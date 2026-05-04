"""Unit tests for polymarket_bot.core.decision.DecisionEngine.

Tests:
  - Threshold checks (tau, eps, min_probability)
  - Kelly fraction calculation (cap/floor)
  - should_enter() decision logic
  - Edge cases: zero probabilities, extreme payoffs
"""

import pytest
import numpy as np
from polymarket_bot.core.decision import DecisionEngine


class TestDecisionEngineConstruction:
    """Test initial parameter validation."""

    def test_default_thresholds(self):
        de = DecisionEngine()
        assert de.tau == 0.87
        assert de.eps == 0.05
        assert de.min_probability == 0.01

    def test_custom_thresholds(self):
        de = DecisionEngine(tau=0.80, eps=0.10, min_probability=0.02)
        assert de.tau == 0.80
        assert de.eps == 0.10
        assert de.min_probability == 0.02

    def test_thresholds_must_be_positive(self):
        with pytest.raises(ValueError):
            DecisionEngine(tau=-0.1)
        with pytest.raises(ValueError):
            DecisionEngine(eps=0.0)
        with pytest.raises(ValueError):
            DecisionEngine(min_probability=1.5)


class TestShouldEnterLogic:
    """Test the core entry decision."""

    def create_matrix(self, diag_value: float, n_states: int = 100):
        """Helper: create matrix with uniform diagonal = diag_value."""
        off_diag = (1 - diag_value) / (n_states - 1)
        P = np.full((n_states, n_states), off_diag)
        np.fill_diagonal(P, diag_value)
        return P

    def test_enter_when_tau_and_eps_both_pass(self, decision_engine):
        """τ ≥ threshold AND ε ≥ threshold → entry."""
        P = self.create_matrix(diag_value=0.93)  # τ = 0.93 > 0.87
        state = 50
        price = 0.60

        # Compute p_hat manually: P[state, state] = 0.93, β = price = 0.60 → ε = 0.93 − 0.60 = 0.33
        enter, meta = decision_engine.should_enter(P, state, price)

        assert enter is True
        assert meta["persist"] >= 0.87
        assert meta["p_hat"] >= 0.87
        assert meta["cond_persist"] is True
        assert meta["cond_gap"] is True

    def test_no_enter_when_tau_too_low(self, decision_engine):
        """τ < threshold → no entry even if ε OK."""
        P = self.create_matrix(diag_value=0.80)  # τ = 0.80 < 0.87
        state = 50
        price = 0.50

        enter, meta = decision_engine.should_enter(P, state, price)
        assert enter is False
        assert meta["cond_persist"] is False
        # gap may still be true, but persist fail blocks entry
        assert meta["cond_gap"] is False or meta["gap"] < decision_engine.eps

    def test_no_enter_when_eps_too_low(self, decision_engine):
        """ε < threshold → no entry even if τ OK."""
        P = self.create_matrix(diag_value=0.93)  # τ high
        state = 50
        price = 0.92  # market almost certain → β ≈ 0.92, p̂=0.93 → ε=0.01

        enter, meta = decision_engine.should_enter(P, state, price)
        assert enter is False
        assert meta["cond_gap"] is False
        assert meta["gap"] < decision_engine.eps
    def test_no_enter_when_probability_below_min(self):
        # Use a custom engine with high min_probability
        de = DecisionEngine(min_probability=0.2)
        # Use a matrix where diagonal (max) probability is 0.1 < 0.2
        P = self.create_matrix(0.1, n_states=20)
        state = 10
        price = 0.05

        enter, meta = de.should_enter(P, state, price)
        assert enter is False
        assert meta["p_hat"] < de.min_probability

    def test_meta_dict_structure(self, decision_engine):
        """Meta output contains all required keys."""
        P = self.create_matrix(0.93)
        state = 50
        price = 0.5

        enter, meta = decision_engine.should_enter(P, state, price)

        required_keys = {"persist", "p_hat", "gap", "cond_persist", "cond_gap"}
        assert required_keys.issubset(meta.keys())


class TestKellyFraction:
    """Test Kelly Criterion position sizing."""

    def test_kelly_fraction_calculation(self):
        de = DecisionEngine()
        f = de.kelly_fraction(p_hat=0.7, market_price=0.6)
        assert 0.20 <= f <= 0.30

    def test_kelly_fraction_zero_when_fair_odds(self):
        de = DecisionEngine()
        f = de.kelly_fraction(p_hat=0.5, market_price=0.5)
        assert abs(f) < 1e-6

    def test_kelly_fraction_negative_means_dont_bet(self):
        de = DecisionEngine()
        f = de.kelly_fraction(p_hat=0.3, market_price=0.6)
        assert f < 0

    def test_kelly_cap_applied(self):
        de = DecisionEngine()
        de.kelly_cap_max = 0.50
        f = de.kelly_fraction(p_hat=0.95, market_price=0.2)
        assert f == 0.50  # capped

    def test_kelly_floor_applied(self):
        de = DecisionEngine()
        de.kelly_cap_min = 0.10
        f = de.kelly_fraction(p_hat=0.52, market_price=0.5)
        assert f == 0.10  # floored

    def test_position_size_calculation(self):
        de = DecisionEngine()
        portfolio = 10_000
        p_hat = 0.70
        price = 0.5
        cap_max = 0.80
        cap_min = 0.05

        capital, shares = de.position_size(
            portfolio_value=portfolio,
            p_hat=p_hat,
            market_price=price,
            cap_max=cap_max,
            cap_min=cap_min
        )

        assert capital > 0
        assert capital <= portfolio * cap_max
        assert capital >= portfolio * cap_min
        assert shares == int(capital / price)
        assert shares >= 1


class TestDecisionEngineEdgeCases:
    """Edge-case handling."""

    def test_zero_price_prevented(self):
        de = DecisionEngine()
        P = np.eye(100) * 0.9
        with pytest.raises(ValueError):
            de.should_enter(P, 50, 0.0)

    def test_price_above_one_prevented(self):
        de = DecisionEngine()
        P = np.eye(100) * 0.9
        with pytest.raises(ValueError):
            de.should_enter(P, 50, 1.5)

    def test_invalid_state_index(self):
        de = DecisionEngine()
        P = np.eye(100) * 0.9
        with pytest.raises(IndexError):
            de.should_enter(P, 150, 0.5)  # state out of bounds

    def test_wrong_matrix_shape(self):
        de = DecisionEngine()
        P = np.zeros((50, 100))  # non-square matrix
        with pytest.raises(ValueError):
            de.should_enter(P, 0, 0.5)
