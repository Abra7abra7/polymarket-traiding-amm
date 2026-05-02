#!/usr/bin/env python3
"""
Health check script for live bot — run via cron every 5 minutes.
Returns non-zero if bot is unhealthy (triggers alert).
"""
import os, sys, json, time
from pathlib import Path

CHECKPOINT = Path("/root/.trading_bot/checkpoint.json")
SERVICE = "polymarket-bot.service"
MAX_UNAVAILABLE = 3  # consecutive failures before alert

def check_service():
    """Check systemd service is active."""
    import subprocess
    r = subprocess.run(["systemctl", "is-active", "--quiet", SERVICE])
    return r.returncode == 0

def check_checkpoint_fresh():
    """Checkpoint modified in last 2 minutes?"""
    if not CHECKPOINT.exists():
        return False
    age = time.time() - CHECKPOINT.stat().st_mtime
    return age < 120  # 2 minutes

def check_drawdown():
    """Portfolio value below 90% of initial?"""
    if not CHECKPOINT.exists():
        return False
    data = json.loads(CHECKPOINT.read_text())
    initial = data.get("portfolio_value_initial", 300)
    current = data.get("portfolio_value", 300)
    return current < initial * 0.90

def main():
    failures = []
    
    if not check_service():
        failures.append("service not active")
    if not check_checkpoint_fresh():
        failures.append("checkpoint stale")
    if check_drawdown():
        failures.append("drawdown >10%")
    
    if failures:
        print(f"❌ Health check FAILED: {'; '.join(failures)}")
        # Send Telegram alert if token available
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat = os.environ.get("TELEGRAM_CHAT_ID")
        if token and chat:
            import urllib.request, urllib.parse, json
            msg = "🚨 *BOT HEALTH CHECK FAILED*\n"
            msg += f"Issues: {'; '.join(failures)}\n"
            msg += f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            payload = {
                "chat_id": chat,
                "text": msg,
                "parse_mode": "Markdown"
            }
            try:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                data = urllib.parse.urlencode(payload).encode()
                urllib.request.urlopen(url, data=data, timeout=10)
            except:
                pass
        sys.exit(1)
    else:
        print(f"✅ Bot healthy — {time.strftime('%H:%M:%S')}")
        sys.exit(0)

if __name__ == "__main__":
    main()
