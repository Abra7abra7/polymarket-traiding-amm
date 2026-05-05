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
    size: float  # USD notional (amount intended for position, excluding fees)
    quantity: int  # number of contracts
    entry_time: str
    current_price: float
    current_pnl: float
    max_price: float = 0.0
    min_price: float = 1e9
    total_cost_usd: float = 0.0  # total USD spent to open (including fees)

class PaperTradingEngine(BaseExchangeClient):
    """
    Wrapper around a live client that simulates order execution.
    Exposes the same async interface as BaseExchangeClient.
    """

    def __init__(self, wrapped_client: BaseExchangeClient, config: FullConfig):
        self.wrapped = wrapped_client
        self._connected = False
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
        # Fees
        self.swap_fee_bps = getattr(pt_config, 'swap_fee_bps', 200)   # default 2%
        self.gas_fee_usd = getattr(pt_config, 'gas_fee_usd', 0.01)    # default $0.01
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
        await self.connect()
        return self

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self):
        await self.wrapped.connect()
        self._connected = True

    async def disconnect(self):
        await self.wrapped.disconnect()
        self._connected = False

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

    async def buy(self, market_id: str, outcome_id: int = 0, price: Optional[float] = None, amount: int = 1, order_type: str = "limit", **kwargs) -> Optional[Dict]:
        """Simulate buy — creates/augments long position.
        
        Args:
            amount: Number of shares to buy (not dollar amount!)
        """
        if not price or price <= 0:
            logger.info(f"[PAPER] BUY rejected: invalid price {price}")
            return None
        
        # amount = number of shares to buy
        shares_to_buy = amount
        size_usd = price * shares_to_buy  # dollar cost
        
        # Check if we have enough balance
        fee_rate = self.swap_fee_bps / 10000
        fee = size_usd * fee_rate
        gas = self.gas_fee_usd
        total_cost = size_usd + fee + gas
        
        if total_cost > self.current_balance:
            logger.info(f"[PAPER] BUY rejected: insufficient balance ${self.current_balance:.2f} < ${total_cost:.2f}")
            return None
        
        result = self._simulate_fill({"side": "buy", "price": price, "size": size_usd})
        self.total_orders += 1
        if result["filled"]:
            self.filled_orders += 1
        if not result["filled"]:
            logger.info(f"[PAPER] BUY not filled: {market_id} ${size_usd}")
            return None
        
        fill_price = result["fill_price"]
        quantity = shares_to_buy  # Use the actual shares bought, not recalculating
        asset = market_id.split('_')[0]
        pid = f"{asset}:{outcome_id}"

        # Fees
        fee_rate = self.swap_fee_bps / 10000
        fee = size_usd * fee_rate
        gas = self.gas_fee_usd
        total_cost = size_usd + fee + gas

        # Deduct total cost from balance
        self.current_balance -= total_cost

        pos = SimulatedPosition(
            asset=asset,
            side="long",
            outcome_id=outcome_id,
            entry_price=fill_price,
            size=size_usd,
            quantity=quantity,
            entry_time=datetime.utcnow().isoformat(),
            current_price=fill_price,
            current_pnl=(quantity * fill_price) - total_cost,  # net P&L after fees
            max_price=fill_price,
            min_price=fill_price,
            total_cost_usd=total_cost,
        )
        self.positions[pid] = pos
        self.trade_log.append({
            "time": pos.entry_time,
            "asset": asset,
            "side": "buy",
            "price": fill_price,
            "size_usd": size_usd,
            "quantity": quantity,
            "type": "entry",
            "fee_usd": fee,
            "gas_usd": gas,
            "total_cost_usd": total_cost,
        })
        logger.info(f"[PAPER] BUY filled: {asset} ${size_usd} @ {fill_price:.4f} (fee=${fee:.2f}, gas=${gas:.2f})")
        self._save_state()
        return {"filled": True, "price": fill_price, "quantity": quantity, "status": "filled", "order_id": pid, "side": "buy"}

    async def sell(self, market_id: str, outcome_id: int = 0, price: Optional[float] = None, amount: int = 1, order_type: str = "limit", **kwargs) -> Optional[Dict]:
        """Simulate sell — exits long or opens short."""
        asset = kwargs.get('asset')
        window = kwargs.get('window')
        if asset is None:
            asset = market_id.split('_')[0]
        pid = f"{asset}:{outcome_id}"
        if pid in self.positions:
            # Exit long
            pos = self.positions[pid]
            fill_price_ask = self._apply_spread(price, "sell")  # selling at bid side
            slippage = fill_price_ask * (self.slippage_bps / 10000) * (pos.size / 1000)
            fill_price = fill_price_ask - slippage

            # Gross proceeds
            gross_proceeds = pos.quantity * fill_price
            # Fees
            fee_rate = self.swap_fee_bps / 10000
            sell_fee = gross_proceeds * fee_rate
            gas = self.gas_fee_usd
            net_proceeds = gross_proceeds - sell_fee - gas
 
            # P&L: net proceeds - total cost (including buy fees)
            pnl = net_proceeds - pos.total_cost_usd
            # Update balance: add net proceeds (cost already deducted at buy)
            self.current_balance += net_proceeds
 
            self.trade_log.append({
                "time": datetime.utcnow().isoformat(),
                "asset": asset,
                "side": "sell",
                "price": fill_price,
                "size_usd": pos.size,
                "quantity": pos.quantity,
                "type": "exit",
                "entry_price": pos.entry_price,
                "pnl": pnl,
                "sell_fee_usd": sell_fee,
                "gas_usd": gas,
                "net_proceeds": net_proceeds,
            })
            logger.info(f"[PAPER] SELL (exit) filled: {pid} @ {fill_price:.4f} P&L=${pnl:.2f} (fee=${sell_fee:.2f}, gas=${gas:.2f})")
            del self.positions[pid]
            self._save_state()
            return {"filled": True, "price": fill_price, "pnl": pnl, "status": "filled", "order_id": pid, "side": "sell"}
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

            # Fees for short entry
            fee_rate = self.swap_fee_bps / 10000
            fee = size_usd * fee_rate
            gas = self.gas_fee_usd
            # Net cash received: you receive size_usd but pay fee and gas
            net_cash_in = size_usd - fee - gas
            # For short, total_cost_usd is positive inflow (cash received)
            self.current_balance += net_cash_in

            pos = SimulatedPosition(
                asset=asset,
                side="short",
                outcome_id=outcome_id,
                entry_price=fill_price,
                size=size_usd,
                quantity=quantity,
                entry_time=datetime.utcnow().isoformat(),
                current_price=fill_price,
                current_pnl=net_cash_in - (quantity * fill_price),  # net P&L after fees
                max_price=fill_price,
                min_price=fill_price,
                total_cost_usd=net_cash_in,  # positive inflow (cash received)
            )
            self.positions[pid] = pos
            self.trade_log.append({
                "time": pos.entry_time,
                "asset": asset,
                "side": "sell_short",
                "price": fill_price,
                "size_usd": size_usd,
                "quantity": quantity,
                "type": "entry",
                "fee_usd": fee,
                "gas_usd": gas,
                "net_cash_in": net_cash_in,
            })
            logger.info(f"[PAPER] SELL (short) filled: {asset} ${size_usd} @ {fill_price:.4f} (fee=${fee:.2f}, gas=${gas:.2f})")
            self._save_state()
            return {"filled": True, "price": fill_price, "quantity": quantity, "status": "filled", "side": "sell"}

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
        """Update mark-to-market for open positions (net of fees)."""
        for pid, pos in self.positions.items():
            new_price = price_updates.get(pos.asset)
            if not new_price:
                continue
            pos.current_price = new_price
            if pos.side == "long":
                # Net P&L = current value - total cost (including fees)
                current_value = pos.quantity * new_price
                pos.current_pnl = current_value - pos.total_cost_usd
            else:  # short
                # Net P&L = net cash received - current cost to buy back
                current_liability = pos.quantity * new_price
                pos.current_pnl = pos.total_cost_usd - current_liability
            if new_price > pos.max_price:
                pos.max_price = new_price
            if new_price < pos.min_price:
                pos.min_price = new_price

    def get_fill_rate(self) -> float:
        if self.total_orders == 0:
            return 1.0
        return self.filled_orders / self.total_orders

    def get_total_equity(self) -> float:
        """Return total portfolio equity: cash balance + unrealized P&L."""
        unrealized = sum(p.current_pnl for p in self.positions.values())
        return self.current_balance + unrealized

