"""
Transition Matrix Builder — Core mathematical engine.

Implements the Markov chain transition matrix P where P[i][j] = probability
of moving from state i to state j. Based on the paper:
"The Math That Made $1M+ for Quant Traders in 30 Days"

Key idea: Build a probability table from recent price ticks, update every minute.
The diagonal P[i][i] = state persistence (how likely price stays in same bin).
Entry condition: diagonal ≥ 0.87 AND gap ≥ 0.05.
"""

from collections import deque
from typing import Deque, Tuple, Optional
import numpy as np
import time


def bin_price(price: float, n_states: int = 20) -> int:
    """
    Bin a continuous price into discrete state index.

    Args:
        price: Price in [0.01, 1.00] (Polymarket YES share probability)
        n_states: Number of discrete bins

    Returns:
        State index in [0, n_states-1]
    """
    if price <= 0.0:
        return 0
    if price >= 1.0:
        return n_states - 1
    # Use n_states-1 to avoid floating point issues at boundary
    idx = int(price * (n_states - 1))
    return min(idx, n_states - 1)


class TransitionMatrix:
    """
    Builds and maintains a transition matrix from a sliding window of price ticks.
    """

    def __init__(self,
                 n_states: int = 20,
                 window_size: int = 60,
                 smoothing_alpha: float = 0.3,
                 min_transitions: int = 30):
        self.n_states = n_states
        self.window_size = window_size
        self.smoothing_alpha = smoothing_alpha
        self.min_transitions = min_transitions

        # Circular buffer of (from_state, to_state) transitions
        self.buffer: Deque[Tuple[int, int]] = deque(maxlen=window_size)

        # Raw count matrix
        self.counts = np.zeros((n_states, n_states), dtype=np.int32)

        # Probability matrix P
        self.P = np.zeros((n_states, n_states), dtype=np.float64)

        # Previous P for exponential smoothing
        self.P_prev: Optional[np.ndarray] = None

        # Metadata
        self.last_update: float = 0.0
        self.is_valid: bool = False
        self.last_state: Optional[int] = None
        self.states: list[int] = []

    @property
    def total_transitions(self) -> int:
        return len(self.buffer)

    def add_transition(self, from_state: int, to_state: int) -> None:
        if not (0 <= from_state < self.n_states and 0 <= to_state < self.n_states):
            raise ValueError(f"State out of range: {from_state}→{to_state}")
        self.buffer.append((from_state, to_state))
        self.is_valid = False

    def update(self, price: float) -> None:
        state = bin_price(price, self.n_states)
        self.states.append(state)
        if self.last_state is not None:
            self.add_transition(self.last_state, state)
            # DEBUG: visible even at INFO log level
            print(f"[MATRIX] TRANSITION {self.last_state}->{state}  buffer={len(self.buffer)}  min={self.min_transitions}", flush=True)
        else:
            print(f"[MATRIX] FIRST_STATE {state}", flush=True)
        self.last_state = state
        if len(self.buffer) >= self.min_transitions:
            print(f"[MATRIX] Build triggered (buffer={len(self.buffer)} >= min={self.min_transitions})", flush=True)
            self.build_matrix()

    def add_price_sequence(self, prices: list[float], binner: callable) -> None:
        if len(prices) < 2:
            return
        prev_state = binner(prices[0])
        for p in prices[1:]:
            curr_state = binner(p)
            self.add_transition(prev_state, curr_state)
            prev_state = curr_state
        if len(self.buffer) >= self.min_transitions:
            self.build_matrix()

    def build_matrix(self, force: bool = False) -> None:
        if not force and len(self.buffer) < self.min_transitions:
            return
        print(f"[MATRIX] BUILD from buffer_len={len(self.buffer)}  (force={force})", flush=True)
        # Rebuild raw counts
        self.counts.fill(0)
        for from_s, to_s in self.buffer:
            self.counts[from_s, to_s] += 1
        # Row-normalize
        row_sums = self.counts.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1
        self.P = self.counts.astype(np.float64) / row_sums
        # Exponential smoothing
        if self.P_prev is not None and self.smoothing_alpha > 0:
            self.P = self.smoothing_alpha * self.P_prev + (1 - self.smoothing_alpha) * self.P
            # Renormalize after smoothing to ensure rows sum to 1
            row_sums = self.P.sum(axis=1, keepdims=True)
            row_sums[row_sums == 0] = 1
            self.P /= row_sums
        self.P_prev = self.P.copy()
        self.last_update = time.time()
        self.is_valid = True
        diag_mean = float(self.P.diagonal().mean())
        print(f"[MATRIX] BUILD COMPLETE — is_valid=True  diag_mean={diag_mean:.4f}", flush=True)

    def get_matrix(self) -> Optional[np.ndarray]:
        if not self.is_valid:
            return None
        return self.P

    def validate(self) -> Tuple[bool, list[str]]:
        warnings = []
        if not self.is_valid:
            self.build_matrix(force=True)
        if self.total_transitions < self.min_transitions:
            warnings.append(f"Not enough transitions: {self.total_transitions} < {self.min_transitions}")
            return False, warnings
        P = self.get_matrix()
        if P is None:
            warnings.append("Matrix is None after build")
            return False, warnings
        row_sums = P.sum(axis=1)
        nonzero = row_sums > 1e-9
        if nonzero.any() and not np.allclose(row_sums[nonzero], 1.0, atol=1e-5):
            warnings.append(f"Rows don't sum to 1: min={row_sums[nonzero].min():.6f}, max={row_sums[nonzero].max():.6f}")
        return len(warnings) == 0, warnings

    def get_diagonal_stats(self) -> dict:
        if not self.is_valid:
            self.build_matrix(force=True)
        if self.total_transitions < self.min_transitions:
            return {"valid": False}
        P = self.get_matrix()
        if P is None:
            return {"valid": False}
        diag = P.diagonal()
        return {
            "valid": True,
            "mean": float(diag.mean()),
            "std": float(diag.std()),
            "min": float(diag.min()),
            "max": float(diag.max()),
            "p_ge_0.87": float(np.mean(diag >= 0.87)),
        }

    def most_likely_next_state(self, state: int) -> Tuple[int, float]:
        P = self.get_matrix()
        if P is None:
            return -1, 0.0
        next_state = int(np.argmax(P[state]))
        prob = float(P[state, next_state])
        return next_state, prob

    def get_persistence(self) -> float:
        stats = self.get_diagonal_stats()
        return stats.get("mean", 0.0)

    def clear(self) -> None:
        self.buffer.clear()
        self.counts.fill(0)
        self.P.fill(0)
        self.P_prev = None
        self.is_valid = False
        self.last_state = None
        self.states.clear()

    def to_dict(self) -> dict:
        return {
            "n_states": self.n_states,
            "window_size": self.window_size,
            "smoothing_alpha": self.smoothing_alpha,
            "min_transitions": self.min_transitions,
            "buffer": list(self.buffer),
            "counts": self.counts.tolist(),
            "P": self.P.tolist(),
            "P_prev": self.P_prev.tolist() if self.P_prev is not None else None,
            "last_update": self.last_update,
            "is_valid": self.is_valid,
            "last_state": self.last_state,
            "states": self.states,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'TransitionMatrix':
        m = cls(
            n_states=data['n_states'],
            window_size=data['window_size'],
            smoothing_alpha=data['smoothing_alpha'],
            min_transitions=data['min_transitions']
        )
        m.buffer = deque(data['buffer'], maxlen=m.window_size)
        m.counts = np.array(data['counts'])
        m.P = np.array(data['P'])
        m.P_prev = np.array(data['P_prev']) if data.get('P_prev') else None
        m.last_update = data.get('last_update', 0.0)
        m.is_valid = data.get('is_valid', False)
        m.last_state = data.get('last_state')
        m.states = data.get('states', [])
        return m

    def __len__(self) -> int:
        return self.total_transitions

    def __repr__(self) -> str:
        return f"<TransitionMatrix states={self.n_states} transitions={self.total_transitions} valid={self.is_valid}>"

# Alias for backward compatibility / tests
def build_matrix_from_prices(prices: list[float], n_states: int = 100) -> np.ndarray:
    """Legacy: build a simple transition matrix from a price list (no sliding window)."""
    tm = TransitionMatrix(n_states=n_states, window_size=max(60, len(prices)-1), min_transitions=1)
    tm.add_price_sequence(prices, bin_price)
    matrix = tm.get_matrix()
    if matrix is None:
        raise RuntimeError("Failed to build matrix")
    return matrix
