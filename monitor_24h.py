#!/usr/bin/env python3
"""24h trading bot monitor — collects stats after 24h runtime."""

import time
import subprocess
import sys
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import RealDictCursor
import json

PID_FILE = "/tmp/trading_bot.pid"
LOG_FILE = "/tmp/trading_bot_24h.log"

def wait_24h_and_report():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting 24h monitoring window...")
    print(f"Bot PID file: {PID_FILE}")
    print(f"Log file: {LOG_FILE}")
    print("─" * 60)

    # Wait 24 hours (86400 seconds)
    print("Waiting 24 hours (86400 seconds)..." )
    time.sleep(86400)

    print(f"\n[{datetime.now(timezone.utc).isoformat()}] 24h elapsed. Stopping bot...")

    # Send SIGINT for graceful shutdown
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        subprocess.run(["kill", "-SIGINT", str(pid)], check=True)
        print(f"Sent SIGINT to PID {pid}")
    except Exception as e:
        print(f"Error stopping bot: {e}")

    # Wait for process to exit
    time.sleep(5)

    # 1. Read last 50 lines of log
    print("\n" + "═" * 60)
    print("RECENT LOG (last 50 lines):")
    print("═" * 60)
    try:
        with open(LOG_FILE) as f:
            lines = f.readlines()
        for line in lines[-50:]:
            print(line.rstrip())
    except Exception as e:
        print(f"Could not read log: {e}")

    # 2. Query PostgreSQL statistics
    print("\n" + "═" * 60)
    print("POSTGRESQL TRADING STATISTICS (last 24h):")
    print("═" * 60)
    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="trading_bot",
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "")
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Total trades
        cur.execute("""
            SELECT COUNT(*) as total_trades,
                   SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN outcome IN ('loss', 'partial_loss') THEN 1 ELSE 0 END) as losses,
                   SUM(pnl_usd) as total_pnl
            FROM trade_history
            WHERE entry_time >= NOW() - INTERVAL '24 hours'
        """)
        row = cur.fetchone()
        print(f"  Total trades (24h) : {row['total_trades'] or 0}")
        print(f"  Wins               : {row['wins'] or 0}")
        print(f"  Losses             : {row['losses'] or 0}")
        print(f"  Total P&L (USD)    : ${row['total_pnl'] or 0:,.2f}")
        if row['total_trades']:
            winrate = (row['wins'] or 0) / row['total_trades'] * 100
            print(f"  Win rate           : {winrate:.1f}%")

        # Trades by asset
        print("\n  by asset:")
        cur.execute("""
            SELECT asset, COUNT(*) as count, SUM(pnl_usd) as pnl
            FROM trade_history
            WHERE entry_time >= NOW() - INTERVAL '24 hours'
            GROUP BY asset ORDER BY count DESC
        """)
        for r in cur.fetchall():
            print(f"    {r['asset']}: {r['count']} trades, P&L=${r['pnl'] or 0:,.2f}")

        # Current portfolio snapshot (latest)
        cur.execute("""
            SELECT portfolio_value_usd, realized_pnl_usd, unrealized_pnl_usd
            FROM portfolio_snapshots
            ORDER BY recorded_at DESC LIMIT 1
        """)
        snap = cur.fetchone()
        if snap:
            print(f"\n  Current portfolio value: ${snap['portfolio_value_usd']:,.2f}")
            print(f"  Realized P&L           : ${snap['realized_pnl_usd']:,.2f}")
            print(f"  Unrealized P&L         : ${snap['unrealized_pnl_usd']:,.2f}")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"PostgreSQL error: {e}")

    # 3. Prometheus metrics snapshot
    print("\n" + "═" * 60)
    print("PROMETHEUS METRICS (http://localhost:9090/metrics):")
    print("═" * 60)
    try:
        import requests
        r = requests.get("http://localhost:9090/metrics", timeout=5)
        if r.status_code == 200:
            # Show only relevant lines
            for line in r.text.splitlines():
                if any(k in line for k in ['trading_bot_', 'portfolio_', 'trades_', 'positions_']):
                    print(f"  {line}")
    except Exception as e:
        print(f"  Could not fetch metrics: {e}")

    print("\n" + "═" * 60)
    print("24h monitoring complete.")
    print("═" * 60)

if __name__ == "__main__":
    import os
    wait_24h_and_report()
