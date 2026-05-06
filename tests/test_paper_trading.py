"""
Unit tests for PaperTradingEngine.
Verifies simulated execution, slippage, and P&L tracking.
"""

import pytest
import os
import json
from unittest.mock import MagicMock
from polymarket_bot.paper_trading import PaperTradingEngine

from types import SimpleNamespace

class DummyConfig:
    def __init__(self):
        self.paper_trading = SimpleNamespace(
            initial_balance=1000.0,
            spread_bps=100,
            slippage_bps=50,
            fee_bps=20,
            data_dir="./test_paper_data",
            swap_fee_bps=20,
            gas_fee_usd=0.01,
            fill_latency_ms=0,
            partial_fill_prob=0.0
        )

@pytest.fixture
def paper_engine():
    cfg = DummyConfig()
    # Create test dir
    if not os.path.exists(cfg.paper_trading.data_dir):
        os.makedirs(cfg.paper_trading.data_dir)
    
    mock_client = MagicMock()
    engine = PaperTradingEngine(mock_client, cfg)
    yield engine
    
    # Cleanup
    if os.path.exists(cfg.paper_trading.data_dir):
        import shutil
        shutil.rmtree(cfg.paper_trading.data_dir)

@pytest.mark.asyncio
async def test_paper_engine_initialization(paper_engine):
    assert paper_engine.initial_balance == 1000.0
    assert paper_engine.positions == {}
    assert paper_engine.trade_log == []

@pytest.mark.asyncio
async def test_paper_buy_execution(paper_engine):
    # Mock a ticker
    paper_engine.wrapped.get_ticker = MagicMock(return_value=0.5)
    
    # Buy 100 shares of BTC_5M at price 0.5
    # Signature: buy(market_id, outcome_id, price, amount)
    order = await paper_engine.buy("BTC_5M", 0, 0.5, 100)
    
    assert order is not None
    assert order["status"] == "filled"
    assert order["side"] == "buy"
    assert order["price"] > 0.5
    assert paper_engine.current_balance < 950.0 # 1000 - (0.5 * 100) - fees
    assert "BTC_5M_0" in paper_engine.positions

@pytest.mark.asyncio
async def test_paper_sell_execution(paper_engine):
    paper_engine.wrapped.get_ticker = MagicMock(return_value=0.5)
    # First buy
    await paper_engine.buy("BTC_5M", 0, 0.5, 100)
    initial_balance = paper_engine.current_balance
    
    # Then sell
    order = await paper_engine.sell("BTC_5M", 0, 0.5, 100)
    
    assert order is not None
    assert order["status"] == "filled"
    assert paper_engine.current_balance > initial_balance
    assert "BTC_5M_0" not in paper_engine.positions

@pytest.mark.asyncio
async def test_insufficient_balance(paper_engine):
    paper_engine.wrapped.get_ticker = MagicMock(return_value=0.5)
    # Try to buy 3000 shares at 0.5 ($1500) with $1000 balance
    # buy(market_id, outcome_id, price, amount)
    order = await paper_engine.buy("BTC_5M", 0, 0.5, 3000)
    assert order is None

@pytest.mark.asyncio
async def test_pnl_tracking(paper_engine):
    # Buy 100 shares at 0.5
    paper_engine.wrapped.get_ticker = MagicMock(return_value=0.5)
    await paper_engine.buy("BTC_5M", 0, 0.5, 100)
    
    # Price goes up to 0.6
    paper_engine.wrapped.get_ticker = MagicMock(return_value=0.6)
    paper_engine.update_market_prices({"BTC": 0.6})
    
    pos = paper_engine.positions["BTC_5M_0"]
    assert pos.current_pnl > 0


