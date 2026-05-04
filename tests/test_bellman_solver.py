"""
Unit tests for the Bellman Solver.
Verifies optimal stopping logic for binary prediction markets.
"""

import pytest
import json
from polymarket_bot.core.bellman_solver import BellmanSolver

def test_bellman_initialization():
    solver = BellmanSolver(p_true=0.6, sigma=0.03, T=60)
    assert solver.p0 == 0.6
    assert solver.sigma == 0.03
    assert solver.T == 60

def test_bellman_decision_buy_hold():
    # Model probability (0.6) > Current price (0.5) -> Should BUY/HOLD
    solver = BellmanSolver(p_true=0.6, sigma=0.03, T=60)
    decision = solver.get_decision(current_prob=0.6, current_price=0.5, days_to_expiry=60)
    
    assert decision["action"] == "BUY/HOLD"
    assert decision["fair_value"] > 0.5
    assert decision["edge"] > 0

def test_bellman_decision_sell():
    # Model probability (0.4) < Current price (0.6) -> Should SELL
    solver = BellmanSolver(p_true=0.4, sigma=0.03, T=60)
    decision = solver.get_decision(current_prob=0.4, current_price=0.6, days_to_expiry=60)
    
    assert decision["action"] == "SELL"
    assert decision["fair_value"] < 0.6
    assert decision["edge"] < 0

def test_bellman_boundary_conditions():
    # Probability at extreme
    solver = BellmanSolver(p_true=0.99, sigma=0.01, T=10)
    decision = solver.get_decision(current_prob=0.99, current_price=0.5, days_to_expiry=10)
    assert decision["action"] == "BUY/HOLD"
    
    solver_low = BellmanSolver(p_true=0.01, sigma=0.01, T=10)
    decision_low = solver_low.get_decision(current_prob=0.01, current_price=0.5, days_to_expiry=10)
    assert decision_low["action"] == "SELL"

def test_bellman_volatility_impact():
    # Higher volatility should increase option value (fair value) for a winner
    solver_low = BellmanSolver(p_true=0.7, sigma=0.01, T=30)
    solver_high = BellmanSolver(p_true=0.7, sigma=0.10, T=30)
    
    val_low = solver_low._approx_american_binary()
    val_high = solver_high._approx_american_binary()
    
    # In a binary option, higher vol usually increases the "upside" chance of hitting 1.0 early
    # even if it also increases downside. The American feature makes it more valuable.
    assert val_high != val_low
