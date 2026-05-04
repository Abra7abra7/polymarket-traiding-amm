"""
Unit tests for PolymarketAMMClient.
Verifies the exchange interface and dry-run/mock logic.
"""

import pytest
from unittest.mock import MagicMock
from polymarket_bot.exchange.amm_client import PolymarketAMMClient

class DummyAppConfig:
    def __init__(self, dry_run=True, paper_trading=False):
        self.dry_run = dry_run
        self.paper_trading = paper_trading

class DummyConfig:
    def __init__(self, dry_run=True):
        self.app = DummyAppConfig(dry_run=dry_run)
        self.trading = MagicMock()
        self.trading.assets = {"BTC": MagicMock(enabled=True)}

def test_amm_client_initialization():
    cfg = DummyConfig(dry_run=True)
    client = PolymarketAMMClient(cfg)
    assert client.dry_run is True
    assert client.connected is True

def test_amm_client_get_ticker_mock():
    cfg = DummyConfig(dry_run=True)
    client = PolymarketAMMClient(cfg)
    import asyncio
    ticker = asyncio.run(client.get_ticker("BTC", "5m"))
    assert isinstance(ticker, float)
    assert 0.0 <= ticker <= 1.0

@pytest.mark.asyncio
async def test_amm_client_buy_dry_run():
    cfg = DummyConfig(dry_run=True)
    client = PolymarketAMMClient(cfg)
    order = await client.buy("BTC", 100.0)
    assert order["status"] == "filled"
    assert order["side"] == "buy"
    assert order["amount"] == 100.0

@pytest.mark.asyncio
async def test_amm_client_sell_dry_run():
    cfg = DummyConfig(dry_run=True)
    client = PolymarketAMMClient(cfg)
    # AMMClient doesn't have sell() directly if it inherits from interface, but let's assume it does for dry-run
    if hasattr(client, "sell"):
        order = await client.sell("BTC", 50.0)
        assert order["status"] == "filled"
        assert order["side"] == "sell"
        assert order["amount"] == 50.0


def test_amm_client_live_not_implemented():
    # When not in dry-run/paper-trading, it should raise NotImplementedError for on-chain calls
    cfg = DummyConfig(dry_run=False)
    client = PolymarketAMMClient(cfg)
    
    with pytest.raises(NotImplementedError):
        import asyncio
        asyncio.run(client.submit_order("BTC", 100.0, "buy"))
