"""
Polymarket AMM Exchange Client
Uses Gamma API (same as CLOB) but treats markets as AMM-based liquidity pools.
For AMM, prices are derived from pool reserves and the constant-product formula.
"""
import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Tuple
from decimal import Decimal, ROUND_DOWN
import aiohttp
import structlog
from web3 import Web3, AsyncHTTPProvider
from web3.contract import Contract
from eth_utils import to_checksum_address

from .interface import BaseExchangeClient

logger = structlog.get_logger()

DEFAULT_GAS_LIMIT = 300000
DEFAULT_GAS_PRICE_GWEI = 2

# Polymarket AMM router contract address (Polygon)
# Official Polymarket AMM router — update from docs
POLYMARKET_AMM_ROUTER = os.environ.get(
    "POLYMARKET_AMM_ROUTER",
    "0x0000000000000000000000000000000000000000"  # placeholder
)

class PolymarketAMMClient(BaseExchangeClient):
    """
    AMM-based exchange client for Polymarket.

    Uses the Gamma REST API to fetch market metadata and token IDs.
    Prices are computed from outcomePrices (probabilities) or simulated
    from reserves if available (future extension).

    Trading: submits swap orders via the AMM router contract on-chain.
    """
    
    BASE_GAMMA = "https://gamma-api.polymarket.com"
    BASE_CLOB = "https://clob.polymarket.com"

    def __init__(
        self,
        config: Optional[Any] = None,
        dry_run: bool = False,
        sandbox: bool = False,
        amm_base_url: str = "",
        router_address: str = "",
        gas_limit: int = DEFAULT_GAS_LIMIT,
        gas_price_gwei: int = DEFAULT_GAS_PRICE_GWEI,
        wallet_address: str = "",
        private_key: str = "",
        **kwargs: Any,
    ) -> None:
        self.config = config
        self.dry_run = dry_run
        self.sandbox = sandbox
        self.gamma_base = amm_base_url or self.BASE_GAMMA
        self.router_address = to_checksum_address(router_address) if router_address else None
        self.gas_limit = gas_limit
        self.gas_price_gwei = gas_price_gwei
        self.wallet_address = to_checksum_address(wallet_address) if wallet_address else ""
        self.private_key = private_key or ""

        self._session: Optional[aiohttp.ClientSession] = None
        self._markets: List[Dict] = []
        self._token_id_by_asset: Dict[str, str] = {}      # asset -> YES token id
        self._condition_id_by_asset: Dict[str, str] = {}  # asset -> condition_id
        self._connected = False

        # Web3 (for live on-chain swaps)
        self.w3: Optional[Web3] = None
        self.router_contract: Optional[Contract] = None

    async def connect(self) -> None:
        """Initialize HTTP session and load market data."""
        if self.dry_run:
            self._connected = True
            return

        self._session = aiohttp.ClientSession(
            base_url=self.gamma_base,
            timeout=aiohttp.ClientTimeout(total=10),
        )
        
        # Load all active markets (Gamma API — works without auth)
        resp = await self._public_get("/markets", params={"active": "true", "limit": 2000})
        # Gamma returns list directly
        if isinstance(resp, dict) and "data" in resp:
            self._markets = resp["data"]
        else:
            self._markets = resp if isinstance(resp, list) else []
            
        self._load_asset_maps_from_config()
        self._build_market_maps()
        self._connected = True

    async def refresh_markets(self) -> None:
        """Fetch latest markets from Gamma API and rebuild maps."""
        if self.dry_run or not self._session:
            return
        
        try:
            # Load all markets (limit 2000)
            resp = await self._public_get("/markets", params={"limit": 2000})
            if isinstance(resp, dict) and "data" in resp:
                self._markets = resp["data"]
            else:
                self._markets = resp if isinstance(resp, list) else []
                
            self._build_market_maps()
            # Debug: show first 10 markets
            for i, m in enumerate(self._markets[:10]):
                logger.info(f"Market {i}: {m.get('question')}")
            # Note: we don't reload asset maps from config here to keep manual overrides
            logger.info(f"Refreshed Polymarket AMM markets: {len(self._markets)} loaded")
        except Exception as e:
            logger.error(f"Failed to refresh markets: {e}")

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def _build_market_maps(self) -> None:
        """Populate token/condition maps and create fast condition_id -> market lookup."""
        # Build fast lookup by condition_id
        self._market_by_condition_id: Dict[str, Dict] = {}
        for m in self._markets:
            cid = m.get("conditionId", "")
            if cid:
                self._market_by_condition_id[cid] = m

        # Supplement token/condition maps from markets for any assets not in config
        for m in self._markets:
            cid = m.get("conditionId", "")
            token_ids_raw = m.get("clobTokenIds", "[]")
            try:
                token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
            except Exception:
                token_ids = []
            question = (m.get("question", "") + " " + m.get("slug", "")).upper()
            matched_asset = None
            for asset in ["BTC", "ETH", "HYPE", "SOL", "TAO", "DOGE", "HL"]:
                if asset in question:
                    matched_asset = asset
                    break
            if matched_asset and token_ids:
                yes_token = str(token_ids[0]) if token_ids else ""
                if matched_asset not in self._token_id_by_asset:
                    self._token_id_by_asset[matched_asset] = yes_token
                if matched_asset not in self._condition_id_by_asset:
                    self._condition_id_by_asset[matched_asset] = cid

    def _load_asset_maps_from_config(self) -> None:
        """Populate token_id and condition_id maps from config trading assets."""
        if not hasattr(self, 'config') or not self.config:
            return
        for asset_key, asset_cfg in self.config.trading.assets.items():
            token = getattr(asset_cfg, 'token_id', None)
            cond = getattr(asset_cfg, 'condition_id', None)
            if token:
                if isinstance(token, list):
                    token = token[0]
                self._token_id_by_asset[asset_key] = str(token)
            if cond:
                if isinstance(cond, list):
                    cond = cond[0]
                self._condition_id_by_asset[asset_key] = str(cond)

    async def _public_get(self, path: str, params: Optional[Dict] = None) -> Any:
        if not self._session:
            raise RuntimeError("Client not connected")
        async with self._session.get(path, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"GET {path} failed {resp.status}: {text}")
            return await resp.json()

    async def get_markets(self) -> List[Dict[str, Any]]:
        """Return all markets fetched during connect."""
        return self._markets

    async def get_ticker(self, asset: str, window: str) -> float:
        """Return last traded price for asset+window as float."""
        if self.dry_run:
            import random
            base = 0.50
            noise = random.uniform(-0.05, 0.05)
            last = max(0.01, min(0.99, base + noise))
            return round(float(last), 4)

        # 1. Lookup market via condition_id from config
        cid = self._condition_id_by_asset.get(asset)
        market = None
        if cid:
            market = self._market_by_condition_id.get(cid)
        
        # 2. Dynamic discovery: if not found, search by symbol + window
        if not market:
            # Extract base symbol if asset is named like SYMBOL_WINDOW
            base_symbol = asset.split('_')[0].upper()
            window_clean = window.lower()
            
            # Symbol aliases for better matching
            symbol_aliases = {
                "BTC": ["BITCOIN", "BTC"],
                "ETH": ["ETHEREUM", "ETH"],
                "SOL": ["SOLANA", "SOL"],
                "XRP": ["XRP"],
                "DOGE": ["DOGE", "DOGECOIN"],
                "BNB": ["BNB", "BINANCE"],
                "HYPE": ["HYPERLIQUID", "HYPE"],
                "HL": ["HYPERLIQUID", "HL"]
            }
            search_symbols = symbol_aliases.get(base_symbol, [base_symbol])
            
            # Map common window names and patterns
            window_names = {
                "5m": ["5 MINUTE", "5M", "5-MINUTE"],
                "15m": ["15 MINUTE", "15M", "15-MINUTE"],
                "1h": ["1 HOUR", "1H", "1-HOUR", "HOURLY"],
                "4h": ["4 HOUR", "4H", "4-HOUR"],
                "1d": ["1 DAY", "1D", "ON APRIL", "DAILY", "1-DAY", "TODAY"], 
                "1w": ["1 WEEK", "WEEKLY", "1-WEEK"],
                "1m": ["1 MONTH", "MONTHLY", "1-MONTH"]
            }
            search_terms = window_names.get(window_clean, [window_clean.upper()])
            
            # Patterns that represent benchmark/trading trhy
            pattern_priority = [
                "UP OR DOWN", "PRICE", "ABOVE", "BELOW", "HIT", 
                "RANGE", "WILL", "MOVED", "CHANGE"
            ] 
            
            found_markets = []
            for m in self._markets:
                q = (m.get("question", "") + " " + m.get("slug", "")).upper()
                # Check if ANY of the symbol aliases match
                symbol_match = any(sym in q for sym in search_symbols)
                # Check if ANY of the window terms match
                window_match = any(term in q for term in search_terms)
                
                if symbol_match and window_match:
                    # Score the match by patterns
                    score = 0
                    for i, pattern in enumerate(pattern_priority):
                        if pattern in q:
                            score = len(pattern_priority) - i
                            break
                    found_markets.append((score, m))
            
            # Sort by score (desc) and then by volume (desc)
            if found_markets:
                found_markets.sort(key=lambda x: (x[0], float(x[1].get('volume24hr') or 0)), reverse=True)
                market = found_markets[0][1]
            
            if market:
                # Automatically update maps for next time
                self._condition_id_by_asset[asset] = market.get("conditionId")
                token_ids_raw = market.get("clobTokenIds", "[]")
                try:
                    token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
                    if token_ids:
                        self._token_id_by_asset[asset] = str(token_ids[0])
                except: pass

        if not market:
            raise ValueError(f"Market not found for {asset}:{window} (no active market for this symbol/timeframe)")

        last_price = market.get("lastTradePrice")
        if last_price is None:
            prices_raw = market.get("outcomePrices", "[]")
            try:
                prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                if prices and len(prices) >= 2:
                    last_price = float(prices[0])
                else:
                    last_price = 0.5
            except Exception:
                last_price = 0.5

        return round(float(last_price), 4)

    async def get_account(self) -> Dict[str, Any]:
        if self.dry_run:
            return {"balance": "10000.0", "positions": []}
        # TODO: GET /portfolio from Data API
        return {}

    async def submit_order(
        self,
        asset: str,
        side: str,           # "buy" or "sell"
        size: Decimal,
        price: Decimal,
        order_type: str = "limit",
        time_in_force: str = "GTC",
    ) -> Dict[str, Any]:
        """
        Submit an AMM swap order via on-chain router.
        For dry_run, returns simulated fill.
        For live: builds swap transaction and sends via Web3.
        """
        if self.dry_run:
            # Simulate AMM slippage using constant product formula approximation
            # pool_liquidity: estimated AMM pool size (in USD)
            pool_liquidity = Decimal('50000')  # $50k default pool
            if asset in ['BTC', 'ETH']:
                pool_liquidity = Decimal('100000')  # $100k for major assets

            # Calculate slippage: larger trades relative to pool = more slippage
            trade_usd = size
            slippage_rate = trade_usd / pool_liquidity

            # Cap slippage at 2% (200 bps) for simulation realism
            slippage_rate = min(slippage_rate, Decimal('0.02'))

            # Apply slippage to execution price
            if side == 'buy':
                executed_price = price * (Decimal('1') + slippage_rate)
            else:  # sell
                executed_price = price * (Decimal('1') - slippage_rate)

            slippage_bps = slippage_rate * Decimal('10000')

            order_id = f"dry-amm-{asset}-{side}-{int(size)}-{price}"
            return {
                "order_id": order_id,
                "status": "filled",
                "filled_qty": str(size),
                "avg_price": str(executed_price),
                "side": side,
                "slippage_bps": float(slippage_bps),
                "requested_price": str(price),
            }

        # Live on-chain swap via AMM router
        if not self.w3 or not self.router_contract:
            raise RuntimeError("Web3 or router contract not initialized — call connect() first")

        token_id = self._token_id_by_asset.get(asset)
        if not token_id:
            raise ValueError(f"No token ID mapped for asset {asset}")

        # Build swap transaction
        # Router method: swapExactTokensForTokens / swapTokensForExactTokens
        # We'll swap collateral (USDC/USDT) for YES/NO tokens
        # NOTE: Contract ABI and token addresses TBD — needs router + token ABI
        raise NotImplementedError("Live on-chain AMM swap not implemented yet")

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def get_open_orders(self, asset: Optional[str] = None) -> List[Dict[str, Any]]:
        return []

    async def get_positions(self) -> List[Dict[str, Any]]:
        return []

    # Additional AMM-specific helpers
    def get_token_id(self, asset: str) -> str:
        return self._token_id_by_asset.get(asset, "")

    def get_condition_id(self, asset: str) -> str:
        return self._condition_id_by_asset.get(asset, "")
    # ——— Context manager support ———
    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.disconnect()

    # ——— Interface compliance ———
    async def buy(
        self,
        market_id: str,
        outcome_id: int = 0,
        price: Optional[float] = None,
        amount: int = 1,
        order_type: str = "limit"
    ) -> Optional[Dict]:
        """
        Place a buy order. In AMM, this is a swap of collateral for YES token.
        outcome_id: 0=YES, 1=NO (binary market)
        """
        size_usd = price * amount if price else 100.0
        return await self.submit_order(
            asset=market_id.split('_')[0],  # BTC from BTC_5M
            side="buy",
            size=Decimal(str(size_usd)),
            price=Decimal(str(price)) if price else None,
            order_type=order_type
        )

    async def sell(
        self,
        market_id: str,
        outcome_id: int = 0,
        price: Optional[float] = None,
        amount: int = 1
    ) -> Optional[Dict]:
        """Place a sell order — swap YES token for collateral."""
        size_usd = price * amount if price else 100.0
        return await self.submit_order(
            asset=market_id.split('_')[0],
            side="sell",
            size=Decimal(str(size_usd)),
            price=Decimal(str(price)) if price else None
        )

    async def get_balance(self) -> float:
        """Return available cash balance."""
        acct = await self.get_account()
        try:
            return float(acct.get("balance", "0.0"))
        except (TypeError, ValueError):
            return 0.0

    async def get_volume_24h(self, market_id: str) -> float:
        """Fetch 24h volume for the market from Gamma."""
        if self.dry_run:
            return 0.0
        # Find market in loaded list
        for m in self._markets:
            if m.get("id") == market_id or m.get("market_id") == market_id:
                vol = m.get("volume24hr") or m.get("volumeNum") or 0.0
                return float(vol)
        return 0.0

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.disconnect()

    async def buy(
        self,
        market_id: str,
        outcome_id: int = 0,
        price: Optional[float] = None,
        amount: int = 1,
        order_type: str = "limit"
    ) -> Optional[Dict]:
        size_usd = price * amount if price else 100.0
        return await self.submit_order(
            asset=market_id.split('_')[0],
            side="buy",
            size=Decimal(str(size_usd)),
            price=Decimal(str(price)) if price else None,
            order_type=order_type
        )

    async def sell(
        self,
        market_id: str,
        outcome_id: int = 0,
        price: Optional[float] = None,
        amount: int = 1
    ) -> Optional[Dict]:
        size_usd = price * amount if price else 100.0
        return await self.submit_order(
            asset=market_id.split('_')[0],
            side="sell",
            size=Decimal(str(size_usd)),
            price=Decimal(str(price)) if price else None
        )

    async def get_balance(self) -> float:
        acct = await self.get_account()
        try:
            return float(acct.get("balance", "0.0"))
        except (TypeError, ValueError):
            return 0.0

    async def get_volume_24h(self, market_id: str) -> float:
        if self.dry_run:
            return 0.0
        for m in self._markets:
            if m.get("id") == market_id or m.get("market_id") == market_id:
                vol = m.get("volume24hr") or m.get("volumeNum") or 0.0
                return float(vol)
        return 0.0


    async def buy(self, market_id: str, outcome_id: int, price: float, amount: int, order_type: str = "limit") -> Dict[str, Any]:
        """
        Stub buy for AMM — used in dry-run / paper-trading.
        Returns a fake order dict (enough for tracking).
        """
        self.logger.info("AMM buy stub", asset=self._asset_by_condition_id.get('?'), price=price, amount=amount)
        return {
            "order_id": f"amm-buy-{market_id[:8]}-{int(time.time())}",
            "status": "filled",
            "filled_amount": amount,
            "average_price": price
        }

    async def sell(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Stub sell for AMM — flexible signature for dry-run / paper-trading.
        Accepts either (market_id=..., outcome_id=..., price=..., amount=..., order_type=...)
        or (asset=..., window=..., price=..., amount=..., outcome_id=..., market_id=...).
        """
        self.logger.info("AMM sell stub", args=args, kwargs=kwargs)
        # Determine identifier for order_id
        market_id = kwargs.get('market_id')
        if not market_id:
            asset = kwargs.get('asset', 'X')
            window = kwargs.get('window', '')
            market_id = f"{asset}:{window}"
        return {
            "order_id": f"amm-sell-{market_id[:8]}-{int(time.time())}",
            "status": "filled",
            "filled_amount": kwargs.get('amount', 0),
            "average_price": kwargs.get('price', 0.0)
        }
