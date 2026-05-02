"""
Test suite for trailing stop loss based on volatility.
Uses high-water mark and ATR-like volatility buffer.
"""

import pytest
import numpy as np
from polymarket_bot.core.trailing_stop import TrailingStop

class TestTrailingStop:
    def test_initial_state_no_exit(self):
        """Fresh position with rising price should not exit."""
        ts = TrailingStop(atr_multiplier=2.0, volatility_window=14)
        ts.update(price=1.00, is_entry=True)      # entry at $1.00
        ts.update(price=1.10)                      # price rises to $1.10
        assert not ts.should_exit(current_price=1.10, atr=0.02)

    def test_exit_on_drawdown_below_atr_buffer(self):
        """Exit triggers when drawdown exceeds ATR buffer from high."""
        ts = TrailingStop(atr_multiplier=2.0, volatility_window=14)
        ts.update(price=100.0, is_entry=True)     # entry at $100 (high_water=$100)
        ts.update(price=120.0)                     # rises to $120 (high_water=$120)
        ts.update(price=115.0)                     # pullback to $115
        # Buffer = 2.0 * atr=2.0 = $4.  High water = $120 → exit if price ≤ 116
        assert ts.should_exit(current_price=115.0, atr=2.0) is True

    def test_no_exit_within_buffer(self):
        """Price within ATR buffer should not exit."""
        ts = TrailingStop(atr_multiplier=2.0, volatility_window=14)
        ts.update(price=100.0, is_entry=True)
        ts.update(price=120.0)
        # Buffer = $4, high=$120, floor=$116. Price at $117 is still above floor.
        assert not ts.should_exit(current_price=117.0, atr=2.0)

    def test_atr_zero_uses_min_buffer(self):
        """If ATR is zero, use minimum buffer to avoid premature exits."""
        ts = TrailingStop(atr_multiplier=2.0, volatility_window=14, min_buffer_pct=0.01)
        ts.update(price=100.0, is_entry=True)
        # With 1% of $100 = $1 buffer, exit if price ≤ 99
        # Scenario A: price at 98 → exit
        ts_a = TrailingStop(atr_multiplier=2.0, volatility_window=14, min_buffer_pct=0.01)
        ts_a.update(price=100.0, is_entry=True)
        assert ts_a.should_exit(current_price=98.0, atr=0.0) is True
        # Scenario B: price at 99.5 → no exit (above $99 stop)
        ts_b = TrailingStop(atr_multiplier=2.0, volatility_window=14, min_buffer_pct=0.01)
        ts_b.update(price=100.0, is_entry=True)
        assert not ts_b.should_exit(current_price=99.5, atr=0.0)

    def test_resets_after_explicit_reset(self):
        """After manual reset, internal state clears for next entry."""
        ts = TrailingStop(atr_multiplier=2.0, volatility_window=14)
        ts.update(price=100.0, is_entry=True)
        ts.update(price=120.0)
        assert ts.should_exit(current_price=115.0, atr=2.0) is True  # triggers exit
        assert ts.exited is True
        # New position
        ts.reset()
        ts.update(price=200.0, is_entry=True)
        assert ts.exited is False
        assert ts.highest_price == 200.0

    def test_volatility_window_tracks_recent_prices(self):
        """Internal volatility estimator updates with price history."""
        ts = TrailingStop(atr_multiplier=2.0, volatility_window=3)
        ts.update(price=100.0, is_entry=True)
        ts.update(price=101.0)
        ts.update(price=100.5)
        ts.update(price=99.0)
        # Volatility from last 3 closes: [101.0, 100.5, 99.0]
        volatility = ts._current_volatility()
        expected_buffer = 2.0 * volatility
        # Expected buffer should be positive and roughly 1.5-2.5 given volatility ~0.85
        assert 1.0 < expected_buffer < 3.0

    def test_buffer_uses_atr_when_provided(self):
        """When ATR > 0, buffer = multiplier * ATR (ignores volatility)."""
        ts = TrailingStop(atr_multiplier=2.5, volatility_window=14)
        ts.update(price=50.0, is_entry=True)
        # Explicit ATR=3.0 → buffer = 2.5 * 3.0 = 7.5
        buffer = ts._buffer_amount(atr=3.0)
        assert buffer == 7.5

    def test_min_buffer_is_percentage_of_highest(self):
        """Minimum buffer scales with high-water mark."""
        ts = TrailingStop(atr_multiplier=2.0, min_buffer_pct=0.02)  # 2%
        ts.update(price=200.0, is_entry=True)
        ts.update(price=250.0)  # new high-water
        # highest_price = 250, min_buffer = 250 * 0.02 = 5.0
        min_buf = ts._buffer_amount(atr=0.0)  # atr=0 forces min_buffer path
        # Since volatility might add buffer, check that min_buffer is at least 5.0
        assert min_buf >= 5.0
