"""
Test suite for market regime detection (bull/bear/sideways).
Regime influences tau thresholds and position sizing.
"""

import pytest
import numpy as np
from polymarket_bot.core.regime_detector import RegimeDetector

class TestRegimeDetector:
    def test_bull_market_recognized(self):
        """Strong upward trend is classified as BULL."""
        detector = RegimeDetector(lookback=20, up_threshold=0.03, down_threshold=-0.03)
        # Simulate rising prices (monotonic increase)
        prices = np.linspace(100, 130, 30)  # +30% over 30 bars
        regime = detector.detect(prices)
        assert regime == "BULL"

    def test_bear_market_recognized(self):
        """Strong downward trend is classified as BEAR."""
        detector = RegimeDetector(lookback=20, up_threshold=0.03, down_threshold=-0.03)
        prices = np.linspace(130, 100, 30)  # -23% over 30 bars
        regime = detector.detect(prices)
        assert regime == "BEAR"

    def test_sideways_market_recognized(self):
        """Choppy/sideways price action classified as SIDEWAYS."""
        detector = RegimeDetector(lookback=20, up_threshold=0.02, down_threshold=-0.02)
        # Flat prices with tiny noise
        np.random.seed(42)
        prices = 100 + np.random.randn(30) * 0.5  # ±0.5% noise
        regime = detector.detect(prices)
        assert regime == "SIDEWAYS"

    def test_insufficient_data_returns_unknown(self):
        """With too few prices, regime is UNKNOWN."""
        detector = RegimeDetector(lookback=20)
        regime = detector.detect([100, 101, 102])  # only 3 prices
        assert regime == "UNKNOWN"

    def test_tau_adjustment_per_regime(self):
        """Each regime has a tau multiplier applied."""
        detector = RegimeDetector()
        assert detector.get_tau_multiplier("BULL") == 1.2   # higher threshold (conservative)
        assert detector.get_tau_multiplier("BEAR") == 1.5   # even more conservative
        assert detector.get_tau_multiplier("SIDEWAYS") == 1.0  # normal
        assert detector.get_tau_multiplier("UNKNOWN") == 1.0  # default

    def test_regime_uses_rolling_window(self):
        """Regime is recomputed as new prices arrive (sliding window)."""
        detector = RegimeDetector(lookback=10)
        # Start flat
        prices1 = [100]*10 + [100.5, 101.0]
        regime1 = detector.detect(np.array(prices1))
        # Add more upward
        prices2 = prices1 + [102.0, 103.0]
        regime2 = detector.detect(np.array(prices2))
        # Regime could strengthen or stay BULL
        assert regime2 in ("BULL", "SIDEWAYS")  # depends on exact thresholds

    def test_invalid_input_raises(self):
        """Non-numeric or None prices raise error."""
        detector = RegimeDetector()
        with pytest.raises(ValueError):
            detector.detect([100, "bad", 102])
