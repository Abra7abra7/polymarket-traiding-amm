#!/usr/bin/env python3
"""
Backtest script for Polymarket AMM bot with FIXED Markov matrix logic.
Uses simulated price data to verify the logic works correctly.
Compares OLD (broken) vs NEW (fixed) logic.
"""

import sys
import os
import json
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple

# Add the bot source to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from polymarket_bot.core.matrix import TransitionMatrix, bin_price

# Configuration
INITIAL_CAPITAL = 50000.0
TRADE_SIZE_USD = 100.0
TAU = 0.01
EPS = 0.08
N_STATES = 20
MIN_TRANSITIONS = 20
WINDOW_SIZE_5M = 60  # 60 bars

def generate_realistic_prices(n_prices: int = 500) -> List[float]:
    """
    Generate realistic price data simulating Polymarket BTC/ETH markets.
    Prices oscillate around 0.50 with mean-reversion and occasional trends.
    """
    prices = []
    current_price = 0.50
    
    for i in range(n_prices):
        # Add mean-reversion (prices tend to stay near 0.50)
        mean_reversion = (0.50 - current_price) * 0.1
        
        # Add random noise
        noise = np.random.normal(0, 0.02)
        
        # Add occasional trend (momentum)
        if i > 10:
            recent_change = current_price - prices[-5] if len(prices) >= 5 else 0
            momentum = recent_change * 0.3
        else:
            momentum = 0
        
        # Calculate new price
        new_price = current_price + mean_reversion + noise + momentum
        
        # Clip to valid range [0.01, 0.99]
        new_price = np.clip(new_price, 0.01, 0.99)
        
        prices.append(new_price)
        current_price = new_price
    
    return prices

def old_logic_p_hat(matrix: TransitionMatrix, state: int) -> float:
    """
    OLD (BROKEN) logic: Use diagonal (persistence) - 
    always predicts current state will persist.
    This was the bug in the original code.
    """
    # The old code was using diagonal mean (persistence)
    stats = matrix.get_diagonal_stats()
    return stats.get('mean', 0.0)

def new_logic_p_hat(matrix: TransitionMatrix, state: int) -> float:
    """
    NEW (FIXED) logic: Use argmax of full distribution -
    predicts the most likely NEXT state.
    This is the correct implementation.
    """
    next_state, prob = matrix.most_likely_next_state(state)
    return prob

def run_backtest(test_name: str, prices: List[float], use_new_logic: bool = True, market_name: str = "BTC_5M"):
    """Run a single backtest with given logic."""
    print(f"\n{'='*60}")
    print(f"BACKTEST: {test_name}")
    print(f"Logic: {'NEW (FIXED)' if use_new_logic else 'OLD (BROKEN)'}")
    print(f"{'='*60}")
    
    matrix = TransitionMatrix(n_states=N_STATES, min_transitions=MIN_TRANSITIONS)
    capital = INITIAL_CAPITAL
    positions = {}
    trades = []
    
    for i, price in enumerate(prices):
        current_state = bin_price(price, n_states=N_STATES)
        
        # Update matrix with transition (need at least 2 prices)
        if i > 0:
            prev_state = bin_price(prices[i-1], n_states=N_STATES)
            matrix.add_transition(prev_state, current_state)
            
            # Trigger matrix build if we have enough transitions
            if matrix.total_transitions >= MIN_TRANSITIONS and not matrix.is_valid:
                matrix.build_matrix()
        
        # Only evaluate after we have a valid matrix
        if not matrix.is_valid:
            continue
        
        # Calculate p_hat based on logic type
        if use_new_logic:
            p_hat = new_logic_p_hat(matrix, current_state)
        else:
            p_hat = old_logic_p_hat(matrix, current_state)
        
        # Current price info
        gap = abs(price - 0.50)
        direction = 'up' if price > 0.50 else 'down'
        
        # ENTRY: Check conditions
        should_enter = (
            p_hat >= 0.52 and
            gap >= 0.05 and
            market_name not in positions
        )
        
        if should_enter and capital >= TRADE_SIZE_USD:
            entry_price = price
            capital -= TRADE_SIZE_USD
            positions[market_name] = {
                'entry_price': entry_price,
                'entry_time': i,
                'size': TRADE_SIZE_USD,
                'direction': direction,
                'p_hat': p_hat
            }
            print(f"  [{i:4d}] ENTER @ {entry_price:.4f}, p_hat={p_hat:.4f}, gap={gap:.4f}")
        
        # EXIT: Check conditions
        elif market_name in positions:
            pos = positions[market_name]
            should_exit = (
                p_hat < 0.48 or
                gap < 0.02 or
                i - pos['entry_time'] > WINDOW_SIZE_5M
            )
            
            if should_exit:
                exit_price = price
                pnl_pct = (exit_price - pos['entry_price']) / pos['entry_price']
                pnl = TRADE_SIZE_USD * pnl_pct
                capital += TRADE_SIZE_USD + pnl
                
                trades.append({
                    'entry': pos['entry_price'],
                    'exit': exit_price,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct * 100,
                    'p_hat_entry': pos['p_hat'],
                    'p_hat_exit': p_hat,
                    'duration': i - pos['entry_time']
                })
                
                print(f"  [{i:4d}] EXIT  @ {exit_price:.4f}, P&L=${pnl:.2f} ({pnl_pct*100:.1f}%), p_hat={p_hat:.4f}")
                del positions[market_name]
    
    # Close any open positions at last price
    for market_name, pos in list(positions.items()):
        exit_price = prices[-1]
        pnl_pct = (exit_price - pos['entry_price']) / pos['entry_price']
        pnl = TRADE_SIZE_USD * pnl_pct
        capital += TRADE_SIZE_USD + pnl
        trades.append({
            'entry': pos['entry_price'],
            'exit': exit_price,
            'pnl': pnl,
            'pnl_pct': pnl_pct * 100,
            'p_hat_entry': pos['p_hat'],
            'p_hat_exit': 0.0,
            'duration': len(prices) - pos['entry_time']
        })
        print(f"  [{len(prices)}] CLOSE @ {exit_price:.4f}, P&L=${pnl:.2f}")
        del positions[market_name]
    
    # Calculate statistics
    n_trades = len(trades)
    n_wins = sum(1 for t in trades if t['pnl'] > 0)
    n_losses = n_trades - n_wins
    total_pnl = sum(t['pnl'] for t in trades)
    
    print(f"\nResults for {test_name}:")
    print(f"  Total trades: {n_trades}")
    print(f"  Wins: {n_wins}, Losses: {n_losses}")
    if n_trades > 0:
        print(f"  Win rate: {n_wins/n_trades*100:.1f}%")
    print(f"  Total P&L: ${total_pnl:.2f}")
    print(f"  Final capital: ${capital:.2f}")
    print(f"  Return: {((capital/INITIAL_CAPITAL)-1)*100:.2f}%")
    
    # Show matrix state
    print(f"  Matrix transitions: {matrix.total_transitions}")
    print(f"  Matrix valid: {matrix.is_valid}")
    diag_stats = matrix.get_diagonal_stats()
    print(f"  Diagonal mean (persistence): {diag_stats.get('mean', 0):.4f}")
    
    return {
        'trades': n_trades,
        'wins': n_wins,
        'losses': n_losses,
        'pnl': total_pnl,
        'capital': capital,
        'return_pct': ((capital/INITIAL_CAPITAL)-1)*100
    }

def main():
    print(f"\n{'='*60}")
    print(f"MARKOV MATRIX BACKTEST - FIXED vs BROKEN LOGIC")
    print(f"{'='*60}")
    print(f"Initial capital: ${INITIAL_CAPITAL:.2f}")
    print(f"n_states: {N_STATES} (fixed from 100)")
    print(f"Tau: {TAU}, Eps: {EPS}")
    print(f"Min transitions: {MIN_TRANSITIONS}")
    print(f"Trade size: ${TRADE_SIZE_USD}")
    print(f"{'='*60}\n")
    
    # Generate realistic price data
    print("Generating realistic price data (500 bars, ~42 hours of 5min data)...")
    np.random.seed(42)  # For reproducible results
    prices = generate_realistic_prices(n_prices=500)
    print(f"Generated {len(prices)} prices")
    print(f"Price range: {min(prices):.4f} - {max(prices):.4f}")
    print(f"Mean price: {np.mean(prices):.4f}")
    
    # Run backtest with NEW (fixed) logic
    new_results = run_backtest(
        "NEW FIXED LOGIC (argmax)",
        prices,
        use_new_logic=True
    )
    
    # Run backtest with OLD (broken) logic
    old_results = run_backtest(
        "OLD BROKEN LOGIC (diagonal/persistence)",
        prices,
        use_new_logic=False
    )
    
    # Comparison
    print(f"\n{'='*60}")
    print(f"COMPARISON: FIXED vs BROKEN")
    print(f"{'='*60}")
    print(f"                    NEW (FIXED)    OLD (BROKEN)    DIFFERENCE")
    print(f"{'-'*60}")
    print(f"Trades:            {new_results['trades']:>10}        {old_results['trades']:>10}        {new_results['trades']-old_results['trades']:>+10}")
    print(f"Win Rate:          {new_results['wins']/max(1,new_results['trades'])*100:>9.1f}%       {old_results['wins']/max(1,old_results['trades'])*100:>9.1f}%       {new_results['wins']/max(1,new_results['trades'])*100-old_results['wins']/max(1,old_results['trades'])*100:>+9.1f}%")
    print(f"Total P&L:         ${new_results['pnl']:>9.2f}      ${old_results['pnl']:>9.2f}      ${new_results['pnl']-old_results['pnl']:>+9.2f}")
    print(f"Final Capital:     ${new_results['capital']:>9.2f}      ${old_results['capital']:>9.2f}      ${new_results['capital']-old_results['capital']:>+9.2f}")
    print(f"Return:            {new_results['return_pct']:>9.1f}%       {old_results['return_pct']:>9.1f}%       {new_results['return_pct']-old_results['return_pct']:>+9.1f}%")
    print(f"{'='*60}\n")
    
    # Diagnosis
    print("DIAGNOSIS:")
    if old_results['trades'] == 0:
        print("  ✓ OLD logic correctly shows 0 or few trades (this was the bug)")
        print("    - Diagonal/persistence logic always predicts current state")
        print("    - p_hat was always low (mean diagonal ~0.20-0.40)")
        print("    - Entry condition p_hat >= 0.52 rarely/never satisfied")
    if new_results['trades'] > 0:
        print(f"  ✓ NEW logic generates {new_results['trades']} trades")
        print(f"    - argmax correctly finds most probable next state")
        print(f"    - p_hat now reflects actual transition probabilities")
        print(f"    - Entry condition can now be satisfied")
    print()

if __name__ == '__main__':
    main()
