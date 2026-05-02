#!/bin/bash
# Start the trading bot for a 24h dry-run and schedule a report

export PYTHONPATH=/opt/trading_bot
cd /opt/trading_bot

# Clean up any old artifacts
rm -f /tmp/trading_bot.pid /tmp/trading_bot_24h.log
mkdir -p /opt/trading_bot/reports

# Start bot
nohup python3 -m polymarket_bot --config config/config.yaml --dry-run --log-level INFO > /tmp/trading_bot_24h.log 2>&1 &
BOT_PID=$!
echo $BOT_PID > /tmp/trading_bot.pid
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bot started PID=$BOT_PID"

# Schedule report in 24 hours (86400 seconds) — use at if available, else background sleep
if command -v at &>/dev/null; then
    echo "cd /opt/trading_bot && /root/generate_trading_report.py" | at now + 24 hours
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Report scheduled via 'at' (24h from now)"
else
    # Fallback: background sleep
    (sleep 86400 && /root/generate_trading_report.py) &
    REPORT_PID=$!
    echo $REPORT_PID > /tmp/report_scheduler.pid
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Report scheduled via background sleep (PID=$REPORT_PID)"
fi

echo ""
echo "Bot is running. Logs: tail -f /tmp/trading_bot_24h.log"
echo "Bot PID: $(cat /tmp/trading_bot.pid)"
echo ""
echo "Report will be generated and emailed in 24 hours to stancikmarian8@gmail.com"
