#!/usr/bin/env python3
"""
Daily trading bot report — sends to Telegram via Hermes.
Runs every day at 08:00 CET/CEST (UTC+1/+2).
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add hermes to path
sys.path.insert(0, '/root/.hermes/hermes-agent')

CHECKPOINT = Path('/root/.trading_bot/checkpoint.json')
REPORTS_DIR = Path('/opt/trading_bot/reports/daily')
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

def load_checkpoint():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return None

def format_report(data):
    now = datetime.now(timezone.utc)
    local = now + timedelta(hours=2)  # CEST (summer) — adjust as needed
    
    lines = []
    lines.append("📈 **TRADING BOT — DAILY REPORT**")
    lines.append(f"📅 {local.strftime('%Y-%m-%d %H:%M')} (CEST)")
    lines.append("")
    
    # Portfolio
    portfolio = data.get('portfolio_value', 0)
    initial = 50000
    total_gain = portfolio - initial
    lines.append(f"💰 **Portfolio:** ${portfolio:,.2f}")
    lines.append(f"   Start capital: ${initial:,.2f}")
    lines.append(f"   Total P&L: ${total_gain:+,.2f} ({(total_gain/initial)*100:+.2f}%)")
    lines.append("")
    
    # Positions summary
    positions = data.get('positions', {})
    open_pos = {k: v for k, v in positions.items() if not v.get('closed', False)}
    closed_pos = {k: v for k, v in positions.items() if v.get('closed', False)}
    
    lines.append(f"📊 **Positions:** {len(open_pos)} open | {len(closed_pos)} closed (today)")
    lines.append("")
    
    if open_pos:
        lines.append("**🔵 OPEN POSITIONS**")
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
            lines.append(f"  • `{pid}` — {asset} ({window})")
            lines.append(f"    Entry: ${entry:.4f} | Curr: ${current:.4f}")
            lines.append(f"    P&L: ${u_pnl:+.2f} ({u_pct:+.2f}%) | Hold: {hold_h:.1f}h")
            total_unrealized += u_pnl
        lines.append(f"  *Total unrealized: ${total_unrealized:+,.2f}*")
        lines.append("")
    
    if closed_pos:
        lines.append("**✅ CLOSED POSITIONS (today)**")
        total_realized = 0
        for pid, p in sorted(closed_pos.items()):
            asset = p.get('asset', '?')
            pnl = p.get('pnl', 0)
            total_realized += pnl
            lines.append(f"  • {pid}: {asset} — ${pnl:+.2f}")
        lines.append(f"  *Total realized: ${total_realized:+,.2f}*")
        lines.append("")
    
    # Matrix health
    matrices = data.get('matrices', {})
    lines.append("**🔬 MATRIX HEALTH**")
    valid_count = sum(1 for m in matrices.values() if m.get('is_valid'))
    avg_diag = sum(m.get('diag_mean',0) for m in matrices.values()) / len(matrices) if matrices else 0
    lines.append(f"  Active: {len(matrices)} | Valid: {valid_count}")
    lines.append(f"  Avg diag: {avg_diag:.4f}")
    lines.append("")
    
    # Configured assets
    config_path = Path('/opt/trading_bot/config/config.yaml')
    if config_path.exists():
        import yaml
        config = yaml.safe_load(config_path.read_text())
        assets = config.get('trading', {}).get('assets', {})
        lines.append("**⚙️ CONFIGURED ASSETS**")
        for asset, acfg in assets.items():
            enabled = '✅' if acfg.get('enabled') else '❌'
            windows = ', '.join(acfg.get('windows', []))
            lines.append(f"  {enabled} `{asset}` — windows: {windows}")
    
    lines.append("")
    lines.append("---")
    lines.append(f"Report generated: {now.strftime('%Y-%m-%d %H:%M UTC')}")
    
    return "\n".join(lines)

def main():
    data = load_checkpoint()
    if not data:
        print("❌ No checkpoint data")
        sys.exit(1)
    
    report = format_report(data)
    
    # Save to file
    date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    report_file = REPORTS_DIR / f"report_{date_str}.txt"
    report_file.write_text(report)
    print(f"✅ Report saved to {report_file}")
    
    # Also print to stdout for cron email if configured
    print(report)
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
