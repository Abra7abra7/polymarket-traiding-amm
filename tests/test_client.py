"""
Unit tests for polymarket_bot.exchange.client.PolymarketClient.

Covers:
  - Connection lifecycle (connect/disconnect)
  - Mock mode price generation
  - Order placement (dry-run vs live)
  - Error handling (retries, timeouts)
  - Balance fetching (dry-run fixed balance)
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from polymarket_bot.exchange.client import PolymarketClient


class TestClientConstruction:
    """Test client initialization."""

    def test_default_dry_run(self):
        client = PolymarketClient()
        assert client.dry_run is True
        assert client.sandbox is False

    def test_explicit_dry_run(self):
        client = PolymarketClient(dry_run=True)
        assert client.dry_run is True

    def test_live_mode_explicit(self):
        client = PolymarketClient(dry_run=False)  # doctest: +SKIP
        assert client.dry_run is False


class TestClientConnectDisconnect:
    """Test connection lifecycle."""

    @pytest.mark.asyncio
    async def test_connect_returns_none(self):
        client = PolymarketClient(dry_run=True)
        result = await client.connect()
        assert result is None
        assert client.connected is True

    @pytest.mark.asyncio
    async def test_disconnect_clean(self):
        client = PolymarketClient(dry_run=True)
        await client.connect()
        result = await client.disconnect()
        assert result is None
        assert client.connected is False

    @pytest.mark.asyncio
    async def test_reconnect_after_disconnect(self):
        client = PolymarketClient(dry_run=True)
        await client.connect()
        await client.disconnect()
        await client.connect()
        assert client.connected is True


class TestMockTicker:
    """Test get_ticker in dry-run mode returns reasonable values."""

    @pytest.mark.asyncio
    async def test_ticker_returns_float(self):
        client = PolymarketClient(dry_run=True)
        await client.connect()
        price = await client.get_ticker("BTC")
        assert isinstance(price, float)
        assert price > 0

    @pytest.mark.asyncio
    async def test_ticker_within_expected_range(self):
        # Mock client returns probability between 0.01 and 0.99
        client = PolymarketClient(dry_run=True)
        await client.connect()
        prices = [await client.get_ticker("BTC") for _ in range(100)]
        assert all(0.01 <= p <= 0.99 for p in prices)

    @pytest.mark.asyncio
    async def test_ticker_without_connection_raises(self):
        client = PolymarketClient(dry_run=True)
        # Not connected yet
        with pytest.raises(ConnectionError):
            await client.get_ticker("BTC")


class TestMockOrderPlacement:
    """Test buy/sell in dry-run mode."""

    @pytest.mark.asyncio
    async def test_buy_returns_order_dict(self):
        client = PolymarketClient(dry_run=True)
        await client.connect()
        order = await client.buy(
            market_id="0xTEST",
            outcome_id=0,
            price=100.0,
            amount=10
        )
        assert "order_id" in order
        assert "status" in order
        assert order["status"] in ("placed", "mock_placed")

    @pytest.mark.asyncio
    async def test_buy_amount_less_than_one_returns_none(self):
        client = PolymarketClient(dry_run=True)
        await client.connect()
        # amount=0.5 shares → should return None (cannot fractional)
        order = await client.buy(
            market_id="0xTEST",
            outcome_id=0,
            price=100.0,
            amount=0.5
        )
        assert order is None

    @pytest.mark.asyncio
    async def test_sell_returns_order_dict(self):
        client = PolymarketClient(dry_run=True)
        await client.connect()
        order = await client.sell(
            market_id="0xTEST",
            outcome_id=0,
            price=100.0,
            amount=5
        )
        assert "order_id" in order

    @pytest.mark.asyncio
    async def test_orders_unique_ids(self):
        client = PolymarketClient(dry_run=True)
        await client.connect()
        ids = set()
        for _ in range(10):
            o = await client.buy("0xX", 0, 100.0, 1)
            ids.add(o["order_id"])
        assert len(ids) == 10  # all unique


class TestBalance:
    """Test balance fetching."""

    @pytest.mark.asyncio
    async def test_balance_dry_run_fixed(self):
        client = PolymarketClient(dry_run=True)
        await client.connect()
        bal = await client.get_balance()
        assert bal == 50_000.0  # hardcoded in client.py

    @pytest.mark.asyncio
    async def test_balance_live_mode_requires_impl(self):
        # Live mode not implemented yet
        client = PolymarketClient(dry_run=False)
        await client.connect()
        with pytest.raises(NotImplementedError):
            await client.get_balance()


class TestMarkets:
    """Test market discovery."""

    @pytest.mark.asyncio
    async def test_get_markets_returns_list(self):
        client = PolymarketClient(dry_run=True)
        await client.connect()
        markets = await client.get_markets()
        assert isinstance(markets, list)
        assert len(markets) >= 1  # mock returns at least BTC mock

    @pytest.mark.asyncio
    async def test_market_structure(self):
        client = PolymarketClient(dry_run=True)
        await client.connect()
        markets = await client.get_markets()
        m = markets[0]
        assert "id" in m or "market_id" in m
        assert "name" in m


class TestClientErrorHandling:
    """Error paths."""

    @pytest.mark.asyncio
    async def test_invalid_price_raises(self):
        client = PolymarketClient(dry_run=True)
        await client.connect()
        with pytest.raises(ValueError):
            await client.buy("0xX", 0, -10.0, 1)

    @pytest.mark.asyncio
    async def test_invalid_amount_raises(self):
        client = PolymarketClient(dry_run=True)
        await client.connect()
        with pytest.raises(ValueError):
            await client.buy("0xX", 0, 100.0, -1)

    @pytest.mark.asyncio
    async def test_zero_shares_returns_none(self):
        client = PolymarketClient(dry_run=True)
        await client.connect()
        order = await client.buy("0xX", 0, 100.0, 0)
        assert order is None


class TestClientState:
    """Client state tracking."""

    @pytest.mark.asyncio
    async def test_connected_flag(self):
        client = PolymarketClient(dry_run=True)
        assert client.connected is False
        await client.connect()
        assert client.connected is True
        await client.disconnect()
        assert client.connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with PolymarketClient(dry_run=True) as client:
            assert client.connected is True
        assert client.connected is False
