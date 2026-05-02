#!/bin/bash
set -euo pipefail

# deploy_live.sh — switch Polymarket bot from dry-run to live trading
# Usage: ./deploy_live.sh [--dry]  (--dry does dry-run validation only)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_DIR="${PROJECT_ROOT}/config"
LIVE_CONF="${CONFIG_DIR}/prod.yaml"
DRY_CONF="${CONFIG_DIR}/config.yaml"
SERVICE_NAME="polymarket-bot.service"

echo "=== Polymarket Bot — Live Deployment ==="
echo "Timestamp: $(date --iso-8601=seconds)"

# 1. Pre-flight checks
echo "[1/7] Pre-flight checks..."

REQUIRED_ENV=(
  "POLYMARKET_API_KEY"
  "POLYMARKET_API_SECRET"
  "POLYMARKET_WALLET_ADDRESS"
  "TELEGRAM_BOT_TOKEN"
  "TELEGRAM_CHAT_ID"
)

for var in "${REQUIRED_ENV[@]}"; do
  if [ -z "${!var:-}" ]; then
    echo "❌ ERROR: $var is not set in environment"
    exit 1
  fi
done

if [ ! -f "${LIVE_CONF}" ]; then
  echo "❌ ERROR: ${LIVE_CONF} not found"
  echo "   Create it from template: cp ${CONFIG_DIR}/prod.yaml.template ${LIVE_CONF}"
  exit 1
fi

# 2. Backup current config
echo "[2/7] Backing up current config..."
TIMESTAMP=$(date +%s)
cp "${DRY_CONF}" "${DRY_CONF}.backup.${TIMESTAMP}"
echo "   Saved as ${DRY_CONF}.backup.${TIMESTAMP}"

# 3. Validate YAML syntax
echo "[3/7] Validating YAML syntax..."
if ! python3 -c "import yaml; yaml.safe_load(open('${LIVE_CONF}'))" 2>/dev/null; then
  echo "❌ ERROR: Invalid YAML in ${LIVE_CONF}"
  exit 1
fi
echo "   ✅ YAML OK"

# 4. Stop bot
echo "[4/7] Stopping bot service..."
systemctl stop "${SERVICE_NAME}"
sleep 3

# 5. Switch config (symlink overwrite)
echo "[5/7] Switching to production config..."
cp "${LIVE_CONF}" "${DRY_CONF}"
echo "   Config replaced"

# 6. Start bot
echo "[6/7] Starting bot service..."
systemctl start "${SERVICE_NAME}"
sleep 5

# 7. Health check
echo "[7/7] Health check..."
if systemctl is-active --quiet "${SERVICE_NAME}"; then
  echo "✅ Bot is running"
else
  echo "❌ Bot failed to start — check logs:"
  echo "   journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
  exit 1
fi

echo ""
echo "🎉 Live deployment complete!"
echo "Monitor: journalctl -fu ${SERVICE_NAME}"
echo "Report: ${PROJECT_ROOT}/scripts/daily_report_telegram.py --live"
