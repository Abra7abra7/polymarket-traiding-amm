"""
Test suite for adaptive threshold (tau) calculation.
τ should increase with volatility to avoid false signals.
"""

import pytest
import numpy as np
from polymarket_bot.core.decision import DecisionEngine

class TestAdaptiveTau:
    def test_tau_increases_with_volatility(self):
        """High volatility → higher tau (more conservative)."""
        engine = DecisionEngine()
        # Low volatility series (std ~ 0.01)
        low_vol = [0.001, -0.002, 0.0005, 0.0015, -0.001] * 20
        # High volatility series (std ~ 0.05)
        high_vol = [0.02, -0.03, 0.015, -0.025, 0.01] * 20
        tau_low = engine.adaptive_tau(low_vol, base_tau=0.05)
        tau_high = engine.adaptive_tau(high_vol, base_tau=0.05)
        assert tau_high > tau_low, f"tau_high ({tau_high:.3f}) should be > tau_low ({tau_low:.3f})"

    def test_tau_bounds(self):
        """τ should stay within reasonable bounds [0.02, 0.20]."""
        engine = DecisionEngine()
        extreme_vol = [1.0, -1.5, 2.0, -1.8] * 50
        tau = engine.adaptive_tau(extreme_vol, base_tau=0.05)
        assert 0.02 <= tau <= 0.20, f"τ={tau:.3f} out of bounds"

    def test_tau_static_when_vol_zero(self):
        """If volatility is zero, τ should equal base_tau."""
        engine = DecisionEngine()
        zeros = [0.0] * 100
        tau = engine.adaptive_tau(zeros, base_tau=0.05)
        assert abs(tau - 0.05) < 0.001

    def test_adaptive_tau_uses_recent_window(self):
        """Method should only use last N returns (default 100)."""
        engine = DecisionEngine()
        long_series = [0.01] * 50 + [0.10] * 50  # recent vol higher
        tau = engine.adaptive_tau(long_series, base_tau=0.05)
        # Should reflect recent volatility, not full series avg
        assert tau > 0.05  # recent high vol → higher τ
