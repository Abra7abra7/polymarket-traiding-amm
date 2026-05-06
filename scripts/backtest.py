"""
Backtest Engine — Historical performance simulation for the Polymarket Bot.

Simulates the full trading loop with historical data, accounting for:
- Slippage (volatility-based)
- Transaction Fees (swap fees + gas)
- Market impact
"""

import sys
import os
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from polymarket_bot.core.matrix import TransitionMatrix, bin_price
from polymarket_bot.core.decision import DecisionEngine
from polymarket_bot.core.tensor import TensorCore
from polymarket_bot.config.loader import load_config

class BacktestEngine:
    def __init__(self, config_path: str, initial_capital: float = 5000.0):
        self.config = load_config(config_path)
        self.capital = initial_capital
        self.initial_capital = initial_capital
        
        self.decision_engine = DecisionEngine(
            tau=self.config.trading.thresholds.tau,
            eps=self.config.trading.thresholds.eps,
            stop_loss_pct=self.config.trading.thresholds.trailing_stop_pct,
            kelly_cap_max=self.config.position.kelly.cap_max,
            kelly_cap_min=self.config.position.kelly.cap_min,
            kelly_fraction=getattr(self.config.position.kelly, 'fraction', 0.5),
            swap_fee=getattr(self.config.paper_trading, 'swap_fee_bps', 150) / 10000.0,
            gas_cost_usd=getattr(self.config.paper_trading, 'gas_fee_usd', 0.01)
        )
        
        self.matrices = {}
        self.positions = [] # list of dicts
        self.history = []   # list of daily snapshots
        
        # Performance metrics
        self.equity_curve = [initial_capital]
        self.trades = []

    def run(self, data: pd.DataFrame, asset: str = "BTC", window: str = "1H"):
        """
        Run backtest on a DataFrame with columns: [timestamp, price, volume]
        """
        print(f"Starting backtest for {asset}:{window}...")
        
        # Initialize matrix
        matrix = TransitionMatrix(
            window_size=self.config.trading.markov.window_sizes.get(window, 100),
            n_states=self.config.trading.markov.n_states,
            min_transitions=self.config.trading.markov.min_transitions
        )
        
        for i in range(len(data)):
            tick = data.iloc[i]
            price = tick['price']
            ts = tick['timestamp']
            
            # 1. Update Matrix
            matrix.update(price, label=f"{asset}:{window}")
            
            if not matrix.is_valid:
                continue

            # 2. Check Exits
            self._handle_exits(price, ts, matrix)
            
            # 3. Check Entry
            if len(self.positions) == 0: # simplified: 1 pos at a time for backtest
                state = bin_price(price)
                decision, meta = self.decision_engine.should_enter(matrix.get_matrix(), state, price)
                
                if decision:
                    self._handle_entry(price, ts, meta, asset, window)

            # Daily tracking
            self.equity_curve.append(self.get_total_value(price))

        self.report()

    def _handle_entry(self, price, ts, meta, asset, window):
        # Slippage simulation: 1% of volatility or fixed 0.5%
        slippage = price * 0.005 
        entry_price = price + slippage
        
        # Fees
        fees = entry_price * 0.015 # 1.5% swap fee
        
        capital, shares = self.decision_engine.position_size(self.capital, meta['p_hat'], entry_price)
        
        if shares > 0:
            cost = (shares * entry_price) + fees
            if cost <= self.capital:
                self.capital -= cost
                self.positions.append({
                    'asset': asset,
                    'window': window,
                    'entry_price': entry_price,
                    'shares': shares,
                    'entry_time': ts,
                    'p_hat': meta['p_hat']
                })
                # print(f"[{ts}] BUY {shares} shares at ${entry_price:.4f}")

    def _handle_exits(self, current_price, ts, matrix):
        to_remove = []
        for i, pos in enumerate(self.positions):
            # Dynamic p_hat from matrix
            _, latest_p_hat = matrix.most_likely_next_state(bin_price(current_price))
            
            # Exit logic (simplified for script)
            exit_info = self.decision_engine.should_exit(
                entry_price=pos['entry_price'],
                entry_shares=pos['shares'],
                current_price=current_price,
                p_hat=latest_p_hat,
                days_to_expiry=30, # dummy
                sigma=0.03
            )
            
            if exit_info['exit']:
                # Slippage on sell
                exit_price = current_price - (current_price * 0.005)
                fees = (pos['shares'] * exit_price) * 0.015
                
                proceeds = (pos['shares'] * exit_price) - fees
                self.capital += proceeds
                
                pnl = proceeds - (pos['shares'] * pos['entry_price'])
                self.trades.append(pnl)
                to_remove.append(i)
                # print(f"[{ts}] SELL at ${exit_price:.4f} | PnL: ${pnl:.2f}")

        for idx in sorted(to_remove, reverse=True):
            self.positions.pop(idx)

    def get_total_value(self, current_price):
        pos_val = sum(p['shares'] * current_price for p in self.positions)
        return self.capital + pos_val

    def report(self):
        print("\n" + "="*40)
        print(" BACKTEST REPORT")
        print("="*40)
        print(f"Initial Capital: ${self.initial_capital:,.2f}")
        total_val = self.equity_curve[-1]
        print(f"Final Value:    ${total_val:,.2f}")
        print(f"Total Return:   {((total_val/self.initial_capital)-1)*100:.2f}%")
        print(f"Total Trades:   {len(self.trades)}")
        if self.trades:
            win_rate = len([t for t in self.trades if t > 0]) / len(self.trades)
            print(f"Win Rate:       {win_rate*100:.2f}%")
            print(f"Avg PnL:        ${np.mean(self.trades):.2f}")
        print("="*40)

def generate_mock_data(n=500):
    """Generate mock price data for testing."""
    np.random.seed(42)
    prices = [0.5]
    for _ in range(n-1):
        prices.append(np.clip(prices[-1] + np.random.normal(0, 0.02), 0.01, 0.99))
    
    df = pd.DataFrame({
        'timestamp': [datetime.now() - timedelta(minutes=5*i) for i in range(n)][::-1],
        'price': prices,
        'volume': np.random.uniform(1000, 5000, n)
    })
    return df

if __name__ == "__main__":
    from datetime import timedelta
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--csv", help="Path to historical data")
    parser.add_argument("--mock", action="store_true", help="Generate mock data")
    args = parser.parse_args()
    
    engine = BacktestEngine(args.config)
    
    if args.mock:
        data = generate_mock_data()
    elif args.csv:
        data = pd.read_csv(args.csv)
    else:
        print("Please provide --csv or --mock")
        sys.exit(1)
        
    engine.run(data)
    engine.report()
