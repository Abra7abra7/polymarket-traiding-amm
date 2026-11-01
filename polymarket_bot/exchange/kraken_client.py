"""
Kraken public market-data adapter (read-only, paper trading).

Fetches real OHLC + ticker data from the public Kraken REST API
(https://api.kraken.com/0/public) — no API keys, no secrets, no
account access. Order placement is intentionally NOT implemented:
this adapter only feeds real market data to the paper-trading engine
(PaperTradingEngine) in dry_run mode.

Pairs are mapped from the strategy asset names (BTC, ETH, ...) to
Kraken pair codes (XBTUSD, ETHUSD, ...).

Docs: https://docs.kraken.com/api/docs/rest-api/get-ohlc-data/
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

import aiohttp
import structlog  # type: ignore

from polymarket_bot.exchange.interface import BaseExchangeClient

logger = structlog.get_logger()

KRAKEN_PUBLIC_BASE = "https://api.kraken.com/0/public"

# Strategy asset name -> Kraken pair code
ASSET_TO_PAIR = {
    "BTC": "XBTUSD",
    "ETH": "ETHUSD",
    "SOL": "SOLUSD",
    "XRP": "XXRPZUSD",
    "ADA": "ADAUSD",
    "DOT": "DOTUSD",
    "LINK": "LINKUSD",
}

# Kraken OHLC intervals (minutes) -> strategy window label
WINDOW_TO_INTERVAL = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


class KrakenClient(BaseExchangeClient):
    """
    Read-only Kraken public data client.

    - get_ticker(asset, window) → latest close price from Kraken OHLC
    - get_ohlc(asset, window)   → full OHLC series (for Markov matrix bins)
    - get_volume_24h(asset)     → 24h volume from Kraken Ticker
    - buy / sell                → NotImplementedError (paper trading only;
                                  order execution is handled by the
                                  PaperTradingEngine wrapper)
    """

    def __init__(
        self,
        dry_run: bool = True,
        base_url: Optional[str] = None,
        request_timeout: float = 10.0,
        rate_limit_seconds: float = 0.25,
        normalize_prices: bool = True,
        normalization_lookback: int = 100,
    ):
        self.dry_run = dry_run
        self.base_url = (base_url or KRAKEN_PUBLIC_BASE).rstrip("/")
        self.request_timeout = request_timeout
        self.rate_limit_seconds = rate_limit_seconds
        self._connected = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_request_ts = 0.0
        # Price normalisation: the decision engine (DecisionEngine.should_enter,
        # bin_price, PaperTradingEngine fills) operates in the Polymarket
        # probability domain (0, 1]. Raw Kraken prices are in USD (BTC ~ 70 000),
        # so they must be min-max scaled into [0.01, 0.99] over a rolling window
        # — the exact method used and validated by scripts/kraken_smoke_test.py.
        # Without it every evaluation fails with "price must be in (0, 1]".
        self.normalize_prices = normalize_prices
        self.normalization_lookback = max(2, int(normalization_lookback))
        self._price_windows: Dict[str, List[float]] = {}

    # ------------------------------------------------------------------ #
    # Connection lifecycle                                               #
    # ------------------------------------------------------------------ #
    async def connect(self) -> None:
        """Establish HTTP session and verify public API reachability."""
        if self._connected and self._session and not self._session.closed:
            return
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.request_timeout)
        )
        # Cheap public endpoint to validate connectivity
        await self._public_get("Time")
        self._connected = True
        logger.info("kraken_client_connected", base_url=self.base_url)

    @property
    def connected(self) -> bool:
        return self._connected and self._session is not None and not self._session.closed

    async def disconnect(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._connected = False
        logger.info("kraken_client_disconnected")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.disconnect()

    # ------------------------------------------------------------------ #
    # Low-level public API                                               #
    # ------------------------------------------------------------------ #
    async def _public_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """GET a public endpoint and unwrap the Kraken {error, result} envelope."""
        if self._session is None or self._session.closed:
            raise RuntimeError("KrakenClient not connected — call connect() first")

        # simple client-side rate limiting
        now = time.monotonic()
        wait = self.rate_limit_seconds - (now - self._last_request_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request_ts = time.monotonic()

        url = f"{self.base_url}/{path}"
        try:
            async with self._session.get(url, params=params) as resp:
                body = await resp.json(content_type=None)
                if resp.status != 200:
                    raise RuntimeError(f"Kraken HTTP {resp.status}: {body}")
                if isinstance(body, dict) and body.get("error"):
                    raise RuntimeError(f"Kraken API error: {body['error']}")
                result = body.get("result", body)
                logger.debug("kraken_public_request", path=path, params=params)
                return result
        except aiohttp.ClientError as exc:
            logger.error("kraken_request_failed", path=path, error=str(exc))
            raise

    @staticmethod
    def _to_pair(asset: str) -> str:
        pair = ASSET_TO_PAIR.get(asset.upper())
        if pair is None:
            raise ValueError(f"Unsupported asset for Kraken adapter: {asset}")
        return pair

    @staticmethod
    def _to_interval(window: str) -> int:
        interval = WINDOW_TO_INTERVAL.get(window.lower())
        if interval is None:
            raise ValueError(f"Unsupported window for Kraken OHLC: {window}")
        return interval

    # ------------------------------------------------------------------ #
    # Market data (real, public)                                         #
    # ------------------------------------------------------------------ #
    async def get_ohlc(self, asset: str, window: str, count: int = 720) -> List[Dict[str, float]]:
        """
        Fetch OHLC candles: [{time, open, high, low, close, volume}, ...].
        Used by the Markov transition matrix / tensor logic.
        """
        pair = self._to_pair(asset)
        interval = self._to_interval(window)
        result = await self._public_get("OHLC", params={"pair": pair, "interval": interval})
        candles = None
        for key, value in result.items():
            if key != "last" and isinstance(value, list):
                candles = value
                break
        if candles is None:
            raise RuntimeError(f"Kraken OHLC: no candle data for {pair}")

        out: List[Dict[str, float]] = []
        for c in candles[-count:]:
            out.append({
                "time": float(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
            })
        logger.debug("kraken_ohlc_fetched", asset=asset, window=window, n=len(out))
        return out

    async def get_ticker(self, asset: str, window: str = "5m") -> float:
        """Latest price for the asset at the requested window.

        With ``normalize_prices`` enabled (default) the raw USD close is
        min-max scaled over a rolling window of recent closes into the
        (0, 1] probability domain required by the decision engine — same
        formula as scripts/kraken_smoke_test.py::normalize().
        """
        candles = await self.get_ohlc(asset, window, count=2)
        raw = candles[-1]["close"]
        if not self.normalize_prices:
            return raw

        key = f"{asset}:{window}"
        win = self._price_windows.get(key)
        if win is None:
            # Seed the rolling window with recent history so the first
            # evaluation already has a meaningful min/max.
            hist = await self.get_ohlc(asset, window, count=self.normalization_lookback)
            win = [c["close"] for c in hist[-self.normalization_lookback:]]
        win.append(raw)
        if len(win) > self.normalization_lookback:
            win.pop(0)
        self._price_windows[key] = win

        lo, hi = min(win), max(win)
        if hi - lo < 1e-12:
            return 0.5
        return 0.01 + 0.98 * (raw - lo) / (hi - lo)

    async def get_volume_24h(self, asset: str) -> float:
        """24h traded volume (base currency) from the public Ticker endpoint."""
        pair = self._to_pair(asset)
        result = await self._public_get("Ticker", params={"pair": pair})
        for key, value in result.items():
            if isinstance(value, dict):
                return float(value.get("v", [0, 0])[-1])
        return 0.0

    async def get_markets(self) -> List[Dict[str, Any]]:
        """Supported paper-trading markets derived from ASSET_TO_PAIR."""
        return [
            {
                "id": f"kraken-{pair.lower()}",
                "symbol": asset,
                "pair": pair,
                "exchange": "kraken",
                "type": "spot_public",
            }
            for asset, pair in ASSET_TO_PAIR.items()
        ]

    # ------------------------------------------------------------------ #
    # Not implemented on purpose (paper trading only)                    #
    # ------------------------------------------------------------------ #
    async def buy(self, market_id: str, outcome_id: int = 0, price: Optional[float] = None,
                  amount: int = 1, order_type: str = "limit") -> Optional[Dict[str, Any]]:
        raise NotImplementedError(
            "KrakenClient is read-only (public data). Order execution is "
            "simulated by PaperTradingEngine in dry_run mode."
        )

    async def sell(self, market_id: str, outcome_id: int = 0, price: Optional[float] = None,
                   amount: int = 1) -> Optional[Dict[str, Any]]:
        raise NotImplementedError(
            "KrakenClient is read-only (public data). Order execution is "
            "simulated by PaperTradingEngine in dry_run mode."
        )

    async def get_balance(self) -> float:
        """Simulated paper-trading balance (no real account access)."""
        return 50000.0
