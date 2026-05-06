import asyncio
import sys
import signal
import argparse
import time
import os
from datetime import datetime, timezone
from typing import Dict, Optional

import numpy as np
from dotenv import load_dotenv

# Internal imports
try:
    from polymarket_bot.core.matrix import TransitionMatrix, bin_price
    from polymarket_bot.core.decision import DecisionEngine
    from polymarket_bot.core.state_manager import StateManager
    from polymarket_bot.core.risk_manager import PortfolioRiskManager
    from polymarket_bot.core.tensor import TensorCore
    from polymarket_bot.paper_trading import PaperTradingEngine
    from polymarket_bot.config.loader import load_config
    from polymarket_bot.monitoring.logging import setup_logging
    from polymarket_bot.monitoring.metrics import MetricsExporter
    from polymarket_bot.monitoring.health import HealthServer
    from polymarket_bot.utils.helpers import resolve_market_id, get_window_duration_days, get_market_volatility
except ImportError:
    # Fallback for development
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from polymarket_bot.core.matrix import TransitionMatrix, bin_price
    from polymarket_bot.core.decision import DecisionEngine
    from polymarket_bot.core.state_manager import StateManager
    from polymarket_bot.core.risk_manager import PortfolioRiskManager
    from polymarket_bot.core.tensor import TensorCore
    from polymarket_bot.paper_trading import PaperTradingEngine
    from polymarket_bot.config.loader import load_config
    from polymarket_bot.monitoring.logging import setup_logging
    from polymarket_bot.monitoring.metrics import MetricsExporter
    from polymarket_bot.monitoring.health import HealthServer
    from polymarket_bot.utils.helpers import resolve_market_id, get_window_duration_days, get_market_volatility

load_dotenv()

class TradingBot:
    """Refactored orchestrator optimized for server deployment."""

    def __init__(self, config_path: str = "config/config.yaml", dry_run: bool = None, log_level: str = None):
        self.config = load_config(config_path)
        
        # CLI Overrides
        if dry_run is not None: self.config.app.dry_run = dry_run
        if log_level is not None: self.config.monitoring.log_level = log_level

        self.logger = setup_logging(self.config.monitoring)
        self.state_manager = StateManager(self.config, self.logger)
        
        self.client = None
        self.decision_engine = DecisionEngine(
            tau=self.config.trading.thresholds.tau,
            eps=self.config.trading.thresholds.eps,
            stop_loss_pct=self.config.trading.thresholds.trailing_stop_pct,
            take_profit_pct=getattr(self.config.trading.thresholds, 'take_profit_pct', 0.07),
            kelly_cap_max=self.config.trading.position.kelly.cap_max,
            kelly_cap_min=self.config.trading.position.kelly.cap_min,
            kelly_fraction=getattr(self.config.trading.position.kelly, 'fraction', 0.5),
            swap_fee=getattr(self.config.paper_trading, 'swap_fee_bps', 150) / 10000.0,
            gas_cost_usd=getattr(self.config.paper_trading, 'gas_fee_usd', 0.01)
        )

        self.tensor_core = TensorCore(
            assets=list(self.config.trading.assets.keys()),
            windows=list(self.config.trading.markov.window_sizes.keys()),
            n_states=self.config.trading.markov.n_states
        )

        self.risk_manager = PortfolioRiskManager(
            max_total_exposure_usd=self.config.risk.max_total_exposure_usd or 100000.0,
            max_single_position_usd=self.config.risk.max_position_size_usd or 5000.0,
            max_positions=self.config.risk.max_open_positions or 5
        )

        self.matrices: Dict[str, TransitionMatrix] = {}
        self.positions: Dict[str, dict] = {}
        self.portfolio_value = self.config.paper_trading.initial_balance if self.config.app.paper_trading else 0.0
        self.running = False
        
        self.shutdown_event = asyncio.Event()
        self.daily_trades_count = 0
        self.last_trade_date = datetime.now(timezone.utc).date()
        self.stats = {"trades_entered": 0, "trades_settled": 0, "total_pnl": 0.0, "start_time": None}

        # Services
        self.metrics = None
        self.health_server = None

        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        self.logger.warning("Signal received, shutting down...", signal=signum)
        self.running = False
        # Set event immediately
        self.shutdown_event.set()

    async def initialize(self):
        """Initialize connections and restore state."""
        self.logger.info("Initializing bot components...")
        
        # Client Setup
        if self.config.app.paper_trading:
            from polymarket_bot.exchange.client import PolymarketClient
            raw_client = PolymarketClient(dry_run=True) 
            self.client = PaperTradingEngine(raw_client, self.config)
        else:
            from polymarket_bot.exchange.amm_client import PolymarketAMMClient
            self.client = PolymarketAMMClient(self.config)

        await self.client.connect()

        # Load State
        checkpoint = self.state_manager.load()
        if checkpoint:
            self.positions = checkpoint.get('positions', {})
            self.portfolio_value = checkpoint.get('portfolio_value', self.config.paper_trading.initial_balance)
            self.stats.update(checkpoint.get('stats', {}))
            self.daily_trades_count = checkpoint.get('daily_trades_count', 0)
            for key, m_data in checkpoint.get('matrices', {}).items():
                self.matrices[key] = TransitionMatrix.from_dict(m_data)
            
            # Sync RiskManager with restored positions
            for pos in self.positions.values():
                self.risk_manager.record_entry(pos['asset'], pos['shares'] * pos['entry_price'])
        else:
            self.portfolio_value = self.config.paper_trading.initial_balance

        # Pre-create missing matrices
        for asset, cfg in self.config.trading.assets.items():
            if cfg.enabled:
                for window in cfg.windows:
                    key = f"{asset}:{window}"
                    if key not in self.matrices:
                        self.matrices[key] = TransitionMatrix(
                            window_size=self.config.trading.markov.window_sizes.get(window, 60),
                            n_states=self.config.trading.markov.n_states
                        )

        # Services
        if self.config.monitoring.metrics.enabled:
            self.metrics = MetricsExporter(self.config.monitoring)
        if self.config.monitoring.health.enabled:
            self.health_server = HealthServer(self.config.monitoring, self)
            await self.health_server.start()

        self.stats["start_time"] = datetime.now(timezone.utc)
        self.running = True

    async def evaluate_one(self, asset: str, window: str):
        """Logic for entering a trade."""
        key = f"{asset}:{window}"
        if key not in self.matrices:
            self.logger.info(f"Creating new matrix for {key}")
            self.matrices[key] = TransitionMatrix(
                window_size=self.config.trading.markov.window_sizes.get(window, 60),
                n_states=self.config.trading.markov.n_states,
                min_transitions=self.config.trading.markov.min_transitions
            )
        matrix = self.matrices[key]

        asset_cfg = self.config.trading.assets[asset]
        market_id = resolve_market_id(asset_cfg, window)

        try:
            price = await self.client.get_ticker(market_id)
            matrix.update(price, label=market_id)
            if not matrix.is_valid: return

            decision, meta = self.decision_engine.should_enter(matrix.get_matrix(), bin_price(price), price)
            
            # Check if we already have an active position for this asset/window combo
            for p in self.positions.values():
                if p.get("asset") == asset and p.get("window") == window:
                    return

            if decision and self.daily_trades_count < self.config.risk.max_daily_trades:
                # Position sizing
                capital, shares = self.decision_engine.position_size(
                    portfolio_value=self.portfolio_value,
                    p_hat=meta["p_hat"],
                    market_price=price
                )
                
                if shares < 1: return

                # RISK CHECK
                violation = self.risk_manager.check_entry(
                    asset=asset,
                    proposed_size_usd=shares * price,
                    correlations={} # Could be expanded later
                )
                if violation:
                    self.logger.warning("Trade blocked by RiskManager", reason=str(violation), asset=asset)
                    return

                order = await self.client.buy(
                    market_id=market_id,
                    outcome_id=0,
                    price=price,
                    amount=shares,
                    order_type=self.config.trading.execution.order_type,
                    asset=asset,
                    window=window
                )
                
                if order:
                    self.positions[order["order_id"]] = {
                        "asset": asset, 
                        "window": window,
                        "entry_price": price, 
                        "shares": shares,
                        "entry_time": datetime.now(timezone.utc).isoformat(),
                        "max_price": price,
                        "current_price": price,
                        "p_hat": meta["p_hat"] # Save p_hat for exit logic
                    }
                    self.risk_manager.record_entry(asset, shares * price)
                    cost = shares * price
                    self.portfolio_value -= cost
                    self.daily_trades_count += 1
                    self.stats["trades_entered"] += 1
                    self.logger.info("Trade entered", asset=asset, price=price, shares=shares, cost=cost)
                    self.state_manager.log_trade({
                        "type": "BUY",
                        "asset": asset,
                        "window": window,
                        "price": price,
                        "shares": shares,
                        "cost": cost,
                        "p_hat": meta["p_hat"],
                        "order_id": order["order_id"]
                    })
        except Exception as e:
            self.logger.error("Evaluation failed", asset=asset, error=str(e))

    async def check_exits(self):
        """Evaluate open positions for optimal exit using Bellman Stopping."""
        to_close = []
        for oid, pos in list(self.positions.items()):
            try:
                asset_cfg = self.config.trading.assets[pos['asset']]
                market_id = resolve_market_id(asset_cfg, pos['window'])
                price = await self.client.get_ticker(market_id)
                
                # Update tracking metrics
                pos['current_price'] = price
                pos['max_price'] = max(pos.get('max_price', 0), price)
                
                # Get latest model prediction for dynamic exit
                key = f"{pos['asset']}:{pos['window']}"
                if key in self.matrices and self.matrices[key].is_valid:
                    _, latest_p_hat = self.matrices[key].most_likely_next_state(bin_price(price))
                    pos['p_hat'] = latest_p_hat

                # Full strategy exit check
                exit_info = self.decision_engine.should_exit(
                    entry_price=pos['entry_price'], 
                    entry_shares=pos['shares'],
                    current_price=price, 
                    p_hat=pos.get('p_hat', 0.5),
                    days_to_expiry=int(get_window_duration_days(pos['window'])),
                    sigma=get_market_volatility(asset_cfg),
                    max_price=pos.get('max_price', 0)
                )

                if exit_info['exit']:
                    order = await self.client.sell(
                        market_id=market_id, 
                        outcome_id=0,
                        amount=pos['shares'], 
                        price=price,
                        order_type=self.config.trading.execution.order_type,
                        asset=pos['asset'],
                        window=pos['window']
                    )
                    if order:
                        to_close.append(oid)
                        proceeds = pos['shares'] * price
                        self.portfolio_value += proceeds
                        pnl = proceeds - (pos['shares'] * pos['entry_price'])
                        self.stats["total_pnl"] = self.stats.get("total_pnl", 0.0) + pnl
                        self.stats["trades_settled"] = self.stats.get("trades_settled", 0) + 1
                        
                        # Update RiskManager
                        self.risk_manager.record_exit(pos['asset'], pos['shares'] * pos['entry_price'])
                        
                        self.logger.info("Position closed", 
                                         asset=pos['asset'], 
                                         reason=exit_info['reason'], 
                                         pnl=pnl,
                                         proceeds=proceeds)
                        self.state_manager.log_trade({
                            "type": "SELL",
                            "asset": pos['asset'],
                            "window": pos['window'],
                            "price": price,
                            "shares": pos['shares'],
                            "proceeds": proceeds,
                            "pnl": pnl,
                            "reason": exit_info['reason'],
                            "entry_price": pos['entry_price'],
                            "hold_duration_sec": (datetime.now(timezone.utc) - datetime.fromisoformat(pos['entry_time'])).total_seconds()
                        })
            except Exception as e:
                self.logger.error("Exit failed", order_id=oid, error=str(e))
        
        for oid in to_close:
            self.positions.pop(oid, None)

    async def evaluation_loop(self):
        self.logger.info("Starting main evaluation loop")
        while self.running:
            try:
                loop_start = time.time()
                
                # Daily Reset
                current_date = datetime.now(timezone.utc).date()
                if current_date > self.last_trade_date:
                    self.logger.info("New day detected, resetting daily trade counter.", 
                                     old_date=self.last_trade_date, 
                                     new_date=current_date)
                    self.daily_trades_count = 0
                    self.last_trade_date = current_date

                # Sync TensorCore with latest matrices
                self.tensor_core.sync(self.matrices)

                if hasattr(self.client, "refresh_markets"): 
                    await self.client.refresh_markets()

                # Synchronize portfolio value with real/simulated balance
                self.portfolio_value = await self.client.get_balance()

                await self.check_exits()

                tasks = []
                for asset, cfg in self.config.trading.assets.items():
                    if cfg.enabled:
                        for w in cfg.windows:
                            tasks.append(self.evaluate_one(asset, w))
                
                await asyncio.gather(*tasks, return_exceptions=True)

                if self.state_manager.should_save():
                    self.state_manager.save({
                        'positions': self.positions,
                        'portfolio_value': self.portfolio_value,
                        'stats': self.stats,
                        'daily_trades_count': self.daily_trades_count,
                        'matrices': {k: m.to_dict() for k, m in self.matrices.items()}
                    })

                # Wait for 1 minute or until shutdown
                elapsed = time.time() - loop_start
                wait_time = max(0, 60 - elapsed)
                try:
                    await asyncio.wait_for(self.shutdown_event.wait(), timeout=wait_time)
                    break # Shutdown event set
                except asyncio.TimeoutError:
                    continue # Regular interval
            except Exception as e:
                self.logger.error("Loop error", error=str(e))
                await asyncio.sleep(10)

    async def shutdown(self):
        self.logger.info("Shutting down safely...")
        self.running = False
        if self.client: await self.client.disconnect()
        if self.health_server: await self.health_server.stop()
        
        self.state_manager.save({
            'positions': self.positions,
            'portfolio_value': self.portfolio_value,
            'stats': self.stats,
            'daily_trades_count': self.daily_trades_count,
            'matrices': {k: m.to_dict() for k, m in self.matrices.items()}
        })
        print("👋 Bot stopped")

async def _start_bot(bot: TradingBot):
    await bot.initialize()
    try:
        await bot.evaluation_loop()
    finally:
        await bot.shutdown()

def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Polymarket Markov Trading Bot")
    parser.add_argument("--config", default="config/config.yaml", help="Path to config YAML file")
    parser.add_argument("--dry-run", action="store_true", default=None, help="Enable paper trading")
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false", help="Disable dry-run")
    parser.add_argument("--log-level", default=None, choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Override log level")
    return parser.parse_args(argv)

def main():
    args = parse_args()
    bot = TradingBot(config_path=args.config, dry_run=args.dry_run, log_level=args.log_level)
    try:
        asyncio.run(_start_bot(bot))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
