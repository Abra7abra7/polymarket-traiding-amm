#!/usr/bin/env bash
# Trading Bot launcher — works both in venv and system-wide

set -e

PROJECT="/opt/trading_bot"
cd "$PROJECT"

# Ensure venv exists
if [ ! -d ".venv" ]; then
    echo "🔧 Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

# Arguments
CONFIG="${1:-/opt/trading_bot/config/config.yaml}"
DRY_RUN="${2:---dry-run}"
LOG_LEVEL="${3:-INFO}"

echo "🤖 Starting Polymarket Markov Bot"
echo "   Config: $CONFIG"
echo "   Mode: $DRY_RUN"
echo "   Log level: $LOG_LEVEL"
echo ""

python -m polymarket_bot \
    --config "$CONFIG" \
    $DRY_RUN \
    --log-level "$LOG_LEVEL"
