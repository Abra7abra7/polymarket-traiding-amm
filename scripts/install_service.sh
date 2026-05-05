#!/bin/bash

# Simple installer for the Polymarket Trading Bot systemd service
# Run this on your Hetzner VPS

set -e

echo "🚀 Starting Polymarket Bot Service Installer..."

# 1. Get current directory and user
WORKDIR=$(pwd)
USER=$(whoami)
PYTHON_PATH=$(which python3)

echo "[*] Detected Workdir: $WORKDIR"
echo "[*] Detected User:    $USER"
echo "[*] Detected Python:  $PYTHON_PATH"

# 2. Prepare the service file from template
TEMPLATE="deploy/trading-bot.service.template"
SERVICE_FILE="deploy/trading-bot.service"

if [ ! -f "$TEMPLATE" ]; then
    echo "[!] Error: Template $TEMPLATE not found!"
    exit 1
fi

sed "s|{{USER}}|$USER|g; s|{{WORKDIR}}|$WORKDIR|g; s|{{PYTHON_PATH}}|$PYTHON_PATH|g" "$TEMPLATE" > "$SERVICE_FILE"

# 3. Copy to systemd directory
echo "[*] Copying service file to /etc/systemd/system/ (requires sudo)..."
sudo cp "$SERVICE_FILE" /etc/systemd/system/trading-bot.service

# 4. Reload and Start
echo "[*] Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "[*] Enabling service on boot..."
sudo systemctl enable trading-bot

echo "[*] Starting service..."
sudo systemctl restart trading-bot

echo ""
echo "===================================================="
echo " ✅ INSTALLATION COMPLETE!"
echo "===================================================="
echo " To check status:   sudo systemctl status trading-bot"
echo " To stop:           sudo systemctl stop trading-bot"
echo " To see logs:       tail -f .trading_bot/logs/systemd.log"
echo "===================================================="
