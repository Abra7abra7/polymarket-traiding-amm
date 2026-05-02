#!/usr/bin/env python3
"""
Daily trading bot report — generates report and sends via Telegram.
Runs every day at 08:00 CET/CEST via cronjob.
"""

import json
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import urllib.request
import urllib.parse
from agentmail import AgentMail  # AgentMail Python SDK

CHECKPOINT = Path('/root/.trading_bot/checkpoint.json')
REPORTS_DIR = Path('/opt/trading_bot/reports/daily')
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Telegram config from env (Hermes sets these)
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_HOME_CHANNEL = os.getenv('TELEGRAM_HOME_CHANNEL', '243422219')

def load_checkpoint():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return None

def format_report_markdown(data):
    now = datetime.now(timezone.utc)
    local = now + timedelta(hours=2)  # CEST (summer)

    lines = []
    lines.append("📈 *TRADING BOT — DAILY REPORT*")
    lines.append(f"📅 `{local.strftime('%Y-%m-%d %H:%M')}` (CEST)")
    lines.append("")

    # Portfolio
    portfolio = data.get('portfolio_value', 0)
    initial = 50000
    total_gain = portfolio - initial
    pct = (total_gain/initial)*100 if initial else 0
    lines.append(f"💰 *Portfolio:* `${portfolio:,.2f}`")
    lines.append(f"   Start: `${initial:,.2f}` | Total P&L: `{total_gain:+.2f} USD` (`{pct:+.2f}%`)")
    lines.append("")

    # Positions
    positions = data.get('positions', {})
    open_pos = {k: v for k, v in positions.items() if not v.get('closed', False)}
    closed_pos = {k: v for k, v in positions.items() if v.get('closed', False)}

    lines.append(f"📊 *Positions:* `{len(open_pos)}` open | `{len(closed_pos)}` closed (today)")
    lines.append("")

    if open_pos:
        lines.append("🔵 *OPEN POSITIONS*")
        total_unrealized = 0
        for pid, p in sorted(open_pos.items()):
            asset = p.get('asset', '?')
            window = p.get('window', '?')
            entry = p.get('entry_price', 0)
            shares = p.get('shares', 0)
            current = p.get('current_price', entry)
            u_pnl = p.get('unrealized_pnl', (current - entry) * shares)
            u_pct = p.get('unrealized_pct', ((current-entry)/entry*100) if entry else 0)
            hold_h = p.get('hold_time_seconds', 0) / 3600
            sign = '+' if u_pnl >= 0 else ''
            lines.append(f"  • `{pid}` — *{asset}* (`{window}`)")
            lines.append(f"    Entry: `${entry:.4f}` | Curr: `${current:.4f}`")
            lines.append(f"    P&L: `${sign}{u_pnl:.2f}` (`{sign}{u_pct:.2f}%`) | Hold: `{hold_h:.1f}h`")
            total_unrealized += u_pnl
        sign2 = '+' if total_unrealized >= 0 else ''
        lines.append(f"  *Total unrealized: `${sign2}{total_unrealized:.2f}`*")
        lines.append("")

    if closed_pos:
        lines.append("✅ *CLOSED POSITIONS (today)*")
        total_realized = 0
        for pid, p in sorted(closed_pos.items()):
            asset = p.get('asset', '?')
            pnl = p.get('pnl', 0)
            total_realized += pnl
            sign = '+' if pnl >= 0 else ''
            lines.append(f"  • `{pid}`: {asset} — `${sign}{pnl:.2f}`")
        sign2 = '+' if total_realized >= 0 else ''
        lines.append(f"  *Total realized: `${sign2}{total_realized:.2f}`*")
        lines.append("")

    # Matrix health
    matrices = data.get('matrices', {})
    lines.append("🔬 *MATRIX HEALTH*")
    valid_count = sum(1 for m in matrices.values() if m.get('is_valid'))
    lines.append(f"  Active: `{len(matrices)}` | Valid: `{valid_count}`")
    sorted_m = sorted(matrices.items(), key=lambda x: x[1].get('total_transitions',0), reverse=True)[:5]
    for key, m in sorted_m:
        lines.append(f"  • `{key}`: trans={m.get('total_transitions',0)} diag={m.get('diag_mean',0):.4f}")
    lines.append("")

    # Config
    config_path = Path('/opt/trading_bot/config/config.yaml')
    if config_path.exists():
        import yaml
        config = yaml.safe_load(config_path.read_text())
        assets = config.get('trading', {}).get('assets', {})
        lines.append("⚙️ *CONFIG*")
        lines.append(f"  τ={config['trading']['thresholds']['tau']} ε={config['trading']['thresholds']['eps']}")
        lines.append("  *Enabled assets:*")
        for asset, acfg in assets.items():
            if acfg.get('enabled'):
                windows = ', '.join(acfg.get('windows', []))
                lines.append(f"    • `{asset}` → {windows}")

    lines.append("")
    lines.append("---")
    lines.append(f"`Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}`")

    return "\n".join(lines)

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_HOME_CHANNEL:
        print("❌ Telegram credentials missing (TELEGRAM_BOT_TOKEN / TELEGRAM_HOME_CHANNEL)")
        return False
def send_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_HOME_CHANNEL,
        'text': text,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True
    }
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=data, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if result.get('ok'):
                print(f"✅ Telegram message sent (msg_id={result['result']['message_id']})")
                return True
            else:
                print(f"❌ Telegram error: {result}")
                return False
    except Exception as e:
        print(f"❌ Telegram send failed: {e}")
        return False


def send_email(report_md: str) -> bool:
    """Send daily report via AgentMail."""
    api_key = os.getenv('AGENTMAIL_API_KEY')
    inbox_id = os.getenv('AGENTMAIL_INBOX', 'hermes-agent-hetzner@agentmail.to')
    recipient = os.getenv('USER_EMAIL')

    if not api_key:
        print("❌ AGENTMAIL_API_KEY not set — skipping email")
        return False
    if not recipient:
        print("❌ USER_EMAIL not set — skipping email")
        return False

    try:
        client = AgentMail(api_key=api_key)
        subject = f"Trading Bot Daily Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        result = client.inboxes.messages.send(
            inbox_id=inbox_id,
            to=recipient,
            subject=subject,
            body=report_md
        )
        print(f"✅ Email sent to {recipient} via AgentMail (msg_id={getattr(result, 'messageId', 'sent')})")
        return True
    except Exception as e:
        print(f"❌ AgentMail send failed: {e}")
        return False


def main():
    data = load_checkpoint()
    if not data:
        print("❌ No checkpoint data at", CHECKPOINT)
        sys.exit(1)

    report = format_report_markdown(data)

    # Save to file
    date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    report_file = REPORTS_DIR / f"report_{date_str}.md"
    report_file.write_text(report)
    print(f"✅ Report saved: {report_file}")

    # Send to Telegram
    if send_telegram(report):
        print("✅ Daily report sent to Telegram Home")
    else:
        print("⚠️  Telegram failed — report saved locally only")

    # Send email via AgentMail
    if send_email(report):
        print("✅ Daily report sent via Email")
    else:
        print("⚠️  Email failed")

    return 0

if __name__ == '__main__':
    sys.exit(main())
