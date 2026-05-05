import json
import os
import yaml
from pathlib import Path
from datetime import datetime

def format_currency(value):
    color = "\033[92m" if value > 0 else ("\033[91m" if value < 0 else "")
    reset = "\033[0m"
    sign = "+" if value > 0 else ("-" if value < 0 else "")
    return f"{color}{sign}${abs(value):,.2f}{reset}" if value != 0 else "$0.00"

def format_plain(value):
    return f"${value:,.2f}"

def generate_report():
    # 1. Paths
    root_dir = Path(__file__).parent.parent
    checkpoint_path = Path(os.path.expanduser("~/.trading_bot/checkpoint.json"))
    config_path = root_dir / "config" / "config.yaml"
    
    # 2. Load Config for initial balance
    initial_balance = 5000.0
    try:
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)
            initial_balance = cfg.get('paper_trading', {}).get('initial_balance', 5000.0)
    except: pass

    if not checkpoint_path.exists():
        print(f"\n[!] Checkpoint not found. Bot might not have saved state yet.")
        return

    try:
        with open(checkpoint_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        print("\n" + "="*70)
        print(f"  POLYMARKET BOT - PROFESSIONAL DASHBOARD")
        print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)

        # 1. Financial Summary
        cash = data.get("portfolio_value", 0.0) # In code, this is actually the liquid cash
        stats = data.get("stats", {})
        realized_pnl = stats.get("total_pnl", 0.0)
        
        # Calculate value of open positions (at entry price as fallback)
        positions = data.get("positions", {})
        holdings_value = 0.0
        for pos in positions.values():
            holdings_value += pos.get('shares', 0) * pos.get('entry_price', 0.0)
        
        total_equity = cash + holdings_value
        unrealized_pnl = total_equity - initial_balance - realized_pnl
        
        print(f"\n[ FINANCIAL OVERVIEW ]")
        print(f"   Initial Deposit:   {format_plain(initial_balance)}")
        print(f"   Total Equity:      {format_plain(total_equity)} (Cash + Positions)")
        print(f"   Available Cash:    {format_plain(cash)} (Liquidity)")
        print(f"   Invested Capital:  {format_plain(holdings_value)}")
        
        print(f"\n[ PERFORMANCE ]")
        total_pnl = total_equity - initial_balance
        pnl_pct = (total_pnl / initial_balance) * 100 if initial_balance > 0 else 0
        print(f"   Net Profit/Loss:   {format_currency(total_pnl)} ({pnl_pct:+.2f}%)")
        print(f"   Realized P/L:      {format_currency(realized_pnl)} (Locked in)")
        print(f"   Unrealized P/L:    {format_currency(unrealized_pnl)} (In open trades)")

        # 2. Trade Statistics
        entered = stats.get("trades_entered", 0)
        settled = stats.get("trades_settled", 0)
        # Win rate is harder without detailed history in checkpoint, 
        # but we can estimate or show counts
        print(f"\n[ TRADE STATISTICS ]")
        print(f"   Total Trades:      {entered} opened / {settled} closed")
        print(f"   Active Trades:     {len(positions)}")
        if settled > 0:
            # We don't have per-trade win/loss in stats yet, but we have total_pnl
            avg_pnl = realized_pnl / settled
            print(f"   Avg. Profit/Trade: {format_currency(avg_pnl)}")

        # 3. Open Positions Table
        print(f"\n[ ACTIVE MARKET POSITIONS ]")
        if not positions:
            print("   >>> No active positions at the moment.")
        else:
            print(f"   {'ASSET':<12} {'WINDOW':<8} {'SHARES':<10} {'ENTRY':<10} {'VALUE':<12}")
            print(f"   {'-'*55}")
            for pid, pos in positions.items():
                asset = pos.get('asset', '???')
                window = pos.get('window', '???')
                shares = pos.get('shares', 0)
                entry = pos.get('entry_price', 0.0)
                val = shares * entry
                print(f"   {asset:<12} {window:<8} {shares:<10} {format_plain(entry):<10} {format_plain(val):<12}")

        # 4. Bot Health
        print(f"\n[ SYSTEM STATUS ]")
        uptime = stats.get("start_time", "N/A")
        print(f"   Bot Started:       {uptime}")
        print(f"   Daily Trades:      {data.get('daily_trades_count', 0)}")
        
        active_m = 0
        for m in data.get("matrices", {}).values():
            if any(any(row) for row in m.get('transitions', [])):
                active_m += 1
        print(f"   Model Readiness:   {active_m} active matrices")

        print("\n" + "="*70 + "\n")

    except Exception as e:
        print(f"\n[!] Error generating dashboard: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    generate_report()
