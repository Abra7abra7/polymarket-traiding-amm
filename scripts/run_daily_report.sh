#!/bin/bash
# Daily trading bot report — 08:00 CET/CEST
# Runs via Hermes cron job (also registered in Hermes)
export TELEGRAM_BOT_TOKEN=$(grep TELEGRAM_BOT_TOKEN /root/.hermes/.env | cut -d'=' -f2)
export TELEGRAM_HOME_CHANNEL=$(grep TELEGRAM_HOME_CHANNEL /root/.hermes/.env | cut -d'=' -f2)

/root/.hermes/hermes-agent/venv/bin/python /opt/trading_bot/scripts/daily_report_telegram.py >> /opt/trading_bot/logs/daily_report.log 2>&1
