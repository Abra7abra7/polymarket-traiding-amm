"""Decision Engine — Entry logic and position sizing.

Implements the two-condition entry filter from the paper:
  Condition 1 (gap):    p̂ - market_price ≥ ε  (ε = 0.05)
  Condition 2 (persist): P[j*,j*]          ≥ τ  (τ = 0.87)

And Kelly criterion position sizing: f* = (p̂ - (1-p̂)/b) capped to [0.05, 0.80].
"""

from typing import Tuple, Optional
import numpy as np
from .bellman_solver import BellmanSolver


class DecisionEngine:
    """
    Encapsulates all trading decisions: entry evaluation and position sizing.
    """

    def __init__(self,
                 tau: float = 0.87,
                 eps: float = 0.05,
                 min_probability: float = 0.01,
                 stop_loss_pct: float = 0.02,
                 take_profit_pct: float = 0.03):
        """
        Args:
            tau: Persistence threshold (diagonal element must exceed this)
            eps: Gap threshold (model-market difference must exceed this)
            min_probability: Minimum probability to consider (avoid noise near 0)
            stop_loss_pct: Percentage loss to trigger exit (e.g., 0.02 for 2%)
            take_profit_pct: Percentage gain to trigger exit (e.g., 0.10 for 10%)
        """
        # Validate thresholds
        if not (0 < tau <= 1):
            raise ValueError("tau must be in (0, 1]")
        if not (0 < eps <= 1):
            raise ValueError("eps must be in (0, 1]")
        if not (0 < min_probability <= 1):
            raise ValueError("min_probability must be in (0, 1]")

        self.tau = tau
        self.eps = eps
        self.min_probability = min_probability
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

        # Kelly caps – mutable via direct assignment (tests tweak these)
        self.kelly_cap_max = 0.80
        self.kelly_cap_min = 0.05

    def adaptive_tau(self, recent_returns: list[float], base_tau: float = 0.05,
                     window: int = 100, min_tau: float = 0.02, max_tau: float = 0.20,
                     vol_scale: float = 2.0) -> float:
        """
        Compute volatility-adjusted tau threshold.

        Higher volatility → more conservative (higher tau) to avoid false signals.
        Uses only the last `window` returns from the series.

        Formula: τ_adj = base_tau * (1 + vol * vol_scale), clamped to [min_tau, max_tau]

        Args:
            recent_returns: List of historical returns (will use last `window` entries)
            base_tau: Base threshold when volatility is zero (default 0.05)
            window: Rolling window size (default 100 bars)
            min_tau: Minimum allowed tau (default 0.02)
            max_tau: Maximum allowed tau (default 0.20)
            vol_scale: Volatility scaling multiplier (default 2.0)

        Returns:
            Adjusted tau in [min_tau, max_tau]
        """
        # Use only recent window
        window_returns = recent_returns[-window:] if len(recent_returns) > window else recent_returns
        if len(window_returns) < 2:
            return base_tau

        # Compute volatility as standard deviation of returns
        volatility = np.std(window_returns)

        # Scale tau: base * (1 + vol * scale)
        adjusted = base_tau * (1 + volatility * vol_scale)

        # Clamp to bounds
        return float(np.clip(adjusted, min_tau, max_tau))

    def should_enter(self, P: np.ndarray, state: int, price: float) -> Tuple[bool, dict]:
        """
        Evaluate whether to enter a trade.

        Exactly the function from the paper:
          j*  = argmax(P[state])
          p̂   = P[state, j*]
          persist = mean(diag(P))
          gap = p̂ - price
          cond_persist = persist ≥ τ
          cond_gap_raw = gap ≥ ε
          cond_gap = cond_persist AND cond_gap_raw
          cond_prob = p̂ ≥ min_probability
          decision = cond_gap AND cond_prob

        Args:
            P: Transition matrix (n_states x n_states)
            state: Discretized current price bin
            price: Continuous price in (0, 1]

        Returns:
            (decision: bool, meta: dict)
        """
        # 1. Matrix shape & type
        if not isinstance(P, np.ndarray) or P.ndim != 2:
            raise ValueError("Transition matrix must be a 2D numpy array")
        if P.shape[0] != P.shape[1]:
            raise ValueError("Transition matrix must be square")

        n_states = P.shape[0]

        # 2. State bounds (before row checks – separate test for this condition)
        if not (0 <= state < n_states):
            raise IndexError(f"State index {state} out of range [0, {n_states})")

        # 3. Price range
        if not (0 < price <= 1.0):
            raise ValueError("price must be in (0, 1]")

        # 4. Stochastic rows (non-zero rows must sum to 1)
        row_sums = P.sum(axis=1)
        nonzero = row_sums > 1e-9
        if nonzero.any() and not np.allclose(row_sums[nonzero], 1.0, atol=1e-5):
            raise ValueError("Transition matrix rows must sum to 1")

        # Core metrics
        persist = float(P.diagonal().mean())

        # p̂: probability of most likely next state (NOT the diagonal!)
        # Per paper: j* = argmax(P[state]), p̂ = P[state, j*]
        next_state = int(np.argmax(P[state]))
        p_hat = float(P[state, next_state])

        gap = p_hat - price

        # Conditions
        cond_persist = persist >= self.tau
        cond_gap_raw = gap >= self.eps
        cond_gap = cond_persist and cond_gap_raw
        cond_prob = p_hat >= self.min_probability

        decision = cond_gap and cond_prob

        # DEBUGLOG
        import sys
        print(f"[DECISION] persist={persist:.4f} p_hat={p_hat:.4f} gap={gap:.4f} tau={self.tau} eps={self.eps} -> decision={decision}", file=sys.stderr, flush=True)

        meta = {
            "persist": persist,
            "p_hat": p_hat,
            "gap": gap,
            "cond_persist": cond_persist,
            "cond_gap": cond_gap,
        }
        return decision, meta

    def kelly_fraction(self,
                       p_hat: float,
                       market_price: float,
                       cap_max: float = None,
                       cap_min: float = None) -> float:
        """
        Compute Kelly criterion fraction.

        Formula: b = (1 - market_price) / market_price
                 f = p̂ - (1 - p̂) / b

        Caps: ceiling at cap_max; floor applied only for positive f (if f > 0 and f < cap_min).
        Negative f is returned unchanged (signals no-bet).
        """
        if market_price <= 0:
            raise ValueError("market_price must be positive")

        if cap_max is None:
            cap_max = self.kelly_cap_max
        if cap_min is None:
            cap_min = self.kelly_cap_min

        b = (1.0 - market_price) / market_price
        f = p_hat - (1.0 - p_hat) / b

        # Apply ceiling
        if f > cap_max:
            f = cap_max
        # Apply floor only for positive f
        if f > 0 and f < cap_min:
            f = cap_min
        # Negative f remains negative
        return f

    def position_size(self,
                      portfolio_value: float,
                      p_hat: float,
                      market_price: float,
                      cap_max: float = None,
                      cap_min: float = None) -> Tuple[float, int]:
        """
        Calculate position size (capital to risk and number of shares).

        Returns:
            (capital_allocated_usd, number_of_shares)
        """
        if portfolio_value <= 0:
            return 0.0, 0

        if cap_max is None:
            cap_max = self.kelly_cap_max
        if cap_min is None:
            cap_min = self.kelly_cap_min

        f = self.kelly_fraction(p_hat, market_price, cap_max, cap_min)
        if f <= 0:
            return 0.0, 0

        capital = portfolio_value * f
        # Ensure bounds despite Kelly output
        capital = max(portfolio_value * cap_min, min(portfolio_value * cap_max, capital))
        shares = int(capital / market_price) if market_price > 0 else 0
        return capital, shares

    def expected_return(self, p_hat: float, market_price: float) -> float:
        """Expected fractional return for a single trade."""
        if market_price <= 0:
            return 0.0
        return (p_hat - market_price) / market_price

    def evaluate_trade(self, P: np.ndarray, state: int, price: float, portfolio_value: float) -> dict:
        """
        Full evaluation wrapper.

        Returns a dict with decision, metrics, and size details if entering.
        """
        decision, meta = self.should_enter(P, state, price)

        result = {
            "decision": decision,
            "p_hat": meta["p_hat"],
            "persist": meta["persist"],
            "gap": meta["gap"],
            "expected_return": self.expected_return(meta["p_hat"], price) if decision else 0.0,
            "metadata": meta,
        }

        if decision:
            capital, shares = self.position_size(
                portfolio_value=portfolio_value,
                p_hat=meta["p_hat"],
                market_price=price
            )
            result["capital"] = capital
            result["shares"] = shares
            result["kelly_fraction"] = self.kelly_fraction(meta["p_hat"], price)

        return result
    def should_exit(self, entry_price: float, entry_shares: int,
                    current_price: float, p_hat: float,
                    days_to_expiry: int, sigma: float = 0.03,
                    max_price: float = 0.0) -> dict:
        """
        Bellman optimal stopping decision for exiting an existing position.

        Args:
            entry_price: Price at which the position was opened
            entry_shares: Number of shares held
            current_price: Current market price
            p_hat: Your model's current probability estimate
            days_to_expiry: Days until market resolution
            sigma: Daily volatility (default 0.03)
            max_price: Maximum price seen since entry (for trailing stop)

        Returns:
            dict with keys: exit (bool), fair_value, edge, reason
        """
        # --- True Trailing Stop Loss (drawdown from MAX price) ---
        reference_price = max(entry_price, max_price)
        drawdown = (current_price - reference_price) / reference_price if reference_price > 0 else 0.0
        
        if drawdown <= -self.stop_loss_pct:
            return {
                "exit": True,
                "fair_value": None,
                "current_price": current_price,
                "edge": round((current_price - entry_price) * entry_shares, 4),
                "reason": f"trailing_stop_{int(self.stop_loss_pct*100)}pct",
                "entry_price": entry_price,
                "entry_shares": entry_shares,
                "potential_pnl_per_share": round(current_price - entry_price, 4),
                "unrealized_pct": round(((current_price - entry_price) / entry_price) * 100, 2),
            }

        # --- Take-profit tiers ---
        unrealized = (current_price - entry_price) / entry_price if entry_price > 0 else 0.0
        if unrealized >= self.take_profit_pct:
            return {
                "exit": True,
                "fair_value": None,
                "current_price": current_price,
                "edge": round(unrealized * entry_price * entry_shares, 4),
                "reason": f"take_profit_{int(self.take_profit_pct*100)}pct",
                "entry_price": entry_price,
                "entry_shares": entry_shares,
                "potential_pnl_per_share": round(current_price - entry_price, 4),
                "unrealized_pct": round(unrealized * 100, 2),
            }

        # --- Bellman optimal stopping ---
        solver = BellmanSolver(p_true=p_hat, sigma=sigma, T=days_to_expiry)
        fair_value = solver._approx_american_binary()

        edge = fair_value - current_price
        exit_signal = current_price >= fair_value - 0.01

        return {
            "exit": exit_signal,
            "fair_value": round(fair_value, 4),
            "current_price": current_price,
            "edge": round(edge, 4),
            "reason": "price_above_fair" if exit_signal else "hold_continuation",
            "entry_price": entry_price,
            "entry_shares": entry_shares,
            "potential_pnl_per_share": round(current_price - entry_price, 4) if exit_signal else None,
            "unrealized_pct": round(unrealized * 100, 2),
        }

