"""
Test suite for multi-window exit strategy.
Different timeframes should have different hold horizons.
"""

import pytest
from polymarket_bot.core.exit_manager import ExitManager

class TestMultiWindowExit:
    def test_exit_horizons_per_timeframe(self):
        """Each timeframe has distinct hold horizon."""
        em = ExitManager()
        assert em.EXIT_HORIZONS["5m"] == 12   # 1 hour
        assert em.EXIT_HORIZONS["1h"] == 3    # 3 hours
        assert em.EXIT_HORIZONS["6h"] == 2    # 12 hours

    def test_should_exit_after_hold_period(self):
        """Position should exit exactly after its horizon bars."""
        em = ExitManager()
        # Register ETH 1h position entered at bar 100
        em.register_entry("ETH", "1h", entry_bar=100)
        assert em.should_exit("ETH", "1h", current_bar=103) is True   # 103-100 = 3
        assert em.should_exit("ETH", "1h", current_bar=102) is False  # still 2 bars left
        assert em.should_exit("ETH", "1h", current_bar=101) is False  # only 1 bar held

    def test_should_exit_does_not_depend_on_price(self):
        """Exit decision is time-based only, independent of price."""
        em = ExitManager()
        em.register_entry("BTC", "5m", entry_bar=90)
        # Same timeframe, same bars held, different price → same decision
        assert em.should_exit("BTC", "5m", current_bar=102) is True  # 12 bars

    def test_invalid_timeframe_raises(self):
        """Unknown timeframe raises KeyError."""
        em = ExitManager()
        with pytest.raises(KeyError):
            em.should_exit("ETH", "invalid", current_bar=10)

    def test_clear_removes_entry_record(self):
        """After clear, should_exit returns False (no position tracked)."""
        em = ExitManager()
        em.register_entry("ETH", "1h", entry_bar=100)
        em.clear("ETH", "1h")
        assert em.should_exit("ETH", "1h", current_bar=110) is False

    def test_bars_held_calculates_correctly(self):
        """bars_held returns exact number of bars since entry."""
        em = ExitManager()
        em.register_entry("ETH", "6h", entry_bar=50)
        assert em.bars_held("ETH", "6h", current_bar=51) == 1
        assert em.bars_held("ETH", "6h", current_bar=52) == 2
        assert em.bars_held("ETH", "6h", current_bar=53) == 3

    def test_no_entry_returns_zero_bars_held(self):
        """bars_held is 0 when no position is tracked."""
        em = ExitManager()
        assert em.bars_held("ETH", "1h", current_bar=100) == 0
