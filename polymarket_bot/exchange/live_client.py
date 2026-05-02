"""
Polymarket Live REST API Client — production trading.

Implements real order execution via Polymarket's authenticated endpoints.
Uses aiohttp for async HTTP calls with API key authentication.

Endpoints (as of 2026-04):
  GET    /markets                 — list all markets
  GET    /markets/{marketId}      — market details + current price
  GET    /portfolio               — account balances & positions
  POST   /orders                  — place order (buy/sell)
  GET    /orders                  — list open orders
  DELETE /orders/{orderId}        — cancel order

Authentication: Bearer token (API Key) in Authorization header.
Base URL: https://api.polymarket.com
"""
import asyncio
import os
import json
import time
import hmac
import hashlib
import base64
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import aiohttp
import structlog  # type: ignore

from polymarket_bot.exchange.interface import BaseExchangeClient
from py_clob_client.signer import Signer
from py_clob_client.headers.headers import create_level_1_headers, create_level_2_headers
from py_clob_client.clob_types import ApiCreds, RequestArgs

logger = structlog.get_logger()


"""
Polymarket live client – multi-API routing (Gamma, Data, CLOB) with Bearer auth.
"""

import os
import aiohttp
import json
import logging
from typing import Dict, Any, Optional, List
from polymarket_bot.exchange.interface import BaseExchangeClient

logger = logging.getLogger('ExchangeClient')


class PolymarketLiveClient(BaseExchangeClient):
    """
    Unified client routing:
      Gamma API  → markets, events
      Data API  → portfolio, positions
      CLOB API  → orders, orderbook
    Authentication: Bearer token (POLYMARKET_BEARER_TOKEN).
    """

    BASE_GAMMA = "https://gamma-api.polymarket.com"
    BASE_DATA  = "https://data-api.polymarket.com"
    BASE_CLOB  = "https://clob.polymarket.com"

    ENDPOINTS = {
        # Gamma
        "markets": "/markets",
        "market_detail": "/markets/{market_id}",
        # Data
        "portfolio": "/portfolio",
        # CLOB
        "orders": "/orders",
        "place_order": "/orders",
        "cancel_order": "/orders/{order_id}",
    }

    def __init__(
        self,
        dry_run: bool = False,
        sandbox: bool = False,
        gamma_base_url: str = None,
        data_base_url: str = None,
        clob_base_url: str = None,
        clob_jwt: str = None,
        api_key: str = None,
        api_secret: str = None,
        api_passphrase: str = None,
        private_key: str = None,
        wallet_address: str = None,
        bearer_token: str = None,  # deprecated – use clob_jwt
    ):
        super().__init__()
        self.dry_run = dry_run
        self.sandbox = sandbox
        self.gamma_base = gamma_base_url or os.environ.get("POLYMARKET_GAMMA_URL", self.BASE_GAMMA)
        self.data_base  = data_base_url  or os.environ.get("POLYMARKET_DATA_URL",  self.BASE_DATA)
        self.clob_base  = clob_base_url  or os.environ.get("POLYMARKET_CLOB_URL",  self.BASE_CLOB)
        # CLOB JWT for Gamma/Data API authentication
        self.clob_jwt = clob_jwt or bearer_token or os.environ.get("POLYMARKET_CLOB_JWT")
        # CLOB Level 2 credentials for order submission
        self.api_key = api_key or os.environ.get("POLYMARKET_API_KEY")
        self.api_secret = api_secret or os.environ.get("POLYMARKET_API_SECRET")
        self.api_passphrase = api_passphrase or os.environ.get("POLYMARKET_API_PASSPHRASE")
        self.private_key = private_key or os.environ.get("POLYMARKET_PRIVATE_KEY")
        self._api_creds = ApiCreds(self.api_key, self.api_secret, self.api_passphrase)
        self.wallet_address = wallet_address or os.environ.get("POLYMARKET_WALLET_ADDRESS")

        # Level 1 signer for authenticated Gamma API calls (uses private key)
        self._signer: Optional[Signer] = None
        if self.private_key:
            self._signer = Signer(self.private_key, chain_id=137)

        self.connected = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._markets: List[Dict] = []
        self._token_id_by_asset: Dict[str, str] = {}
        self._condition_id_by_asset: Dict[str, str] = {}

        # L2 credentials initialized above as self._api_creds

        if not self.dry_run:
            if not self.clob_jwt:
                logger.warning("POLYMARKET_CLOB_JWT not set — authenticated endpoints will fail")
            if not self.wallet_address:
                raise ValueError("Missing POLYMARKET_WALLET_ADDRESS")

        logger.info(
            f"PolymarketLiveClient init: dry_run={self.dry_run}, "
            f"wallet={self.wallet_address[:10] + '...' if self.wallet_address else None}"
        )

    def _base_for(self, path: str) -> str:
        """Route API paths to correct base URLs."""
        if path.startswith('/markets'):
            return self.clob_base
        if path.startswith('/positions') or path.startswith('/value') or path.startswith('/users'):
            return self.data_base
        return self.clob_base

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if not self.dry_run and self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        return headers

    async def connect(self) -> None:
        if self.dry_run:
            self.connected = True
            return
        self._session = aiohttp.ClientSession(trust_env=True)
        try:
            # Health check via public markets endpoint; also load market data
            resp = await self._public_get("/markets")
            self._markets = resp.get("data", resp) if isinstance(resp, dict) else resp
            self._build_market_maps()
            self._load_asset_maps_from_config()
            logger.info(f"Connected to Polymarket — loaded {len(self._markets)} markets")
            self.connected = True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            raise
    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
        self.connected = False

    async def _gamma_get(self, path: str, params: Dict = None) -> Any:
        """Authenticated GET to Gamma/Data API using CLOB JWT."""
        if self.dry_run:
            raise NotImplementedError("Live client in dry-run mode should not be used")
        base = self._base_for(path)
        url = f"{base}{path}"
        headers = {}
        if self._signer:
            headers = create_level_1_headers(self._signer)
        elif self.clob_jwt:
            # Fallback to legacy JWT if signer not available
            headers = {"Authorization": f"Bearer {self.clob_jwt}"}
        """Authenticated GET to Gamma/Data API using CLOB JWT."""
        if self.dry_run:
            raise NotImplementedError("Live client in dry-run mode should not be used")
        base = self._base_for(path)
        url = f"{base}{path}"
        headers = {"Authorization": f"Bearer {self.clob_jwt}"} if self.clob_jwt else {}
        async with self._session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"GET {path} failed {resp.status}: {text}")
            return await resp.json()

    async def _public_get(self, path: str, params: Dict = None) -> Any:
        """Public GET without authentication."""
        if self.dry_run:
            raise NotImplementedError("Live client in dry-run mode should not be used")
        base = self._base_for(path)
        url = f"{base}{path}"
        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"GET {path} failed {resp.status}: {text}")
            return await resp.json()

    async def _post(self, path: str, data: Dict) -> Any:
        if self.dry_run:
            raise NotImplementedError("Live client in dry-run mode should not be used")

        base = self._base_for(path)
        url = f"{base}{path}"
        # Use L2 auth for order submission
        if path.startswith("/orders"):
            if not self._signer:
                raise ValueError("Private key required for order submission (L2 auth)")
            request_args = RequestArgs(
                method="POST",
                request_path=path,
                body=data
            )
            headers = create_level_2_headers(self._signer, self._api_creds, request_args)
        else:
            headers = self._headers()
        async with self._session.post(url, headers=headers, json=data) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                raise RuntimeError(f"POST {path} failed {resp.status}: {text}")
            return await resp.json()

    # ---- Public API ----

    def _build_market_maps(self) -> None:
        
        
            # Find YES token_id
                # outcome may be under 'outcome' or 'name'

            # Detect time window from question text

                # No window detected – map ticker alone
                # For crypto tickers, also map with all common windows


        # DO NOT clear — preserve tokens loaded from config.yaml (explicit token_ids)
        # Tokens from config are authoritative; market data may not include them (orderbook disabled)
        # Map from available markets
        for m in self._markets:
            condition_id = m.get("condition_id")
            ticker = m.get("ticker", "").upper()
            if not condition_id:
                continue
            # Try to find YES/TRUE token
            token_id = None
            for t in m.get("tokens", []):
                name = (t.get("outcome") or t.get("name") or "").lower()
                if name in ("yes", "true", "1"):
                    token_id = t.get("token_id")
                    break
            if not token_id:
                continue
            # Map base ticker to token/condition
            if ticker and ticker not in ("N/A", "N\A"):
                self._token_id_by_asset[ticker] = token_id
                self._condition_id_by_asset[ticker] = condition_id
            # Also map common variants:
            # For weather, condition_id often contains city+metric; ticker may be like LON_RAIN
            # We do not derive further without extra metadata; rely on config for exact asset keys
        logger.info(f"Built market maps: {len(self._token_id_by_asset)} assets mapped")
    async def get_markets(self, params: Dict = None) -> List[Dict[str, Any]]:

        data = await self._public_get("/markets")
        markets = data.get("data", [])
        self._markets = markets
        self._load_asset_maps_from_config()
        self._build_market_maps()
        self._load_asset_maps_from_config()
        return markets


    def _load_asset_maps_from_config(self) -> None:
        """Load condition_ids and token_ids for enabled assets from config."""
        cfg_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'config.yaml')
        if not os.path.exists(cfg_path):
            return
        import yaml
        with open(cfg_path, 'r') as f:
            cfg = yaml.safe_load(f)
        assets_cfg = cfg.get('trading', {}).get('assets', {})
        for asset_key, asset_cfg in assets_cfg.items():
            if not asset_cfg.get('enabled', True):
                continue
            condition_id = asset_cfg.get('condition_id')
            if condition_id and not condition_id.startswith('REPLACE_'):
                self._condition_id_by_asset[asset_key] = condition_id
            token_id = asset_cfg.get('token_id')
            if token_id:
                self._token_id_by_asset[asset_key] = token_id
                windows = asset_cfg.get('windows', [])
                for w in windows:
                    self._token_id_by_asset[f"{asset_key}_{w}"] = token_id
                    if w.endswith('m'):
                        self._token_id_by_asset[f"{asset_key}_{w[:-1]}M"] = token_id
                    elif w.endswith('h'):
                        self._token_id_by_asset[f"{asset_key}_{w[:-1]}H"] = token_id
                logger.info(f"Loaded token for {asset_key} (windows {windows}): {token_id[:20]}...")

    async def _ensure_token_for_asset(self, asset_key: str) -> None:
        """Lazy-load token_id for asset if not already mapped."""
        if asset_key in self._token_id_by_asset:
            return
        condition_id = self._condition_id_by_asset.get(asset_key)
        if not condition_id or condition_id.startswith('REPLACE_'):
            return
        try:
            # Use Gamma API with condition_id filter – returns list of markets
            markets = await self._gamma_get("/markets", params={"condition_id": condition_id, "active": "true", "limit": 5})
            logger.debug(f"Gamma response for {asset_key}: type={type(markets).__name__}, len={len(markets) if isinstance(markets, list) else 'N/A'}")
            if isinstance(markets, dict):
                markets = [markets]
            token_id = None
            if markets:
                logger.debug(f"Market keys: {list(markets[0].keys())[:10]}")
                clob_tokens = markets[0].get("clobTokenIds", [])
                logger.debug(f"clobTokenIds: {clob_tokens}")
                if clob_tokens:
                    token_id = clob_tokens[0]
                else:
                    tokens = markets[0].get("tokens", [])
                    for t in tokens:
                        name = (t.get("outcome") or t.get("name") or "").lower()
                        if name in ("yes", "true", "1"):
                            token_id = t.get("token_id")
                            break
                    if not token_id and tokens:
                        token_id = tokens[0].get("token_id")
            if token_id:
                self._token_id_by_asset[asset_key] = token_id
                logger.info(f"Loaded token for {asset_key}: {token_id[:20]}...")
            else:
                logger.warning(f"No token found for {asset_key} (condition_id: {condition_id[:20]}...)")
        except Exception as e:
            logger.error(f"Error fetching token for {asset_key}: {e}")

    async def get_market(self, market_id: str) -> Dict[str, Any]:
        """Fetch market details by condition_id using Gamma API query."""
        markets = await self._gamma_get("/markets", params={"condition_id": market_id, "limit": 1})
        if isinstance(markets, list) and markets:
            return markets[0]
        elif isinstance(markets, dict):
            return markets
        return {}

    async def get_positions(self) -> List[Dict[str, Any]]:
        # Data API returns either {"positions": [...]} or a bare list


        if self.dry_run:
            return []
        wallet = self.wallet_address.lower()
        positions = await self._public_get(f"/positions?user={wallet}")
        return [p for p in positions if p.get("size", 0) > 0]
    async def get_balance(self) -> float:
        # Data API returns a list of {user, value}


        if self.dry_run:
            return 0.0
        wallet = self.wallet_address.lower()
        data = await self._public_get(f"/value?user={wallet}")
        total = sum(float(p.get("value", 0)) for p in data)
        return total

    async def get_volume_24h(self, market_id: str) -> float:
        """Get 24-hour trading volume for a market."""
        try:
            m = await self.get_market(market_id)
            return float(m.get("volume_24h", 0))
        except Exception:
            return 0.0

    async def get_open_orders(self) -> List[Dict[str, Any]]:
        if self.dry_run:
            return []
        data = await self._get("/orders")
        return data.get("orders", [])

    async def place_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
    ) -> Dict:
        if self.dry_run:
            return {"success": True, "dry_run": True, "order_id": "dry-123"}
        if side not in ('buy', 'sell'):
            raise ValueError(f"Invalid side: {side}")
        size = float(size)
        price = float(price)
        payload = {
            "order_type": "LIMIT",
            "token_id": token_id,
            "side": side,
            "size": str(size),
            "price": str(price),
            "neg_risk": False,
        }
        resp = await self._post("/orders", data=payload)
        data = await resp.json()
        if resp.status == 200:
            return {"success": True, "order_id": data.get("orderID") or data.get("order_id")}
        else:
            return {"success": False, "error": data, "status": resp.status}

    async def buy(self, asset: str, size: float, price: Optional[float] = None) -> Dict:
        token_id = self._token_id_by_asset.get(asset)
        if not token_id:
            await self._ensure_token_for_asset(asset)
            token_id = self._token_id_by_asset.get(asset)
            if not token_id:
                return {"success": False, "error": f"No token_id for asset {asset}"}
        return await self.place_order(token_id, "buy", size, price or 0.0)

    async def sell(self, asset: str, size: float, price: Optional[float] = None) -> Dict:
        token_id = self._token_id_by_asset.get(asset)
        if not token_id:
            await self._ensure_token_for_asset(asset)
            token_id = self._token_id_by_asset.get(asset)
            if not token_id:
                return {"success": False, "error": f"No token_id for asset {asset}"}
        return await self.place_order(token_id, "sell", size, price or 0.0)

    async def get_ticker(self, asset: str) -> float:
        """Get current mid price for an asset from orderbook."""
        book = await self.get_orderbook(asset)
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        # CLOB orderbook: bids/asks are list of dicts {'price': str, 'size': str}
        best_bid = float(bids[0]["price"]) if bids else (float(asks[0]["price"]) if asks else 0.0)
        best_ask = float(asks[0]["price"]) if asks else (float(bids[0]["price"]) if bids else 0.0)
        # Compute mid, handling zero cases
        if best_bid > 0 and best_ask > 0:
            return (best_bid + best_ask) / 2
        elif best_bid > 0:
            return best_bid
        else:
            return best_ask

    async def get_orderbook(self, asset_id: str) -> Dict[str, Any]:
        """Get orderbook for asset using token_id via public CLOB endpoint."""
        await self._ensure_token_for_asset(asset_id)
        token_id = self._token_id_by_asset.get(asset_id)
        if not token_id:
            logger.warning(f"No token_id for asset {asset_id}")
            return {"bids": [], "asks": []}
        return await self._public_get(f"/book?token_id={token_id}&depth=10")


    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.disconnect()
