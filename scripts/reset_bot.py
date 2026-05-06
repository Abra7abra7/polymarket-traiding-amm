import json
import os
from pathlib import Path

def reset_bot():
    checkpoint_path = Path(os.path.expanduser("~/.trading_bot/checkpoint.json"))
    paper_positions = Path(os.path.expanduser("~/.trading_bot/paper_positions.json"))
    paper_trades = Path(os.path.expanduser("~/.trading_bot/paper_trades.json"))
    trade_history = Path(os.path.expanduser("~/.trading_bot/trade_history.json"))
    
    if not checkpoint_path.exists():
        print("[!] No checkpoint found to reset.")
        return

    try:
        # 1. Load current state
        with open(checkpoint_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 2. Reset everything EXCEPT matrices
        print(f"[*] Preserving {len(data.get('matrices', {}))} learned matrices...")
        
        new_data = {
            "timestamp": data.get("timestamp"),
            "positions": {},  # Clear open positions
            "portfolio_value": 5000.0,  # Reset capital
            "stats": {
                "trades_entered": 0,
                "trades_settled": 0,
                "total_pnl": 0.0,
                "start_time": data.get("stats", {}).get("start_time")
            },
            "daily_trades_count": 0,
            "last_trade_date": "",
            "matrices": data.get("matrices", {}) # KEEP THE KNOWLEDGE
        }
        
        # 3. Save clean checkpoint
        with open(checkpoint_path, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, indent=2)
        
        # 4. Wipe paper trading engine files
        if paper_positions.exists():
            paper_positions.unlink()
        if paper_trades.exists():
            paper_trades.unlink()
        if trade_history.exists():
            trade_history.unlink()
            
        print("\n" + "="*50)
        print(" SUCCESS: BOT RESET COMPLETED")
        print("   - Capital reset to $5,000.00")
        print("   - Trade history wiped")
        print("   - Open positions closed")
        print("   - Markov matrices PRESERVED")
        print("="*50 + "\n")
        
    except Exception as e:
        print(f"[!] Error during reset: {e}")

if __name__ == "__main__":
    reset_bot()
