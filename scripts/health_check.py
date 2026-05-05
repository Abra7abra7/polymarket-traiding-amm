#!/usr/bin/env python3
"""
Health check script for Docker/Coolify environment.
Checks the internal HTTP health endpoint and checkpoint freshness.
"""
import os
import sys
import json
import time
import urllib.request
from pathlib import Path

# Config (should match config.yaml)
CHECKPOINT = Path(os.path.expanduser("~/.trading_bot/checkpoint.json"))
HEALTH_URL = "http://localhost:8089/health/ready"
SAVE_INTERVAL_MINS = 5
MAX_STALE_FACTOR = 2.5  # Allow 2.5x the interval before calling it stale

def check_http_health():
    """Check the internal HTTP health server."""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as response:
            if response.status != 200:
                return False, f"HTTP Status {response.status}"
            data = json.loads(response.read().decode())
            if data.get("status") == "ready":
                return True, "Bot is ready"
            return False, f"Bot status: {data.get('status')}"
    except Exception as e:
        return False, f"HTTP Check failed: {str(e)}"

def check_checkpoint_fresh():
    """Verify the checkpoint file is being updated."""
    if not CHECKPOINT.exists():
        return False, "Checkpoint file missing"
    
    age_seconds = time.time() - CHECKPOINT.stat().st_mtime
    max_age_seconds = SAVE_INTERVAL_MINS * 60 * MAX_STALE_FACTOR
    
    if age_seconds > max_age_seconds:
        return False, f"Checkpoint stale (age: {int(age_seconds)}s > limit: {int(max_age_seconds)}s)"
    return True, f"Checkpoint fresh (age: {int(age_seconds)}s)"

def main():
    failures = []
    
    # 1. Check HTTP Health
    ok, msg = check_http_health()
    if not ok:
        failures.append(msg)
    
    # 2. Check Checkpoint (only if not a fresh start)
    # We allow some time for the first checkpoint to be created
    if CHECKPOINT.exists():
        ok, msg = check_checkpoint_fresh()
        if not ok:
            failures.append(msg)
    
    if failures:
        print(f"❌ Health check FAILED: {'; '.join(failures)}")
        
        # Telegram Alert
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat = os.environ.get("TELEGRAM_CHAT_ID")
        if token and chat:
            try:
                msg = f"🚨 *BOT HEALTH CHECK FAILED*\nIssues: {'; '.join(failures)}\nTime: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                payload = json.dumps({"chat_id": chat, "text": msg, "parse_mode": "Markdown"}).encode()
                req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload)
                req.add_header('Content-Type', 'application/json')
                urllib.request.urlopen(req, timeout=10)
            except: pass
        sys.exit(1)
    else:
        print(f"✅ Bot healthy — {time.strftime('%H:%M:%S')}")
        sys.exit(0)

if __name__ == "__main__":
    main()
