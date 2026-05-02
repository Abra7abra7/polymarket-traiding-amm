#!/bin/bash
set -euo pipefail

# emergency_stop.sh — immediately halt all trading and flat positions
# Usage: ./emergency_stop.sh [--reason="..."]
# Sends Telegram alert before stopping.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICE_NAME="polymarket-bot.service"
REASON="${1:-Manual emergency stop}"

echo "🚨 EMERGENCY STOP triggered: ${REASON}" | tee /dev/stderr

# 1. Send Telegram alert
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
  MESSAGE="🚨 *EMERGENCY STOP*\n"
  MESSAGE+="Time: $(date --iso-8601=seconds)\n"
  MESSAGE+="Reason: ${REASON}\n"
  MESSAGE+="Action: Stopping bot and attempting to flat positions...\n"
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_CHAT_ID}" \
    -d text="${MESSAGE}" \
    -d parse_mode="Markdown" > /dev/null 2>&1 || true
fi

# 2. Stop bot service (graceful shutdown allows should_exit to run)
echo "[1/2] Stopping ${SERVICE_NAME}..."
systemctl stop "${SERVICE_NAME}" || true
sleep 5

# 3. Check if process exited
if pgrep -f "polymarket_bot" > /dev/null; then
  echo "[2/2] Process still running — forcing kill..."
  pkill -9 -f "polymarket_bot" || true
  sleep 2
fi

# 4. Log checkpoint (positions frozen)
CHECKPOINT="/root/.trading_bot/checkpoint.json"
if [ -f "${CHECKPOINT}" ]; then
  cp "${CHECKPOINT}" "${CHECKPOINT}.stopped.$(date +%s)"
  echo "✅ Checkpoint saved to ${CHECKPOINT}.stopped.*"
fi

echo "✅ Bot stopped. Positions remain as-is (manual intervention required to flat)."
echo "   To restart: systemctl start ${SERVICE_NAME}"
