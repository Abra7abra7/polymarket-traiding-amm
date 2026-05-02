"""
Test suite for volume-based market filtering.
Poor liquidity markets should be rejected regardless of signal strength.
"""

import pytest
from polymarket_bot.core.volume_filter import VolumeFilter

class TestVolumeFilter:
    def test_accepts_high_volume_market(self):
        """Markets with volume above threshold should pass."""
        vf = VolumeFilter(min_volume_usd=50_000.0)
        assert vf.should_trade("BTC_1H", volume_usd=2_500_000.0) is True
        assert vf.should_trade("ETH_1H", volume_usd=1_800_000.0) is True

    def test_rejects_low_volume_market(self):
        """Markets below threshold are filtered out."""
        vf = VolumeFilter(min_volume_usd=100_000.0)
        assert vf.should_trade("VIE_RAIN_1H", volume_usd=80_000.0) is False
        assert vf.should_trade("PRG_RAIN_1H", volume_usd=30_000.0) is False

    def test_edge_case_at_threshold(self):
        """Exactly at threshold passes (>=)."""
        vf = VolumeFilter(min_volume_usd=100_000.0)
        assert vf.should_trade("EDGE", volume_usd=100_000.0) is True
        assert vf.should_trade("EDGE", volume_usd=99_999.99) is False

    def test_zero_volume_rejected(self):
        """Zero volume markets are always rejected."""
        vf = VolumeFilter(min_volume_usd=10_000.0)
        assert vf.should_trade("DEAD", volume_usd=0.0) is False

    def test_negative_volume_rejected(self):
        """Negative volume (data error) is rejected."""
        vf = VolumeFilter(min_volume_usd=10_000.0)
        assert vf.should_trade("ERROR", volume_usd=-100.0) is False

    def test_different_thresholds(self):
        """Filter respects configured threshold."""
        vf_low = VolumeFilter(min_volume_usd=10_000.0)
        vf_high = VolumeFilter(min_volume_usd=1_000_000.0)
        volume = 500_000.0
        assert vf_low.should_trade("X", volume) is True
        assert vf_high.should_trade("X", volume) is False
