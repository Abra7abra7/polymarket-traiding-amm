"""
Paper Trading Module — Simulates order execution with real-time market data.

Wraps a live exchange client. All read-only calls (get_ticker, get_markets, get_balance)
are delegated to the underlying live client. Buy/sell calls are simulated with spread,
slippage, partial fills, and latency. Positions and P&L are recorded locally.

Configure in config.yaml:
  app:
    dry_run: false
    paper_trading: true   # ← enable paper trading
  paper_trading:
    spread_bps: 200       # simulated spread (basis points)
    slippage_bps: 50      # size-based slippage
    fill_latency_ms: 200  # artificial delay before fill
    partial_fill_prob: 0.1  # 10% chance order not filled
    data_dir: ~/.trading_bot
"""

import asyncio
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List
import random

from .exchange.interface import BaseExchangeClient
from polymarket_bot.config.loader import FullConfig

logger = logging.getLogger(__name__)

@dataclass
class SimulatedPosition:
    asset: str
    side: str  # "long" or "short"
    outcome_id: int
    entry_price: float  # fill price (includes spread/slippage)
    size: float  # USD notional
    quantity: int  # number of contracts
    entry_time: str
    current_price: float
    current_pnl: float
    max_price: float = 0.0
    min_price: float = 1e9

class PaperTradingEngine(BaseExchangeClient):
    """
    Wrapper around a live client that simulates order execution.
    Exposes the same async interface as BaseExchangeClient.
    """

    def __init__(self, wrapped_client: BaseExchangeClient, config: FullConfig):
        self.wrapped = wrapped_client
        self.config = config
        self.positions: Dict[str, SimulatedPosition] = {}
        self.trade_log: List[Dict] = []
        pt_config = config.paper_trading
        self.initial_balance = pt_config.initial_balance
        self.current_balance = self.initial_balance
        self.spread_bps = pt_config.spread_bps
        self.slippage_bps = pt_config.slippage_bps
        self.fill_latency_ms = pt_config.fill_latency_ms
        self.partial_fill_prob = pt_config.partial_fill_prob
        data_dir = Path(pt_config.data_dir).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)
        self.positions_file = data_dir / "paper_positions.json"
        self.trades_file = data_dir / "paper_trades.json"
        self.total_orders = 0
        self.filled_orders = 0
        self._load_state()

    @property
    def connected(self) -> bool:
        """Forward connectivity status from the wrapped live client."""
        return getattr(self.wrapped, "connected", False)

    async def refresh_markets(self) -> None:
        """Forward refresh call to underlying live client."""
        if hasattr(self.wrapped, "refresh_markets"):
            await self.wrapped.refresh_markets()

    def _load_state(self):
        if self.positions_file.exists():
            with open(self.positions_file) as f:
                raw = json.load(f)
            for pid, pos in raw.items():
                self.positions[pid] = SimulatedPosition(**pos)
        if self.trades_file.exists():
            with open(self.trades_file) as f:
                self.trade_log = [json.loads(line) for line in f if line.strip()]

    def _save_state(self):
        with open(self.positions_file, 'w') as f:
            json.dump({k: asdict(v) for k, v in self.positions.items()}, f, indent=2)
        if self.trade_log:
            with open(self.trades_file, 'a') as f:
                for t in self.trade_log:
                    f.write(json.dumps(t) + "\n")
            self.trade_log.clear()

    def _apply_spread(self, price: float, side: str) -> float:
        spread = price * (self.spread_bps / 10000)
        return price + spread/2 if side == "buy" else price - spread/2

    def _simulate_fill(self, order: Dict) -> Dict:
        """Simulate execution with latency, slippage, partial fill."""
        fill_price = self._apply_spread(order["price"], order["side"])
        slippage = fill_price * (self.slippage_bps / 10000) * max(1, order.get("size", 1) / 1000)
        if order["side"] == "buy":
            fill_price += slippage
        else:
            fill_price -= slippage
        filled = random.random() > self.partial_fill_prob
        return {"filled": filled, "fill_price": fill_price if filled else None, "filled_amount": order.get("amount", 1) if filled else 0}

    # ——— BaseExchangeClient interface ———
    async def connect(self) -> None:
        await self.wrapped.connect()

    async def disconnect(self) -> None:
        await self.wrapped.disconnect()

    async def __aenter__(self):
        await self.wrapped.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.wrapped.__aexit__(exc_type, exc, tb)

    async def get_markets(self) -> List[Dict]:
        return await self.wrapped.get_markets()

    async def get_ticker(self, *args, **kwargs) -> float:
        """
        Flexible ticker fetch for both AMM (asset+window) and CLOB (market_id) styles.

        Accepts either:
          - get_ticker(asset, window)       → AMM style
          - get_ticker(market_id)           → CLOB style
          - get_ticker(asset=.., window=..) → AMM style
          - get_ticker(market_id=..)        → CLOB style
        """
        # Determine call pattern
        asset = kwargs.get('asset')
        window = kwargs.get('window')
        market_id = kwargs.get('market_id')

        if len(args) == 1:
            # Single positional → treat as market_id
            market_id = args[0]
        elif len(args) == 2:
            # Two positionals → asset, window
            asset, window = args
        elif args:
            raise TypeError(f"get_ticker() takes 1 or 2 positional args but {len(args)} were given")

        # If market_id provided (via positional or kw), convert to asset+window
        if market_id is not None:
            parts = str(market_id).split('_')
            if len(parts) >= 2:
                asset = parts[0]
                # Normalize window to lowercase (e.g., "5M" → "5m", "1H" → "1h")
                window = parts[1].lower()
            else:
                raise ValueError(f"Cannot parse market_id '{market_id}' into asset/window")

        if asset is None or window is None:
            raise TypeError("get_ticker() requires either (asset, window) or market_id")

        return await self.wrapped.get_ticker(asset, window)

    async def get_volume_24h(self, *args, **kwargs) -> float:
        """
        Accepts either (market_id) or (asset, window). Converts to asset+window for AMM backend.
        """
        asset = kwargs.get('asset')
        window = kwargs.get('window')
        market_id = kwargs.get('market_id')

        if len(args) == 1:
            market_id = args[0]
        elif len(args) == 2:
            asset, window = args
        elif args:
            raise TypeError(f"get_volume_24h() takes 1 or 2 positional args but {len(args)} were given")

        if market_id is not None:
            parts = str(market_id).split('_')
            if len(parts) >= 2:
                asset = parts[0]
                window = parts[1].lower()
            else:
                raise ValueError(f"Cannot parse market_id '{market_id}'")

        if asset is None or window is None:
            raise TypeError("get_volume_24h() requires either (asset, window) or market_id")

        # Note: AMMClient may not implement get_volume_24h; wrapped_live might.
        # We forward asset+window; if underlying expects market_id, it's up to wrapper.
        return await self.wrapped.get_volume_24h(asset, window)

    async def get_balance(self) -> float:
        # Return simulated cash balance
        return self.current_balance

    async def buy(self, market_id: str, outcome_id: int = 0, price: Optional[float] = None, amount: int = 1, order_type: str = "limit") -> Optional[Dict]:
        """Simulate buy — creates/augments long position."""
        size_usd = price * amount if price else 100  # default notional
        result = self._simulate_fill({"side": "buy", "price": price, "size": size_usd})
        self.total_orders += 1
        if result["filled"]:
            self.filled_orders += 1
        if not result["filled"]:
            logger.info(f"[PAPER] BUY not filled: {market_id} ${size_usd}")
            return None
        fill_price = result["fill_price"]
        quantity = int(size_usd / fill_price) if fill_price > 0 else 0
        asset = market_id.split('_')[0]
        pid = f"{asset}:{outcome_id}"
        pos = SimulatedPosition(
            asset=asset,
            side="long",
            outcome_id=outcome_id,
            entry_price=fill_price,
            size=size_usd,
            quantity=quantity,
            entry_time=datetime.utcnow().isoformat(),
            current_price=fill_price,
            current_pnl=0.0,
            max_price=fill_price,
            min_price=fill_price
        )
        self.positions[pid] = pos
        self.current_balance -= size_usd
        self.trade_log.append({
            "time": pos.entry_time,
            "asset": asset,
            "side": "buy",
            "price": fill_price,
            "size_usd": size_usd,
            "quantity": quantity,
            "type": "entry"
        })
        logger.info(f"[PAPER] BUY filled: {asset} ${size_usd} @ {fill_price:.4f}")
        self._save_state()
        return {"filled": True, "price": fill_price, "quantity": quantity, "status": "filled"}

    async def sell(self, market_id: str, outcome_id: int = 0, price: Optional[float] = None, amount: int = 1, order_type: str = "limit") -> Optional[Dict]:
        """Simulate sell — exits long or opens short."""
        asset = market_id.split('_')[0]
        pid = f"{asset}:{outcome_id}"
        if pid in self.positions:
            # Exit long
            pos = self.positions[pid]
            fill_price_ask = self._apply_spread(price, "sell")  # selling at bid side
            slippage = fill_price_ask * (self.slippage_bps / 10000) * (pos.size / 1000)
            fill_price = fill_price_ask - slippage
            pnl = pos.size * (fill_price - pos.entry_price) / pos.entry_price
            self.current_balance += pos.size + pnl
            self.trade_log.append({
                "time": datetime.utcnow().isoformat(),
                "asset": asset,
                "side": "sell",
                "price": fill_price,
                "size_usd": pos.size,
                "quantity": pos.quantity,
                "type": "exit",
                "entry_price": pos.entry_price,
                "pnl": pnl
            })
            logger.info(f"[PAPER] SELL (exit) filled: {pid} @ {fill_price:.4f} P&L=${pnl:.2f}")
            del self.positions[pid]
            self._save_state()
            return {"filled": True, "price": fill_price, "pnl": pnl, "status": "filled"}
        else:
            # Open short
            size_usd = price * amount if price else 100
            result = self._simulate_fill({"side": "sell", "price": price, "size": size_usd})
        self.total_orders += 1
        if result["filled"]:
            self.filled_orders += 1
            if not result["filled"]:
                logger.info(f"[PAPER] SELL (short) not filled: {market_id}")
                return None
            fill_price = result["fill_price"]
            quantity = int(size_usd / fill_price) if fill_price > 0 else 0
            pos = SimulatedPosition(
                asset=asset,
                side="short",
                outcome_id=outcome_id,
                entry_price=fill_price,
                size=size_usd,
                quantity=quantity,
                entry_time=datetime.utcnow().isoformat(),
                current_price=fill_price,
                current_pnl=0.0,
                max_price=fill_price,
                min_price=fill_price
            )
            self.positions[pid] = pos
            self.current_balance += size_usd  # receive cash from short sale
            self.trade_log.append({
                "time": pos.entry_time,
                "asset": asset,
                "side": "sell_short",
                "price": fill_price,
                "size_usd": size_usd,
                "quantity": quantity,
                "type": "entry"
            })
            logger.info(f"[PAPER] SELL (short) filled: {asset} ${size_usd} @ {fill_price:.4f}")
            self._save_state()
            return {"filled": True, "price": fill_price, "quantity": quantity, "status": "filled"}

    async def get_positions(self) -> Dict:
        return {k: asdict(v) for k, v in self.positions.items()}

    async def cancel_order(self, order_id: str) -> bool:
        # Not simulated — assume no cancellations in paper mode
        return False

    # ——— Helper methods for monitoring ———
    def get_position_summary(self) -> Dict:
        unrealized = sum(p.current_pnl for p in self.positions.values())
        return {
            "open_positions": len(self.positions),
            "current_balance": self.current_balance,
            "unrealized_pnl": unrealized,
            "total_balance": self.current_balance + unrealized
        }

    def update_market_prices(self, price_updates: Dict[str, float]):
        """Update mark-to-market for open positions."""
        for pid, pos in self.positions.items():
            new_price = price_updates.get(pos.asset)
            if not new_price:
                continue
            pos.current_price = new_price
            if pos.side == "long":
                pos.current_pnl = pos.size * (new_price - pos.entry_price) / pos.entry_price
            else:
                pos.current_pnl = pos.size * (pos.entry_price - new_price) / pos.entry_price
            if new_price > pos.max_price:
                pos.max_price = new_price
            if new_price < pos.min_price:
                pos.min_price = new_price

    def get_fill_rate(self) -> float:
        if self.total_orders == 0:
            return 1.0
        return self.filled_orders / self.total_orders

