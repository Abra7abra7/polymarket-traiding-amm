#!/usr/bin/env python3
"""
Trading Bot Event Monitor — watches for notable events and maintains an event log.
Run this in background or via cron every 5 minutes.
"""

import subprocess
import json
import time
from pathlib import Path

STATE_FILE = Path("/opt/trading_bot/reports/monitor_state.json")
EVENT_LOG = Path("/opt/trading_bot/reports/events.log")

# Persistent state across runs
if STATE_FILE.exists():
    with open(STATE_FILE) as f:
        state = json.load(f)
else:
    state = {
        "last_trades": 0,
        "last_positions": 0,
        "last_portfolio": 50000.0,
        "last_matrix_valid": False,
        "last_matrix_transitions": 0,
    }

def read_metric(port, metric_name):
    try:
        import requests
        r = requests.get(f"http://localhost:{port}/metrics", timeout=5)
        for line in r.text.split('\n'):
            if line.startswith(metric_name):
                return float(line.split()[1])
    except:
        pass
    return None

def get_recent_logs(minutes=5):
    result = subprocess.run(
        ["journalctl", "-u", "polymarket-bot", "--since", f"{minutes} min ago", "--no-pager"],
        capture_output=True, text=True
    )
    return result.stdout

def log_event(event_type, message):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    entry = f"[{ts}] [{event_type}] {message}"
    with open(EVENT_LOG, "a") as f:
        f.write(entry + "\n")
    print(entry)

def check_matrix_progress():
    logs = get_recent_logs(2)
    lines = [l for l in logs.split('\n') if '[MATRIX]' in l]
    if not lines:
        return None, None
    last = lines[-1]
    import re
    m = re.search(r'buffer=(\d+)', last)
    if m:
        transitions = int(m.group(1))
        is_valid = 'BUILD COMPLETE' in last
        return transitions, is_valid
    return None, None

def main():
    events = []

    # 1. Portfolio & trades
    portfolio = read_metric(9090, 'trading_bot_portfolio_value_usd')
    trades = int(read_metric(9090, 'trading_bot_trades_total') or 0)
    positions = int(read_metric(9090, 'trading_bot_open_positions_count') or 0)

    if portfolio is not None and portfolio != state["last_portfolio"]:
        diff = portfolio - state["last_portfolio"]
        events.append(f"Portfolio change: ${state['last_portfolio']:.2f} → ${portfolio:.2f}  (Δ${diff:+.2f})")
        state["last_portfolio"] = portfolio

    if trades > state["last_trades"]:
        new_trades = trades - state["last_trades"]
        events.append(f"🚨 TRADE{'S' if new_trades>1 else ''} EXECUTED!  Total trades: {trades}  (+{new_trades})")
        state["last_trades"] = trades

    if positions != state["last_positions"]:
        events.append(f"Position count change: {state['last_positions']} → {positions}")
        state["last_positions"] = positions

    # 2. Matrix progress
    transitions, is_valid = check_matrix_progress()
    if transitions is not None:
        if transitions > state["last_matrix_transitions"]:
            state["last_matrix_transitions"] = transitions
            if transitions >= 30 and not state["last_matrix_valid"]:
                events.append(f"✅ Markov matrix is now VALID (transitions={transitions}≥30)")
                state["last_matrix_valid"] = True
            elif transitions < 30:
                pct = transitions / 30 * 100
                events.append(f"Matrix progress: {transitions}/30 transitions ({pct:.0f}%)")

    # 3. Errors
    logs = get_recent_logs(5)
    error_lines = [l for l in logs.split('\n') if '"level":"error"' in l or 'ERROR' in l]
    for el in error_lines[-3:]:
        events.append(f"ERROR in logs: {el[:120]}")

    # 4. Service health
    svc = subprocess.run(["systemctl", "is-active", "polymarket-bot"], capture_output=True, text=True)
    if "active" not in svc.stdout:
        events.append(f"⚠️ Service status: {svc.stdout.strip()}")

    # Save state
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

    # Output & notify
    if events:
        ts = time.strftime('%H:%M:%S')
        print(f"[{ts}] Detected {len(events)} event(s):")
        for e in events:
            log_event("EVENT", e)
            # Attempt Telegram notification (fire-and-forget)
            try:
                subprocess.run(
                    ["/opt/trading_bot/scripts/telegram_notify.py", f"⚠️ Trading Bot: {e}"],
                    capture_output=True, timeout=10
                )
            except Exception as ne:
                print(f"Notify error: {ne}")
    else:
        print(f"[{time.strftime('%H:%M:%S')}] No new events.")

if __name__ == "__main__":
    main()
