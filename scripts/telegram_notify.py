#!/usr/bin/env python3
"""
Send Telegram notification if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set.
Usage: /opt/trading_bot/scripts/telegram_notify.py "message text"
"""

import os
import sys
import requests

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def send(message: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set)")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        data = r.json()
        if data.get('ok'):
            return True
        else:
            print(f"Telegram API error: {data}")
            return False
    except Exception as e:
        print(f"Telegram send failed: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: telegram_notify.py <message>")
        sys.exit(1)
    msg = " ".join(sys.argv[1:])
    ok = send(msg)
    sys.exit(0 if ok else 1)
