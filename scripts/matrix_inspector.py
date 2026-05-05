import json
import os
import numpy as np
from typing import Dict

def print_heatmap(matrix, n_states=20):
    """Prints a small ASCII heatmap of the transition matrix."""
    if matrix is None or np.sum(matrix) == 0:
        print("      [ Empty Matrix ]")
        return

    chars = " .:-=+*#%@"
    print("      To State ->")
    for i in range(n_states):
        row_str = f"{i:2d} | "
        for j in range(n_states):
            val = matrix[i][j]
            char_idx = min(int(val * 10), len(chars) - 1)
            row_str += chars[char_idx] + " "
        print(row_str)
    print("      " + "-" * (n_states * 2))

def inspect_matrices(checkpoint_path: str):
    if not os.path.exists(checkpoint_path):
        print(f"❌ Checkpoint file not found at {checkpoint_path}")
        return

    try:
        with open(checkpoint_path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Error loading checkpoint: {e}")
        return

    matrices_data = data.get("matrices", {})
    if not matrices_data:
        print("⚠️ No matrices found in checkpoint.")
        return

    print("\n" + "="*80)
    print("  POLYMARKET BOT - MATRIX INSPECTOR")
    print("  Source: " + checkpoint_path)
    print("="*80)

    for market_id, m_info in matrices_data.items():
        # m_info is usually a dict with 'P', 'counts', 'total_transitions', etc.
        p_matrix = m_info.get("P")
        total = m_info.get("total_transitions", 0)
        is_valid = m_info.get("is_valid", False)
        
        status = "✅ READY" if is_valid else "⏳ TRAINING"
        
        print(f"\n[ {market_id} ] Status: {status} | Transitions: {total}")
        
        if p_matrix:
            print_heatmap(p_matrix)
        else:
            print("      No probability data yet.")

    print("\n" + "="*80)
    print("  Legend: . (Low Prob) -> @ (High Prob)")
    print("="*80 + "\n")

if __name__ == "__main__":
    # Default path for Docker/Coolify environment
    path = os.path.expanduser("~/.trading_bot/checkpoint.json")
    if not os.path.exists(path):
        # Fallback for local dev
        path = "checkpoint.json"
    
    inspect_matrices(path)
