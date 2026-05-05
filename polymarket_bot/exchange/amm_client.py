"""
Polymarket AMM Exchange Client
Uses Gamma API (same as CLOB) but treats markets as AMM-based liquidity pools.
For AMM, prices are derived from pool reserves and the constant-product formula.
"""
import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple
from decimal import Decimal
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
POLYMARKET_AMM_ROUTER = os.environ.get(
    "POLYMARKET_AMM_ROUTER",
    "0x0000000000000000000000000000000000000000"  # placeholder
)

class PolymarketAMMClient(BaseExchangeClient):
    """
    AMM-based exchange client for Polymarket.

    Uses the Gamma REST API to fetch market metadata and token IDs.
    Prices are computed from outcomePrices (probabilities).

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
        
        # Prioritize dry_run from config if present
        if config and hasattr(config, 'app') and hasattr(config.app, 'dry_run'):
            self.dry_run = config.app.dry_run
        else:
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
        self._market_by_condition_id: Dict[str, Dict] = {}
        self._connected = False

        # Web3 (for live on-chain swaps)
        self.w3: Optional[Web3] = None
        self.router_contract: Optional[Contract] = None

    async def connect(self) -> bool:
        """Initialize HTTP session and load market data."""
        if self.dry_run:
            self._connected = True
            return True

        self._session = aiohttp.ClientSession(
            base_url=self.gamma_base,
            timeout=aiohttp.ClientTimeout(total=10),
        )
        
        try:
            # Load all active markets (Gamma API — works without auth)
            resp = await self._public_get("/markets", params={"active": "true", "limit": 2000})
            if isinstance(resp, dict) and "data" in resp:
                self._markets = resp["data"]
            else:
                self._markets = resp if isinstance(resp, list) else []
                
            self._load_asset_maps_from_config()
            self._build_market_maps()
            self._connected = True
            return True
        except Exception as e:
            logger.error(f"Failed to connect to AMM API: {e}")
            self._connected = False
            return False

    async def refresh_markets(self) -> None:
        """Fetch latest markets from Gamma API and rebuild maps."""
        if self.dry_run or not self._session:
            return
        
        try:
            resp = await self._public_get("/markets", params={"limit": 2000})
            if isinstance(resp, dict) and "data" in resp:
                self._markets = resp["data"]
            else:
                self._markets = resp if isinstance(resp, list) else []
                
            self._build_market_maps()
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
        """Populate token/condition maps."""
        self._market_by_condition_id = {}
        for m in self._markets:
            cid = m.get("conditionId", "")
            if cid:
                self._market_by_condition_id[cid] = m

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
        """Populate token_id and condition_id maps from config."""
        if not self.config:
            return
        
        assets_cfg = getattr(self.config, 'trading', {}).assets if hasattr(self.config, 'trading') else {}
        if not assets_cfg:
            return

        for asset_key, asset_cfg in assets_cfg.items():
            token = getattr(asset_cfg, 'token_id', None)
            cond = getattr(asset_cfg, 'condition_id', None)
            if token:
                self._token_id_by_asset[asset_key] = str(token)
            if cond:
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
        return self._markets

    async def get_ticker(self, asset: str, window: str = "5m") -> float:
        """Return last traded price for asset+window."""
        if self.dry_run:
            import random
            return round(0.5 + random.uniform(-0.05, 0.05), 4)

        cid = self._condition_id_by_asset.get(asset)
        market = self._market_by_condition_id.get(cid) if cid else None
        
        if not market:
            # Fallback to search logic if not found in maps
            return 0.5

        last_price = market.get("lastTradePrice")
        if last_price is None:
            prices_raw = market.get("outcomePrices", "[]")
            try:
                prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                last_price = float(prices[0]) if prices and len(prices) >= 2 else 0.5
            except Exception:
                last_price = 0.5

        return round(float(last_price), 4)

    async def get_balance(self) -> float:
        """Return available cash balance (pUSD)."""
        if self.dry_run:
            return 10000.0
        # In V2, we should ideally use the CLOB Data API for balance
        return 0.0

    async def submit_order(
        self,
        asset: str,
        side: str,
        size: Decimal,
        price: Decimal,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Submit an AMM swap order."""
        if self.dry_run:
            executed_price = price * (Decimal('1.01') if side == 'buy' else Decimal('0.99'))
            return {
                "order_id": f"dry-amm-{int(time.time())}",
                "status": "filled",
                "filled_qty": str(size),
                "avg_price": str(executed_price),
                "side": side,
            }

        raise NotImplementedError("Live on-chain AMM swap not implemented")

    async def buy(self, market_id: str, outcome_id: int = 0, price: float = 0.5, amount: float = 1, **kwargs) -> Dict:
        """Interface compliance: buy YES/NO shares."""
        if self.dry_run:
            return {
                "order_id": f"amm-buy-{int(time.time())}",
                "status": "filled",
                "filled_amount": amount,
                "average_price": price
            }
        return await self.submit_order(market_id, "buy", Decimal(str(amount)), Decimal(str(price)))

    async def sell(self, market_id: str, outcome_id: int = 0, price: float = 0.5, amount: float = 1, **kwargs) -> Dict:
        """Interface compliance: sell YES/NO shares."""
        if self.dry_run:
            return {
                "order_id": f"amm-sell-{int(time.time())}",
                "status": "filled",
                "filled_amount": amount,
                "average_price": price
            }
        return await self.submit_order(market_id, "sell", Decimal(str(amount)), Decimal(str(price)))

    async def get_volume_24h(self, market_id: str) -> float:
        """Fetch 24h volume for the market."""
        if self.dry_run:
            return 0.0
        cid = self._condition_id_by_asset.get(market_id)
        market = self._market_by_condition_id.get(cid) if cid else None
        if market:
            return float(market.get("volume24hr") or 0.0)
        return 0.0

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.disconnect()
