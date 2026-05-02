#!/usr/bin/env python3
"""
Daily export script for Polymarket Trading Bot.
Collects logs, metrics, and state for the preceding 24 hours.
"""

import os
import json
import csv
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPORTS_DIR = "/opt/trading_bot/reports"
METRICS_PORT = 9090

def get_yesterday_range():
    """Return (since_str, until_str) for yesterday 00:00–23:59 UTC."""
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    since = datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0, 0)
    until = datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59)
    return since.strftime("%Y-%m-%d %H:%M:%S"), until.strftime("%Y-%m-%d %H:%M:%S")

def export_logs(since: str, until: str, prefix: str):
    """Export journal logs for polymarket-bot service."""
    log_path = f"{prefix}_journal.log"
    result = subprocess.run(
        ["journalctl", "-u", "polymarket-bot", "--since", since, "--until", until, "--no-pager"],
        capture_output=True, text=True
    )
    with open(log_path, "w") as f:
        f.write(result.stdout)
    print(f"  Logs → {log_path} ({len(result.stdout.splitlines())} lines)")
    return log_path

def export_metrics(prefix: str):
    """Export current Prometheus metrics snapshot."""
    try:
        import requests
        r = requests.get(f"http://localhost:{METRICS_PORT}/metrics", timeout=5)
        metrics_path = f"{prefix}_metrics.txt"
        with open(metrics_path, "w") as f:
            f.write(r.text)
        print(f"  Metrics → {metrics_path}")
        return metrics_path
    except Exception as e:
        print(f"  Metrics unavailable: {e}")
        return None

def count_trades(log_path: str) -> int:
    if not os.path.exists(log_path):
        return 0
    with open(log_path) as f:
        return sum(1 for line in f if "Trade entered" in line)

def get_portfolio_value() -> float | None:
    try:
        import requests
        r = requests.get(f"http://localhost:{METRICS_PORT}/metrics", timeout=5)
        for line in r.text.splitlines():
            if line.startswith("trading_bot_portfolio_value_usd"):
                return float(line.split()[1])
    except:
        pass
    return None

def build_summary(trade_count: int, portfolio_end: float | None, log_lines: int) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat() + "Z",
        "period": "yesterday",
        "trades_executed": trade_count,
        "portfolio_end_usd": portfolio_end,
        "log_lines": log_lines
    }

def main():
    os.makedirs(REPORTS_DIR, exist_ok=True)
    since, until = get_yesterday_range()
    yesterday_date = (datetime.utcnow().date() - timedelta(days=1)).isoformat()

    print(f"Daily export — {yesterday_date} (logs from {since} → {until})")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prefix = os.path.join(REPORTS_DIR, f"report_{yesterday_date}_{ts}")

    # 1. Journal logs (yesterday)
    log_path = export_logs(since, until, prefix)

    # 2. Metrics snapshot (current)
    metrics_path = export_metrics(prefix)

    # 3. Summary JSON
    log_lines = 0
    if os.path.exists(log_path):
        with open(log_path) as f:
            log_lines = len(f.readlines())

    trade_count = count_trades(log_path)
    portfolio_end = get_portfolio_value()

    summary = build_summary(trade_count, portfolio_end, log_lines)
    summary_path = f"{prefix}_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Summary → {summary_path}")

    # 4. Append to daily history CSV
    csv_path = os.path.join(REPORTS_DIR, "daily_history.csv")
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "trades", "portfolio_end_usd"])
        if not file_exists:
            f.write(",".join(writer.fieldnames) + "\\n")
        writer.writerow({
            "date": yesterday_date,
            "trades": trade_count,
            "portfolio_end_usd": round(portfolio_end, 2) if portfolio_end else ""
        })
    print(f"  Appended to {csv_path}")
    print("Export complete.")

if __name__ == "__main__":
    main()
