import json
import os
from pathlib import Path
from datetime import datetime

def format_currency(value):
    return f"${value:,.2f}"

def generate_report():
    # Path to checkpoint
    checkpoint_path = Path(os.path.expanduser("~/.trading_bot/checkpoint.json"))
    
    if not checkpoint_path.exists():
        print(f"\n[!] Checkpoint file not found at {checkpoint_path}")
        print("    Make sure the bot has been running and saved its state.")
        return

    try:
        with open(checkpoint_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        print("\n" + "="*60)
        print(f"  POLYMARKET BOT - STATUS REPORT ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
        print("="*60)

        # 1. Portfolio Overview
        capital = data.get("portfolio_value", 0.0)
        stats = data.get("stats", {})
        initial_balance = 5000.0  # Default initial balance for paper trading
        pnl = stats.get("total_pnl", capital - initial_balance)
        pnl_pct = (pnl / initial_balance) * 100 if initial_balance > 0 else 0

        print(f"\n[PORTFOLIO OVERVIEW]")
        print(f"   Current Capital:   {format_currency(capital)}")
        print(f"   Initial Balance:   {format_currency(initial_balance)}")
        color = "\033[92m" if pnl >= 0 else "\033[91m"
        reset = "\033[0m"
        print(f"   Total P/L:         {color}{format_currency(pnl)} ({pnl_pct:+.2f}%){reset}")
        print(f"   Trades (E/S):      {stats.get('trades_entered', 0)} / {stats.get('trades_settled', 0)}")

        # 2. Open Positions
        positions = data.get("positions", {})
        print(f"\n[OPEN POSITIONS] ({len(positions)})")
        if not positions:
            print("   (No active trades)")
        else:
            print(f"   {'Asset':<15} {'Shares':<10} {'Entry':<12} {'Timestamp'}")
            print(f"   {'-'*55}")
            for pos_id, pos in positions.items():
                asset = pos.get('asset', pos_id)
                price = pos.get('entry_price', 0.0)
                shares = pos.get('shares', 0)
                time = pos.get('entry_time', 'N/A').split('T')[0]
                print(f"   {asset:<15} {shares:<10} {format_currency(price):<12} {time}")

        # 3. Model Health
        matrices = data.get("matrices", {})
        active_matrices = 0
        total_transitions = 0
        
        for m_id, m_data in matrices.items():
            # Check if matrix has some data
            data_points = m_data.get('transitions', [])
            if any(any(row) for row in data_points):
                active_matrices += 1
                # Sum all transitions in the matrix
                total_transitions += sum(sum(row) for row in data_points)

        print(f"\n[MODEL STATUS]")
        print(f"   Active Matrices:   {active_matrices} / {len(matrices)}")
        print(f"   Total Samples:     {total_transitions:,} transitions captured")
        
        print("\n" + "="*60 + "\n")

    except Exception as e:
        print(f"\n[!] Error reading report: {e}")

if __name__ == "__main__":
    generate_report()
