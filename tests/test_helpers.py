import pytest
from polymarket_bot.utils.helpers import resolve_market_id, get_window_duration_days, get_market_volatility

def test_resolve_market_id_crypto():
    class MockAsset:
        symbol = "BTC"
    
    asset = MockAsset()
    assert resolve_market_id(asset, "5m") == "BTC_5M"
    assert resolve_market_id(asset, "1h") == "BTC_1H"

def test_resolve_market_id_weather():
    class MockAsset:
        symbol = "LON_RAIN"
        market_id = "LON_RAIN_BASE"
    
    asset = MockAsset()
    assert resolve_market_id(asset, "1h") == "LON_RAIN_BASE_1H"

def test_get_window_duration_days():
    assert get_window_duration_days("5m") == 5 / (60 * 24)
    assert get_window_duration_days("1d") == 1.0
    assert get_window_duration_days("unknown") == 1.0

def test_get_market_volatility():
    class MockAsset:
        volatility = 0.05
    
    assert get_market_volatility(MockAsset()) == 0.05
    assert get_market_volatility(None) == 0.03
