import asyncio
import sys
import signal
import argparse
import time
from datetime import datetime, timezone
from typing import Dict, List
import numpy as np
import json
import atexit
import os
import os

# Internal imports (when packaged)
try:
    from polymarket_bot.core.matrix import TransitionMatrix, bin_price
    from polymarket_bot.core.decision import DecisionEngine
    from polymarket_bot.paper_trading import PaperTradingEngine
    from polymarket_bot.config.loader import load_config
    from polymarket_bot.monitoring.logging import setup_logging, get_logger
    from polymarket_bot.monitoring.metrics import MetricsExporter
    from polymarket_bot.monitoring.health import HealthServer
    from polymarket_bot.exchange.client import PolymarketClient as MockClient
    from polymarket_bot.exchange.amm_client import PolymarketAMMClient
except ImportError:
    # When running from source without package install
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from polymarket_bot.core.matrix import TransitionMatrix, bin_price
    from polymarket_bot.core.decision import DecisionEngine
    from polymarket_bot.paper_trading import PaperTradingEngine
    from polymarket_bot.config.loader import load_config
    from polymarket_bot.monitoring.logging import setup_logging, get_logger
    from polymarket_bot.monitoring.metrics import MetricsExporter
    from polymarket_bot.monitoring.health import HealthServer
    from polymarket_bot.exchange.client import PolymarketClient as MockClient
    from polymarket_bot.exchange.amm_client import PolymarketAMMClient



# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()
class TradingBot:
    """
    Main orchestrator for the Markov trading bot.

    Responsibilities:
      - Initialize all subsystems
      - Manage lifecycle (start, stop, restart)
      - Coordinate evaluation across assets and windows
      - Handle shutdown signals
      - Aggregate metrics and logging
    """

    def __init__(self,
                 config_path: str = "config/config.yaml",
                 dry_run: bool = None,
                 log_level: str = None):
        """
        Args:
            config_path: Path to YAML config file
            dry_run: Override config dry_run flag (for CLI flag)
            log_level: Override config log level
        """
        # Load config
        print(f"Loading config from {config_path}...")
        self.config = load_config(config_path)

        # CLI overrides
        if dry_run is not None:
            self.config.app.dry_run = dry_run
        if log_level is not None:
            self.config.monitoring.log_level = log_level

        # Initialize logger
        self.logger = setup_logging(self.config.monitoring)
        self.logger.info("Bot initializing...", config=self.config.app.dict())

        # Components (initialized in async init)
        self.client: Optional[BaseExchangeClient] = None
        self.decision_engine = DecisionEngine(
            tau=self.config.trading.thresholds.tau,
            eps=self.config.trading.thresholds.eps,
            min_probability=self.config.trading.thresholds.min_probability
        )

        # State: one TransitionMatrix per (asset, window)
        self.matrices: Dict[str, TransitionMatrix] = {}

        # Open positions tracking (order_id → position dict)
        self.positions: Dict[str, dict] = {}

        # Portfolio state - set initial value based on mode
        if self.config.app.paper_trading:
            self.initial_balance = self.config.paper_trading.initial_balance
            self.portfolio_value = self.initial_balance
        elif self.config.app.dry_run:
            self.initial_balance = self.config.backtest.initial_capital
            self.portfolio_value = self.initial_balance
        else:
            self.initial_balance = 0.0
            self.portfolio_value = 0.0  # Will be fetched from exchange

        # Control flags
        self.running = False
        self.shutdown_event = asyncio.Event()
        self._shutdown_future: Optional[asyncio.Future] = None  # Set in run()
        self._loop_ref: Optional[asyncio.AbstractEventLoop] = None  # Event loop reference for safe signal handling
        self.shutdown_event_is_set = False  # For test compatibility
        self._last_checkpoint_time: float = 0.0

        # Daily trade limit tracking
        self.daily_trades_count: int = 0
        self.last_trade_date = datetime.now(timezone.utc).date()

        # Services
        self.metrics: Optional[MetricsExporter] = None
        self.health_server: Optional[HealthServer] = None

        # Stats
        self.stats = {
            "trades_entered": 0,
            "trades_settled": 0,
            "total_pnl": 0.0,
            "start_time": None
        }

        # Register signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)


    # ========== Checkpoint persistence ==========

    def _get_checkpoint_path(self) -> str:
        """Return expanded checkpoint file path."""
        return os.path.expanduser(self.config.storage.checkpoint.path)

    def _load_checkpoint(self) -> bool:
        """Load bot state from checkpoint file if it exists.

        Returns:
            bool: True if checkpoint loaded successfully, False otherwise.
        """
        checkpoint_path = self._get_checkpoint_path()
        if not os.path.exists(checkpoint_path):
            self.logger.info("No checkpoint found, starting fresh")
            return False

        try:
            with open(checkpoint_path, 'r') as f:
                data = json.load(f)

            # Restore positions
            self.positions = data.get('positions', {})

            # Restore portfolio value - use appropriate default based on mode
            if self.config.app.paper_trading:
                default_balance = self.config.paper_trading.initial_balance
            else:
                default_balance = self.config.backtest.initial_capital
            self.portfolio_value = data.get('portfolio_value', default_balance)
            
            # Restore daily trade counter
            self.daily_trades_count = data.get('daily_trades_count', 0)
            saved_date_str = data.get('last_trade_date', '')
            if saved_date_str:
                from datetime import date
                try:
                    self.last_trade_date = date.fromisoformat(saved_date_str)
                    # Reset if saved date is not today
                    if self.last_trade_date != datetime.now(timezone.utc).date():
                        self.logger.info(f"New day detected, resetting trade counter (saved: {saved_date_str})")
                        self.daily_trades_count = 0
                        self.last_trade_date = datetime.now(timezone.utc).date()
                except ValueError:
                    self.last_trade_date = datetime.now(timezone.utc).date()
            else:
                self.last_trade_date = datetime.now(timezone.utc).date()

            # Restore stats (merge with defaults)
            saved_stats = data.get('stats', {})
            self.stats.update(saved_stats)

            # Restore matrices
            matrices_data = data.get('matrices', {})
            for key, matrix_dict in matrices_data.items():
                try:
                    matrix = TransitionMatrix.from_dict(matrix_dict)
                    self.matrices[key] = matrix
                    self.logger.info(f"Restored matrix: {key} (transitions={matrix.total_transitions})")
                except Exception as e:
                    self.logger.error(f"Failed to restore matrix {key}", error=str(e))

            self.logger.info("Checkpoint loaded",
                             positions=len(self.positions),
                             matrices=len(self.matrices))
            return True
        except Exception as e:
            self.logger.error("Failed to load checkpoint", error=str(e))
            return False

    def _should_save_checkpoint(self) -> bool:
        """Check if enough time has passed to save checkpoint."""
        if not self.config.storage.checkpoint.enabled:
            return False
        now = time.time()
        interval_seconds = self.config.storage.checkpoint.interval_minutes * 60
        return (now - self._last_checkpoint_time) >= interval_seconds

    async def _save_checkpoint(self) -> None:
        """Save current bot state to checkpoint file."""
        if not self.config.storage.checkpoint.enabled:
            return

        checkpoint_path = self._get_checkpoint_path()
        os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)

        data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'positions': self.positions,
            'portfolio_value': self.portfolio_value,
            'stats': self.stats,
            'daily_trades_count': self.daily_trades_count,
            'last_trade_date': self.last_trade_date.isoformat() if hasattr(self.last_trade_date, 'isoformat') else str(self.last_trade_date),
            'matrices': {key: matrix.to_dict() for key, matrix in self.matrices.items()}
        }

        try:
            with open(checkpoint_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            self._last_checkpoint_time = time.time()
            self.logger.info("Checkpoint saved",
                             path=checkpoint_path,
                             positions=len(self.positions),
                             matrices=len(self.matrices))
            # Update paper trading metrics
            if self.config.app.paper_trading and hasattr(self.client, "get_position_summary"):
                try:
                    summary = self.client.get_position_summary()
                    # P&L = current portfolio value - initial balance ($5000)
                    # This shows ACTUAL current P&L vs initial, not historical cumulative
                    total_balance = summary.get("total_balance", summary.get("current_balance", 0.0))
                    current_pnl = total_balance - self.initial_balance
                    unrealized = summary.get("unrealized_pnl", 0.0)
                    self.metrics.record_paper_pnl(current_pnl, unrealized)
                    self.metrics.record_paper_positions(summary.get("open_positions", 0))
                    if hasattr(self.client, "get_fill_rate"):
                        self.metrics.record_paper_fill_rate(self.client.get_fill_rate())
                except Exception as e:
                    self.logger.warning("Paper metrics update failed", error=str(e))

        except Exception as e:
            self.logger.error("Failed to save checkpoint", error=str(e))

    # ============================================

    def _window_duration_days(self, window: str) -> float:
        """Convert window label to fractional days."""
        mapping = {
            '5m': 5 / (60 * 24),   # 0.00347 days
            '1h': 1 / 24,          # 0.04167 days
            '6h': 6 / 24,          # 0.25 days
        }
        return mapping.get(window, 1.0)

    def _get_market_volatility(self, asset_key: str) -> float:
        """Fetch volatility from market config, default 0.03."""
        asset_cfg = self.config.trading.assets.get(asset_key)
        if asset_cfg:
            # Use per-market volatility if set in future; for now, default
            return getattr(asset_cfg, 'volatility', 0.03)
        return 0.03

    async def _recompute_p_hat(self, asset: str, window: str, price: float) -> float:
        """Recompute p_hat from current matrix for exit decision."""
        key = f"{asset}:{window}"
        matrix = self.matrices.get(key)
        if matrix and matrix.is_valid:
            P = matrix.get_matrix()
            n_states = self.config.trading.markov.n_states
            from polymarket_bot.core.matrix import bin_price
            state = bin_price(price, n_states=n_states)
            _, meta = self.decision_engine.should_enter(P, state, price)
            return meta.get('p_hat', 0.5)
        # fallback: use stored position p_hat (handled outside)
        return 0.5

    def _resolve_market_id(self, asset_cfg, window: str) -> str:
        """Build correct market_id for asset+window.
        Crypto assets (BTC, ETH, TAO, HL, HYPERLIQUID): use symbol + '_' + window.upper().
        Weather/exotic assets: use config market_id (base) + '_' + window.upper().
        """
        crypto = ('BTC', 'ETH', 'TAO', 'HL', 'HYPERLIQUID', 'HYPE', 'SOL')
        if asset_cfg.symbol in crypto:
            return f"{asset_cfg.symbol}_{window.upper()}"
        else:
            base = asset_cfg.market_id
            return f"{base}_{window.upper()}"

    async def check_exits(self) -> None:
        """Evaluate all open positions for optimal exit via Bellman stopping."""
        print("[EXIT] Checking exits for open positions...", flush=True)
        now = datetime.now(timezone.utc)
        to_close = []
        force_timeout_hours = 4  # Force exit after 4 hours

        for order_id, pos in list(self.positions.items()):
            try:
                asset = pos['asset']
                window = pos['window']
                asset_cfg = self.config.trading.assets.get(asset)
                if not asset_cfg:
                    self.logger.warning("Unknown asset in position", asset=asset, order_id=order_id)
                    continue
                
                # Safely parse entry_time (could be string or datetime from checkpoint)
                entry_time_raw = pos['entry_time']
                if isinstance(entry_time_raw, str):
                    entry_dt = datetime.fromisoformat(entry_time_raw).replace(tzinfo=timezone.utc)
                elif isinstance(entry_time_raw, datetime):
                    entry_dt = entry_time_raw
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=timezone.utc)
                else:
                    self.logger.error("Invalid entry_time format", order_id=order_id, type=type(entry_time_raw))
                    continue
                
                # Force exit if position is too old
                now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
                hours_open = (now_utc - entry_dt).total_seconds() / 3600
                force_exit = hours_open >= force_timeout_hours
                
                if force_exit:
                    self.logger.warning(f"Force exit: position open for {hours_open:.1f}h >= {force_timeout_hours}h", 
                                      order_id=order_id, asset=asset)

                # Get current price
                # Build correct market_id format: for weather assets, append window (e.g. LON_RAIN -> LON_RAIN_1H)
                market_id = self._resolve_market_id(asset_cfg, window)
                current_price = await self.client.get_ticker(market_id)

                # Recompute p_hat from latest matrix (best effort)
                p_hat = await self._recompute_p_hat(asset, window, current_price)
                if p_hat == 0.5:  # fallback, use stored if available
                    p_hat = pos.get('p_hat', 0.5)

                # Compute remaining time to expiry
                total_days = self._window_duration_days(window)
                # entry_dt already parsed above, reuse it
                now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
                elapsed_days = (now_utc - entry_dt).total_seconds() / 86400
                remaining_days = max(0.01, total_days - elapsed_days)

                sigma = self._get_market_volatility(asset)

                # Bellman exit decision
                exit_info = self.decision_engine.should_exit(
                    entry_price=pos['entry_price'],
                    entry_shares=pos['shares'],
                    current_price=current_price,
                    p_hat=p_hat,
                    days_to_expiry=int(remaining_days),
                    sigma=sigma
                )
                
                # Force exit if position is too old OR Bellman says exit
                should_exit = exit_info['exit'] or force_exit
                exit_reason = exit_info.get('reason', 'bellman') if not force_exit else f'force_timeout_{hours_open:.1f}h'

                if should_exit:
                    # Check daily trade limit before placing sell order
                    if not self._check_daily_trade_limit():
                        self.logger.warning("Skipping sell - daily limit reached",
                                           order_id=order_id, asset=asset, window=window)
                    else:
                        # Place sell order
                        # market_id already resolved earlier (line 287)
                        sell_order = await self.client.sell(
                            market_id=market_id,
                            outcome_id=0,  # YES
                            price=current_price,
                            amount=pos['shares'],
                            order_type=self.config.trading.execution.order_type,
                            asset=asset,
                            window=window
                        )
                        # PnL from paper trading engine (net of fees)
                        pnl = sell_order.get('pnl', 0.0) if sell_order else 0.0
                        self.stats['total_pnl'] += pnl
                        # Sync portfolio value with paper trading total equity (cash + unrealized)
                        if hasattr(self.client, 'get_total_equity'):
                            self.portfolio_value = self.client.get_total_equity()
                        else:
                            self.portfolio_value += pnl
                        self.stats['trades_settled'] += 1
                        self._increment_daily_trades()
                        to_close.append(order_id)
                        self.logger.info("Position closed",
                                         order_id=order_id, asset=asset, window=window,
                                         price=current_price, pnl=pnl, reason=exit_reason)
                else:
                    # Optional: log threshold info at debug
                    self.logger.debug("Hold position", order_id=order_id,
                                      current=current_price, fair=exit_info['fair_value'],
                                      edge=exit_info['edge'], remaining_days=remaining_days)
            except Exception as e:
                self.logger.error("Exit check error", order_id=order_id, asset=asset, error=str(e))

        # Remove closed positions
        for oid in to_close:
            self.positions.pop(oid, None)



    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals gracefully."""
        self.logger.warning("Signal received", signal=signum)
        print(f"[SIGNAL] Received signal {signum} at {time.time()}", flush=True)
        print("[SIGNAL] _shutdown_future id=%s done=%s" % (id(self._shutdown_future) if self._shutdown_future else "None", self._shutdown_future.done() if self._shutdown_future else "N/A"), flush=True)
        self.running = False
        # Safely resolve shutdown future on the event loop thread to avoid deadlock
        if self._shutdown_future is not None and not self._shutdown_future.done():
            if self._loop_ref is not None:
                self._loop_ref.call_soon_threadsafe(self._shutdown_future.set_result, True)
                print("[SIGNAL] scheduled set_result via call_soon_threadsafe", flush=True)
            else:
                # Loop not available yet; will be handled by early-exit logic in run()
                pass
        else:
            print("[SIGNAL] future is None or already done", flush=True)
        # Safely set the shutdown event for external observers
        if self._loop_ref is not None:
            self._loop_ref.call_soon_threadsafe(self.shutdown_event.set)
        else:
            self.shutdown_event.set()
        self.shutdown_event_is_set = True

    def _check_daily_trade_limit(self) -> bool:
        """Check if we can place more trades today.

        Returns:
            True if we can trade, False if daily limit reached
        """
        current_date = datetime.now(timezone.utc).date()
        max_trades = self.config.risk.max_daily_trades

        # Reset counter if new day
        if current_date != self.last_trade_date:
            self.daily_trades_count = 0
            self.last_trade_date = current_date
            self.logger.info("New day, resetting daily trade counter")

        # Check limit
        if self.daily_trades_count >= max_trades:
            self.logger.warning("Daily trade limit reached",
                               count=self.daily_trades_count,
                               limit=max_trades)
            return False
        return True

    def _increment_daily_trades(self) -> None:
        """Increment the daily trade counter."""
        self.daily_trades_count += 1
        self.logger.debug("Daily trade count",
                          count=self.daily_trades_count,
                          limit=self.config.risk.max_daily_trades)

    async def initialize(self) -> None:
        """Connect to exchange and initialize all matrices."""
        self.logger.info("Initializing exchange connection...")
        # Choose client based on mode
        if self.config.app.paper_trading:
            # Paper trading mode — wrap client in PaperTradingEngine
            self.logger.info("Paper trading mode enabled — simulating orders")
            if self.config.app.dry_run:
                # Dry run + paper trading: use mock client wrapped in PaperTradingEngine
                from polymarket_bot.exchange.client import PolymarketClient as MockClient
                live_client = MockClient(
                    dry_run=True,
                    sandbox=False,
                    base_url=self.config.exchange.api.base_url,
                    ws_url=self.config.exchange.api.ws_url
                )
                await live_client.connect()
            else:
                # Live + paper trading: use real client wrapped in PaperTradingEngine
                from polymarket_bot.exchange.amm_client import PolymarketAMMClient
                live_client = PolymarketAMMClient(
                    self.config,
                    dry_run=False,
                    sandbox=False,
                    amm_base_url=self.config.exchange.amm.base_url,
                    gas_limit=self.config.exchange.amm.gas_limit,
                    gas_price_gwei=self.config.exchange.amm.gas_price_gwei,
                    wallet_address=self.config.exchange.auth.wallet_address,
                    private_key=self.config.exchange.auth.private_key or '',
                )
                await live_client.connect()
            self.client = PaperTradingEngine(live_client, self.config)
        elif self.config.app.dry_run:
            # Dry run only (no paper trading) — use mock client
            from polymarket_bot.exchange.client import PolymarketClient as MockClient
            self.client = MockClient(
                dry_run=True,
                sandbox=False,
                base_url=self.config.exchange.api.base_url,
                ws_url=self.config.exchange.api.ws_url
            )
            await self.client.connect()
        else:
            # Live mode — use real client
            from polymarket_bot.exchange.amm_client import PolymarketAMMClient
            self.client = PolymarketAMMClient(
                self.config,
                dry_run=False,
                sandbox=False,
                amm_base_url=self.config.exchange.amm.base_url,
                gas_limit=self.config.exchange.amm.gas_limit,
                gas_price_gwei=self.config.exchange.amm.gas_price_gwei,
                wallet_address=self.config.exchange.auth.wallet_address,
                private_key=self.config.exchange.auth.private_key or '',
            )
            await self.client.connect()

        # Fetch markets and create matrices for each enabled asset/window
        markets = await self.client.get_markets()
        self.logger.info(f"Markets loaded: {len(markets)}")

        # Create matrix for each (asset, window) combo
        for asset_key, asset_cfg in self.config.trading.assets.items():
            if not asset_cfg.enabled:
                self.logger.info(f"Asset {asset_key} disabled, skipping")
                continue

            for window in asset_cfg.windows:
                key = f"{asset_key}:{window}"
                window_size = self.config.trading.markov.window_sizes.get(
                    window,
                    60 if window == "1h" else 5
                )
                self.matrices[key] = TransitionMatrix(
                    n_states=self.config.trading.markov.n_states,
                    window_size=window_size,
                    smoothing_alpha=self.config.trading.markov.smoothing_alpha,
                    min_transitions=self.config.trading.markov.min_transitions
                )
                self.logger.info(f"Initialized matrix: {key} (window_size={window_size}, n_states={self.config.trading.markov.n_states})")

        self.logger.info(f"Initialized {len(self.matrices)} trading matrices")

        # Initialize monitoring services
        if self.config.monitoring.metrics.enabled:
            self.metrics = MetricsExporter(self.config.monitoring)
            self.logger.info(f"Metrics exporter on port {self.config.monitoring.metrics.port}")

        if self.config.monitoring.health.enabled:
            self.health_server = HealthServer(self.config.monitoring, self)
            await self.health_server.start()
            self.logger.info(f"Health server on port {self.config.monitoring.health.port}")

        # Get initial portfolio value from client (works for dry-run; live mode would need real account call)
        try:
            balance = await self.client.get_balance()
            self.portfolio_value = balance
        except NotImplementedError:
            # Live mode account fetch not implemented, use appropriate initial balance
            if self.config.app.paper_trading:
                self.portfolio_value = self.config.paper_trading.initial_balance
            else:
                self.portfolio_value = self.config.backtest.initial_capital
        self.logger.info(f"Starting portfolio = ${self.portfolio_value:,.2f}")

        self.stats["start_time"] = datetime.now(timezone.utc)
        self.logger.info("✅ Initialization complete", portfolio=self.portfolio_value)

        # Load checkpoint after initialization (restore previous state if available)
        if self.config.storage.checkpoint.enabled:
            self._load_checkpoint()

        # Mark as ready BEFORE returning — prevents shutdown race where signal arrives
        # between initialize() completing and run() setting self.running = True
        self.running = True

    async def evaluate_one(self, asset: str, window: str) -> None:
        """
        Evaluate a single (asset, window) combination for entry.

        Steps:
          1. Get current matrix P for this combo
          2. Get current market price via API
          3. Bin price → state index
          4. Call decision_engine.should_enter()
          5. If True: compute position size, place order
          6. Record metrics
        """
        print(f"[EVAL] start {asset}:{window}", flush=True)
        key = f"{asset}:{window}"
        matrix = self.matrices.get(key)
        if matrix is None:
            return

        # Get current price first (needed to update the matrix)
        asset_cfg = self.config.trading.assets[asset]
        market_id = self._resolve_market_id(asset_cfg, window)

        # Record matrix health metrics (even if ticker fails)
        if self.metrics:
            try:
                diag_mean = float(np.diag(matrix.P).mean()) if matrix.is_valid else 0.0
                self.metrics.record_matrix_stats(
                    asset=asset,
                    window=window,
                    transitions=matrix.total_transitions,
                    valid=matrix.is_valid,
                    diag_mean=diag_mean
                )
            except Exception as e:
                self.logger.error("Failed to record matrix metrics", asset=asset, window=window, error=str(e))

        try:
            price = await self.client.get_ticker(asset, window)
            matrix.update(price)
            # Mark-to-market update for paper trading (if client supports it)
            if hasattr(self.client, "update_market_prices"):
                self.client.update_market_prices({asset: price})
        except Exception as e:
            self.logger.error("Failed to get ticker", asset=asset, window=window, error=str(e))
            return

        # Get updated matrix (may be None until enough transitions collected)
        P = matrix.get_matrix()
        if P is None:
            self.logger.debug("Matrix not ready (insufficient data)", asset=asset, window=window)
            return

        # Bin price
        n_states = self.config.trading.markov.n_states
        state = bin_price(price, n_states=n_states)

        # Evaluate entry
        decision, meta = self.decision_engine.should_enter(P, state, price)

        if decision:
            # Risk check: max open positions (global)
            if len(self.positions) >= self.config.risk.max_open_positions:
                self.logger.debug("Max positions reached, skipping", asset=asset, window=window)
                return

            # Risk check: per-asset position limit (diversification / correlation)
            asset_pos_count = sum(1 for p in self.positions.values() if p.get('asset') == asset)
            max_per_asset = getattr(self.config.risk, 'max_positions_per_asset', 2)
            if asset_pos_count >= max_per_asset:
                self.logger.debug("Max per-asset positions reached, skipping",
                                  asset=asset, window=window, count=asset_pos_count, limit=max_per_asset)
                return

            # Risk check: total exposure cap
            capital, shares = self.decision_engine.position_size(
                portfolio_value=self.portfolio_value,
                p_hat=meta["p_hat"],
                market_price=price,
                cap_max=self.config.trading.position.kelly.get("cap_max", 0.80),
                cap_min=self.config.trading.position.kelly.get("cap_min", 0.05)
            )

            # Risk check: per-position limit
            max_pos = min(asset_cfg.max_position_usd, self.config.risk.max_position_size_usd)
            if capital > max_pos:
                self.logger.info("Position size capped",
                                 asset=asset, requested=capital, capped=max_pos)
                capital = max_pos
                shares = int(capital / price)

            if shares < 1:
                self.logger.debug("Position too small (<1 share)", asset=asset, capital=capital)
                return

            # Risk check: total portfolio exposure cap
            total_exposed = sum(p['shares'] * p['entry_price'] for p in self.positions.values())
            max_total = getattr(self.config.risk, 'max_total_exposure_usd', None)
            if max_total and (total_exposed + capital) > max_total:
                self.logger.info("Total exposure cap hit, reducing position",
                                 asset=asset, requested=capital,
                                 total_exposed=total_exposed, cap=max_total)
                capital = max(0, max_total - total_exposed)
                shares = int(capital / price) if capital > 0 else 0
                if shares < 1:
                    return

            # Check daily trade limit before placing order
            if not self._check_daily_trade_limit():
                self.logger.warning("Skipping trade - daily limit reached", asset=asset, window=window)
                return

            # Place order
            try:
                order = await self.client.buy(
                    market_id=market_id,
                    outcome_id=0,  # YES
                    price=price,
                    amount=shares,
                    order_type=self.config.trading.execution.order_type
                )

                # Track position
                self.positions[order["order_id"]] = {
                    "asset": asset,
                    "window": window,
                    "entry_price": price,
                    "shares": shares,
                    "entry_time": datetime.now(timezone.utc).isoformat(),
                    "kelly_fraction": self.decision_engine.kelly_fraction(meta["p_hat"], price),
                    "p_hat": meta["p_hat"],
                    "persist": meta["persist"],
                    "gap": meta["gap"],
                    "order_id": order["order_id"]
                }

                # Sync portfolio value with paper trading total equity
                if hasattr(self.client, 'get_total_equity'):
                    self.portfolio_value = self.client.get_total_equity()

                self.stats["trades_entered"] += 1
                self._increment_daily_trades()
                self.logger.info("Trade entered",
                                 asset=asset, window=window, price=price,
                                 shares=shares, capital=capital,
                                 p_hat=meta["p_hat"], persist=meta["persist"], gap=meta["gap"],
                                 kelly=self.decision_engine.kelly_fraction(meta["p_hat"], price),
                                 portfolio=self.portfolio_value)

                # Metrics
                if self.metrics:
                    self.metrics.record_trade(
                        asset=asset, window=window,
                        entry_price=price, shares=shares,
                        p_hat=meta["p_hat"], persist=meta["persist"]
                    )

            except Exception as e:
                self.logger.error("Order failed", asset=asset, error=str(e))
                if self.metrics:
                    self.metrics.record_error("order_failed")

        else:
            # Log why we didn't enter (at debug level)
            self.logger.debug("No entry",
                              asset=asset, window=window, price=price,
                              p_hat=meta.get("p_hat", 0), persist=meta.get("persist", 0),
                              gap=meta.get("gap", 0),
                              gap_ok=meta.get("cond_gap", False),
                              persist_ok=meta.get("cond_persist", False))
    async def shutdown(self) -> None:
        """Graceful shutdown."""
        print("[SHUTDOWN] Starting...", flush=True)
        self.logger.info("Shutting down...")
        self.running = False

        # Disconnect exchange
        if self.client:
            print("[SHUTDOWN] Disconnecting client...", flush=True)
            await self.client.disconnect()
            print("[SHUTDOWN] Client disconnected", flush=True)

        # Stop metrics exporter
        if self.metrics:
            print("[SHUTDOWN] Stopping metrics...", flush=True)
            await self.metrics.stop()
            print("[SHUTDOWN] Metrics stopped", flush=True)

        # Stop health server
        if self.health_server:
            print("[SHUTDOWN] Stopping health server...", flush=True)
            await self.health_server.stop()
            print("[SHUTDOWN] Health server stopped", flush=True)

        # Save checkpoint (persist state to disk)
        await self._save_checkpoint()

        # Compute runtime safely even if initialization failed before start_time was set
        start = self.stats.get("start_time")
        runtime = str(datetime.now(timezone.utc) - start) if start else "N/A"
        self.logger.info("Shutdown complete",
                         trades=self.stats["trades_entered"],
                         runtime=runtime)
        print("👋 Bot stopped")



    async def evaluation_loop(self) -> None:
        """
        Main loop: run once per minute across all assets/windows.
        """
        while self.running:
            print("[EVAL] Loop iteration start", flush=True)
            loop_start = asyncio.get_event_loop().time()
            
            # Safety check: if portfolio value dropped below 50% of initial, stop trading
            initial_balance = self.config.paper_trading.initial_balance if self.config.app.paper_trading else self.config.backtest.initial_capital
            if self.portfolio_value < initial_balance * 0.5:
                self.logger.error(f"EMERGENCY STOP: Portfolio value ${self.portfolio_value:.2f} < 50% of initial ${initial_balance:.2f}")
                self.running = False
                break
            
            # Also check paper trading balance
            if self.config.app.paper_trading and hasattr(self.client, 'get_balance'):
                current_balance = await self.client.get_balance()
                if current_balance < initial_balance * 0.3:  # Stop if less than 30% left
                    self.logger.error(f"EMERGENCY STOP: Paper balance ${current_balance:.2f} < 30% of initial")
                    self.running = False
                    break

            # Sync portfolio value with paper trading total equity (net of fees)
            if hasattr(self.client, 'get_total_equity'):
                self.portfolio_value = self.client.get_total_equity()

            # Dynamic discovery: refresh latest markets from Polymarket
            if hasattr(self.client, "refresh_markets"):
                await self.client.refresh_markets()

            # Check exits first (Bellman optimal stopping)
            await self.check_exits()

            # Refresh current_price for all open positions (for checkpoint P&L tracking)
            for pos in self.positions.values():
                try:
                    asset = pos['asset']
                    asset_cfg = self.config.trading.assets.get(asset)
                    if asset_cfg:
                        window_pos = pos.get('window', '5m')
                        # _resolve_market_id now handles the window mapping
                        market_id = self._resolve_market_id(asset_cfg, window_pos)
                        # AMMClient.get_ticker(asset, window)
                        pos['current_price'] = await self.client.get_ticker(asset, window_pos)
                        entry = pos['entry_price']
                        current = pos['current_price']
                        pos['unrealized_pnl'] = (current - entry) * pos['shares']
                        pos['unrealized_pct'] = ((current - entry) / entry) * 100 if entry > 0 else 0.0
                        pos['hold_time_seconds'] = (datetime.now(timezone.utc) -
                                                     datetime.fromisoformat(pos['entry_time'])).total_seconds()
                except Exception:
                    pass  # ignore per-position refresh errors

            # Create evaluation tasks for all (asset, window) combos
            tasks = []
            for asset_cfg_key, asset_cfg in self.config.trading.assets.items():
                if not asset_cfg.enabled:
                    continue
                for window in asset_cfg.windows:
                    tasks.append(self.evaluate_one(asset_cfg_key, window))

            print(f"[EVAL] Running gather for {len(tasks)} tasks", flush=True)
            # Run concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            print(f"[EVAL] Gather completed, results count={len(results)}", flush=True)

            # Log any exceptions
            for result in results:
                if isinstance(result, Exception):
                    self.logger.error("Evaluation error", error=str(result))

            # Update portfolio metrics
            if self.metrics:
                self.metrics.portfolio_value(self.portfolio_value)
                self.metrics.open_positions(len(self.positions))
            print("[EVAL] Metrics updated", flush=True)

            # Periodic checkpoint save
            if self._should_save_checkpoint():
                await self._save_checkpoint()

            # Sleep until next minute (interruptible by shutdown_event)
            elapsed = asyncio.get_event_loop().time() - loop_start
            sleep_time = max(0, 60.0 - elapsed)
            print("[EVAL] About to sleep/wait (sleep_time=%.2f)" % sleep_time, flush=True)
            if sleep_time > 0 and self.running:
                # Wait for either shutdown signal or sleep timeout using future (no race)
                sleep_task = asyncio.create_task(asyncio.sleep(sleep_time))
                
                # If _shutdown_future is None (e.g. in tests calling loop directly), 
                # we just wait for the sleep task.
                if self._shutdown_future:
                    done, pending = await asyncio.wait(
                        [self._shutdown_future, sleep_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                else:
                    await sleep_task
                    done, pending = {sleep_task}, set()
                
                if sleep_task in pending:
                    sleep_task.cancel()
            print("[EVAL] After sleep/wait block", flush=True)
            print("[EVAL] Loop iteration complete, running=" + str(self.running), flush=True)


    async def run(self) -> None:
        """Main entry point."""
        print("[RUN] Starting bot run", flush=True)
        try:
            print("[RUN] Initializing...", flush=True)
            await self.initialize()
            # Capture the running event loop for safe signal handling
            self._loop_ref = asyncio.get_running_loop()
            # If a shutdown signal arrived during initialize(), respect it
            if not self.running:
                self.logger.info("Shutdown requested during initialization, exiting")
                return
            self.running = True
            print("[RUN] Initialized, running=True", flush=True)
            # Initialize shutdown future for clean wakeup from sleep
            self._shutdown_future = self._loop_ref.create_future()
            self.logger.info("🚀 Bot starting evaluation loop...", dry_run=self.config.app.dry_run)

            # Run main loop
            await self.evaluation_loop()
            print("[RUN] evaluation_loop returned", flush=True)

        except asyncio.CancelledError:
            self.logger.info("Bot cancelled")
            print("[RUN] CancelledError", flush=True)
        except Exception as e:
            self.logger.error("Fatal error", error=str(e), exc_info=True)
            print(f"[RUN] Exception: {e}", flush=True)
            raise
        finally:
            print("[RUN] Entering finally, calling shutdown", flush=True)
            await self.shutdown()
            print("[RUN] Shutdown complete", flush=True)

def parse_args(argv=None):
    """Parse command-line arguments. If argv=None, uses sys.argv[1:]."""
    parser = argparse.ArgumentParser(
        description="Polymarket Markov Trading Bot"
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to config YAML file (default: config/config.yaml)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Enable paper trading (no real orders)"
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Disable dry-run → live trading (USE WITH CAUTION)"
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override config log level"
    )
    return parser.parse_args(argv)


def main():
    """Synchronous entry point."""
    args = parse_args()
    bot = TradingBot(
        config_path=args.config,
        dry_run=args.dry_run,
        log_level=args.log_level
    )
    try:
        # Start the async lifecycle manually (no TradingBot.run method)
        asyncio.run(_start_bot(bot))
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


async def _start_bot(bot: TradingBot) -> None:
    """Initialize, run evaluation loop, and shutdown."""
    await bot.initialize()
    bot.running = True
    loop = asyncio.get_running_loop()
    bot._shutdown_future = loop.create_future()
    try:
        await bot.evaluation_loop()
    finally:
        await bot.shutdown()

if __name__ == "__main__":
    main()





