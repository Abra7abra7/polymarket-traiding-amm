"""
Unit tests for polymarket_bot.core.matrix.TransitionMatrix and bin_price.

Tests align with actual implementation API:
  - `buffer` stores (from_state, to_state) tuples
  - `total_transitions` counts added transitions
  - `get_matrix()` returns None until build_matrix() called (but initialize sets zeros)
  - After build, rows with transitions sum to 1.0 when smoothing_alpha=0
  - `counts` is int ndarray
"""

import pytest
import numpy as np
from polymarket_bot.core.matrix import TransitionMatrix, bin_price


class TestConstruction:
    def test_default(self):
        m = TransitionMatrix()
        assert m.n_states == 100
        assert m.window_size == 60
        assert m.smoothing_alpha == 0.3
        assert m.min_transitions == 30
        assert m.buffer.maxlen == 60
        assert len(m.buffer) == 0
        assert m.total_transitions == 0
        assert m.P_prev is None
        assert m.P.shape == (100, 100)
        assert np.all(m.P == 0)

    def test_custom(self):
        m = TransitionMatrix(n_states=50, window_size=10, smoothing_alpha=0.2, min_transitions=5)
        assert m.n_states == 50
        assert m.window_size == 10
        assert m.buffer.maxlen == 10


class TestBinPrice:
    @pytest.mark.parametrize("price,exp", [
        (0.0, 0), (1.0, 99), (0.5, 50), (0.01, 1), (0.99, 99),
    ])
    def test_bin(self, price, exp):
        s = bin_price(price, n_states=100)
        assert 0 <= s < 100
        assert abs(s - exp) <= 1

    def test_clamp(self):
        assert bin_price(-0.1, 100) == 0
        assert bin_price(1.2, 100) == 99


class TestUpdate:
    def test_first_no_transition(self):
        m = TransitionMatrix(window_size=5)
        m.update(0.3)
        assert m.total_transitions == 0
        assert len(m.buffer) == 0
        assert m.last_state == bin_price(0.3, m.n_states)

    def test_second_creates_transition(self):
        m = TransitionMatrix(window_size=5)
        m.update(0.3)
        m.update(0.4)
        assert m.total_transitions == 1
        assert len(m.buffer) == 1
        fs, ts = m.buffer[0]
        assert fs == bin_price(0.3, m.n_states)
        assert ts == bin_price(0.4, m.n_states)

    def test_multiple(self):
        m = TransitionMatrix(window_size=5)
        prices = [0.1, 0.2, 0.3, 0.4, 0.5]
        for p in prices:
            m.update(p)
        assert m.total_transitions == 4

    def test_buffer_maxlen(self):
        m = TransitionMatrix(window_size=4)
        for i in range(5):
            m.update(i*0.1)
        assert len(m.buffer) == 4  # holds last 4 transitions
        m.update(0.5)
        assert len(m.buffer) == 4
        # Oldest (0,1) should be gone
        assert (0, 1) not in m.buffer


class TestBuildMatrix:
    def test_auto_build_after_min_transitions(self):
        m = TransitionMatrix(n_states=10, window_size=5, min_transitions=1, smoothing_alpha=0)
        m.update(0.3)
        m.update(0.4)
        P = m.get_matrix()
        assert P is not None
        assert P.shape == (10, 10)
        # Matrix should be valid (is_valid True)
        assert m.is_valid

    def test_force_build(self):
        m = TransitionMatrix(n_states=10, window_size=5, min_transitions=10, smoothing_alpha=0)
        for p in [0.3, 0.4]:
            m.update(p)
        # Without force, matrix may be zeros but is_valid False
        assert not m.is_valid
        m.build_matrix(force=True)
        P = m.get_matrix()
        assert P is not None


class TestNormalization:
    def test_rows_sum_to_one_no_smoothing(self):
        m = TransitionMatrix(n_states=10, window_size=5, min_transitions=1, smoothing_alpha=0)
        for p in [0.3, 0.4, 0.5, 0.6]:
            m.update(p)
        P = m.get_matrix()
        row_sums = P.sum(axis=1)
        nonzero = row_sums > 1e-9
        assert np.allclose(row_sums[nonzero], 1.0, atol=1e-6)


class TestValidate:
    def test_valid_when_enough_and_normalized(self):
        m = TransitionMatrix(n_states=10, window_size=5, min_transitions=1, smoothing_alpha=0)
        for p in [0.3, 0.4, 0.5]:
            m.update(p)
        valid, warnings = m.validate()
        assert valid is True
        assert warnings == []

    def test_invalid_too_few_transitions(self):
        m = TransitionMatrix(n_states=10, window_size=5, min_transitions=10, smoothing_alpha=0)
        for p in [0.3, 0.4, 0.5]:
            m.update(p)
        valid, warnings = m.validate()
        assert valid is False
        assert any("Not enough transitions" in w for w in warnings)


class TestDiagonalStats:
    def test_keys(self):
        m = TransitionMatrix(n_states=20, window_size=5, min_transitions=1, smoothing_alpha=0)
        for p in [0.3, 0.4, 0.5]:
            m.update(p)
        stats = m.get_diagonal_stats()
        for k in ["mean", "std", "min", "max", "p_ge_0.87"]:
            assert k in stats

    def test_mean_in_range(self):
        m = TransitionMatrix(n_states=20, window_size=5, min_transitions=1, smoothing_alpha=0)
        for p in np.linspace(0.3, 0.7, 10):
            m.update(p)
        s = m.get_diagonal_stats()
        assert 0.0 <= s["mean"] <= 1.0


class TestScalability:
    @pytest.mark.parametrize("n", [10, 50, 100])
    def test_matrix_size(self, n):
        m = TransitionMatrix(n_states=n, window_size=5, min_transitions=1, smoothing_alpha=0)
        for p in [0.3, 0.4, 0.5]:
            m.update(p)
        P = m.get_matrix()
        assert P.shape == (n, n)

    @pytest.mark.parametrize("n", [10, 50, 100])
    def test_normalization(self, n):
        m = TransitionMatrix(n_states=n, window_size=5, min_transitions=1, smoothing_alpha=0)
        for i in range(20):
            m.update(i/100.0)
        P = m.get_matrix()
        row_sums = P.sum(axis=1)
        nonzero = row_sums > 1e-9
        assert np.allclose(row_sums[nonzero], 1.0, atol=1e-5)


class TestIntegration:
    def test_matrix_becomes_valid_after_enough_data(self):
        m = TransitionMatrix(n_states=20, window_size=10, min_transitions=1, smoothing_alpha=0)
        assert not m.is_valid
        m.update(0.3)
        m.update(0.4)
        assert m.is_valid
