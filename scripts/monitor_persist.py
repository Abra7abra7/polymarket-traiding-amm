#!/usr/bin/env python3
"""
AMM Bot Persist Monitor — upozorní, keď Markov matrix dosiahne threshold tau.
Monitors journalctl for DECISION log lines and checks if persist >= tau.
Run via cron every minute.
"""

import subprocess
import re
import sys
import os
from datetime import datetime

SERVICE = "polymarket-bot.service"
THRESHOLD_CHECK = r"\[DECISION\] persist=([\d.]+).*tau=([\d.]+)"


def get_recent_decisions(minutes=2):
    """Get last DECISION log entries from journalctl."""
    result = subprocess.run(
        ["journalctl", "-u", SERVICE, "--since", f"{minutes} min ago", "--no-pager"],
        capture_output=True, text=True, timeout=10
    )
    return result.stdout.splitlines()


def extract_persist_tau(line):
    """Extract persist and tau values from a DECISION log line."""
    m = re.search(THRESHOLD_CHECK, line)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def send_alert(persist, tau):
    """Send alert via Hermes send_message to home chat."""
    msg = (
        f"🚨 AMM BOT — PERSIST THRESHOLD REACHED\n\n"
        f"▸ persist = {persist:.4f}\n"
        f"▸ tau     = {tau:.4f}\n"
        f"▸ Stav    = persist ≥ tau ✅\n\n"
        f"Bot môže generovať entry signály. Ďalšie podmienky (gap, p̂) tiesň sledovať v logoch."
    )
    # Use Hermes send_message tool via subprocess (cron context)
    # The cron job delivers to 'origin' automatically, so we just print and let cron capture
    print(msg)
    # Also write to a persistent flag file so we don't spam
    flag_path = "/opt/trading_bot_amm/reports/persist_threshold_met.flag"
    with open(flag_path, "w") as f:
        f.write(f"{datetime.utcnow().isoformat()} persist={persist:.4f} tau={tau:.4f}\n")


def main():
    lines = get_recent_decisions(3)
    if not lines:
        print("No DECISION logs found in last 3 minutes.")
        sys.exit(0)

    # Find latest DECISION line
    for line in reversed(lines):
        persist, tau = extract_persist_tau(line)
        if persist is not None:
            print(f"Latest DECISION: persist={persist:.4f}, tau={tau:.4f}")
            if persist >= tau:
                flag_path = "/opt/trading_bot_amm/reports/persist_threshold_met.flag"
                try:
                    with open(flag_path) as f:
                        last = f.read().strip()
                except FileNotFoundError:
                    last = ""
                if not last or float(last.split()[1].split('=')[1]) < persist:
                    send_alert(persist, tau)
                else:
                    print("Threshold already met — alert already sent (flag file exists).")
            else:
                # Clear flag if no longer meeting threshold
                flag_path = "/opt/trading_bot_amm/reports/persist_threshold_met.flag"
                try:
                    os.remove(flag_path)
                    print(" persist < tau — threshold flag cleared.")
                except FileNotFoundError:
                    pass
                print(f"Waiting... persist {persist:.4f} < tau {tau:.4f}")
            break
    else:
        print("No DECISION log line with persist/tau found.")


if __name__ == "__main__":
    main()
