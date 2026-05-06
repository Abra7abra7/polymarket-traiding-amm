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
    
    def __init__(self, 
                 p_true: float, 
                 sigma: float, 
                 T: int, 
                 r: float = 0.0, 
                 discount_factor: float = 0.99,
                 swap_fee: float = 0.015,
                 gas_cost_usd: float = 0.01):
        self.p0 = p_true
        self.sigma = sigma
        self.T = T
        self.r = r
        self.discount_factor = discount_factor
        self.swap_fee = swap_fee
        self.gas_cost_usd = gas_cost_usd
    
    def _approx_american_binary(self, current_price: float = 0.5) -> float:
        """
        Backward induction for V(s) with cost-aware rewards.
        V(s) = max(Price - Costs, E[V(s') * Discount])
        """
        steps = min(self.T, 120)
        dt = 1.0
        
        # Probability grid
        n_grid = 501
        p_grid = np.linspace(0.001, 0.999, n_grid)
        
        # Terminal value: V_T(p) = p (Expected payoff)
        V = p_grid.copy()
        
        # Cost adjustment (fractional)
        # Assuming typical position size for gas normalization
        cost_penalty = self.swap_fee + (self.gas_cost_usd / 100.0) # Normalized to $100 pos
        
        k = 0.05 # Mean reversion
        vol = self.sigma
        
        for step in range(steps - 1, -1, -1):
            V_new = np.zeros_like(V)
            for i, p in enumerate(p_grid):
                mu = k * (self.p0 - p)
                samples = [
                    np.clip(p + mu - vol, 0.001, 0.999),
                    np.clip(p + mu + vol, 0.001, 0.999)
                ]
                V_samples = [np.interp(s, p_grid, V) for s in samples]
                
                # Continuation value with discount
                continuation = (0.5 * sum(V_samples)) * self.discount_factor
                
                # Stopping value with transaction costs
                stopping = p - cost_penalty
                
                V_new[i] = max(stopping, continuation)
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
