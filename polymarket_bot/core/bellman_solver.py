"""
Bellman Optimal Stopping Solver for Polymarket Positions.
Implements V_t = max(M_t, E[V_{t+1}]) for binary prediction markets.
"""

import math
from typing import Tuple, Optional
import numpy as np


class BellmanSolver:
    """
    Solves optimal stopping for a binary prediction market position.
    
    Parameters
    ----------
    p_true : float
        Your model's estimated probability of YES (0 to 1).
    sigma : float
        Daily volatility (std dev of daily price moves).
    T : int
        Days until resolution.
    r : float, optional
        Daily risk-free rate (default 0).
    """
    
    def __init__(self, p_true: float, sigma: float, T: int, r: float = 0.0):
        self.p0 = p_true
        self.sigma = sigma
        self.T = T
        self.r = r
    
    def _approx_american_binary(self) -> float:
        """
        Approximate American binary option value (early exercise on binary payoff).
        Uses a discrete-time backward induction with a simple mean-reverting process.
        """
        steps = min(self.T, 120)  # cap steps for speed
        dt = 1.0
        
        # Probability grid
        n_grid = 501
        p_grid = np.linspace(0.001, 0.999, n_grid)
        # Terminal value: V_T(p) = p (expected payoff under your model)
        V = p_grid.copy()
        
        # Mean reversion speed toward p0
        k = 0.05
        vol = self.sigma
        
        for step in range(steps - 1, -1, -1):
            V_new = np.zeros_like(V)
            # Vectorized expectation over two-point distribution (up/down)
            for i, p in enumerate(p_grid):
                mu = k * (self.p0 - p)
                # Two-point Gauss-Hermite-ish (just ±1 sigma)
                samples = [
                    np.clip(p + mu - vol, 0.001, 0.999),
                    np.clip(p + mu + vol, 0.001, 0.999)
                ]
                V_samples = [np.interp(s, p_grid, V) for s in samples]
                continuation = 0.5 * sum(V_samples)
                V_new[i] = max(p, continuation)
            V = V_new
        
        return float(np.interp(self.p0, p_grid, V))
    
    def get_decision(self, current_prob: float, current_price: float, days_to_expiry: int) -> dict:
        """
        Return optimal action for current position.
        """
        fair = self._approx_american_binary()
        edge = fair - current_price
        
        if edge > 0.01:  # 1 cent buffer for fees
            action = "BUY/HOLD"
            threshold = None
        elif edge < -0.01:
            action = "SELL"
            threshold = round(fair, 4)
        else:
            action = "HOLD (no clear edge)"
            threshold = round(fair, 4)
        
        return {
            "fair_value": round(fair, 4),
            "current_price": current_price,
            "edge": round(edge, 4),
            "action": action,
            "optimal_exit_threshold": threshold,
            "days_to_expiry": days_to_expiry,
            "your_probability": current_prob
        }


# Test with article example
if __name__ == "__main__":
    solver = BellmanSolver(p_true=0.60, sigma=0.03, T=60)
    decision = solver.get_decision(current_prob=0.60, current_price=0.52, days_to_expiry=60)
    print(json.dumps(decision, indent=2))
