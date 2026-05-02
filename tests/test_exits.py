"""
Unit tests for check_exits method and exit logic.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from datetime import datetime, timezone
import sys

# Import the TradingBot class
from polymarket_bot import __main__ as bot_main


@pytest.mark.asyncio
async def test_check_exits_calls_sell_with_correct_arguments(tmp_config):
    """
    Verify that check_exits calls client.sell() with market_id, outcome_id,
    price, amount, order_type, asset, window.
    """
    # Create bot with dry-run config
    bot = bot_main.TradingBot(
        config_path=str(tmp_config),
        dry_run=True,
        log_level="WARNING"
    )
    # Replace client with a mock
    mock_client = AsyncMock()
    mock_client.get_ticker = AsyncMock(return_value=0.6)  # current price
    mock_client.sell = AsyncMock(return_value={"order_id": "test_order"})
    bot.client = mock_client

    # Setup a mock decision engine that returns exit=True
    mock_decision_engine = MagicMock()
    # Mock should_exit to return exit=True
    mock_decision_engine.should_exit = MagicMock(return_value={
        "exit": True,
        "reason": "test",
        "fair_value": 0.7,
        "edge": 0.1
    })
    bot.decision_engine = mock_decision_engine

    # Create a fake open position (simulating BTC_5M)
    import copy
    bot.positions = {
        "order-123": {
            "asset": "BTC",
            "window": "5m",
            "entry_price": 0.5,
            "shares": 100,
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "p_hat": 0.6,  # stored p_hat
        }
    }
    # Ensure config.trading.assets.BTC exists (should from tmp_config)
    # We'll also need asset_cfg.symbol = "BTC"
    # The fixture tmp_config already defines BTC asset with symbol "BTC"
    # We'll also need market_id resolution (_resolve_market_id).
    # Since BTC is crypto, it will be "BTC_5M"

    # Run check_exits
    await bot.check_exits()

    # Verify that sell was called once
    assert mock_client.sell.called
    # Get call arguments
    call_args = mock_client.sell.call_args
    # Verify market_id matches expected format (BTC_5M)
    assert call_args.kwargs["market_id"] == "BTC_5M"
    assert call_args.kwargs["outcome_id"] == 0
    assert call_args.kwargs["price"] == 0.6  # mocked current_price
    assert call_args.kwargs["amount"] == 100  # shares from position
    assert call_args.kwargs["order_type"] == "limit"
    # Additional optional arguments asset and window
    assert call_args.kwargs["asset"] == "BTC"
    assert call_args.kwargs["window"] == "5m"

    # Verify that position was closed (removed from bot.positions)
    # In check_exits, closed positions are added to to_close list and later popped.
    # Since we mocked sell, the position should still be removed.
    # However, the method uses to_close list and pops after iterating.
    # Let's check that positions dict is empty.
    # Actually, the method iterates over list(self.positions.items()) and modifies later.
    # We'll just assert that the position is gone.
    assert len(bot.positions) == 0

    # Verify get_ticker was called with correct market_id
    mock_client.get_ticker.assert_called_with("BTC_5M")

    # Verify decision_engine.should_exit was called with appropriate args
    mock_decision_engine.should_exit.assert_called_once()
    exit_call = mock_decision_engine.should_exit.call_args
    assert exit_call.kwargs["entry_price"] == 0.5
    assert exit_call.kwargs["entry_shares"] == 100
    assert exit_call.kwargs["current_price"] == 0.6
    assert exit_call.kwargs["p_hat"] == 0.6  # should be recomputed p_hat (or fallback)
    assert exit_call.kwargs["days_to_expiry"] == int(5 * 60 / 86400)  # 5m window approx 0.00347 days, int conversion -> 0? Wait, window_duration_days returns 5/60/24 = 0.00347, remaining_days max(0.01, total_days - elapsed_days). Elapsed near zero, total_days = 5/(60*24) = 0.00347. remaining_days max(0.01, 0.00347) = 0.01, int(0.01) = 0. That could be zero, but days_to_expiry expects int. In original code they convert to int. That's fine.
    # We'll just assert call was made.

    # Cleanup (shutdown not needed because client is mock)
    await bot.shutdown()


@pytest.mark.asyncio
async def test_check_exits_no_exit_when_should_exit_false(tmp_config):
    """When should_exit returns False, sell should NOT be called."""
    bot = bot_main.TradingBot(
        config_path=str(tmp_config),
        dry_run=True,
        log_level="WARNING"
    )
    mock_client = AsyncMock()
    mock_client.get_ticker = AsyncMock(return_value=0.55)
    mock_client.sell = AsyncMock()
    bot.client = mock_client

    mock_decision_engine = MagicMock()
    mock_decision_engine.should_exit = MagicMock(return_value={
        "exit": False,
        "reason": "hold",
        "fair_value": 0.56,
        "edge": 0.01
    })
    bot.decision_engine = mock_decision_engine

    bot.positions = {
        "order-456": {
            "asset": "ETH",
            "window": "5m",
            "entry_price": 0.52,
            "shares": 200,
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "p_hat": 0.53,
        }
    }

    await bot.check_exits()

    # sell should NOT be called
    assert not mock_client.sell.called
    # positions should remain open
    assert len(bot.positions) == 1
    assert "order-456" in bot.positions

    await bot.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])