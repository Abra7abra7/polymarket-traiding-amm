# Coolify Deployment Guide — Polymarket Trading Bot

Follow these steps to ensure a stable and profitable deployment on your VPS via Coolify.

## 1. Project Configuration
- **Build Pack:** Dockerfile
- **Ports Mapping:** 
  - `8089:8089` (Health/API)
  - `9093:9093` (Metrics)

## 2. Environment Variables
You MUST set these variables in the Coolify "Environment Variables" section:
- `POLYMARKET_WALLET_ADDRESS`: Your Polygon wallet address.
- `POLYMARKET_PRIVATE_KEY`: Your wallet's private key.
- `POLYMARKET_BUILDER_CODE`: (Optional) Your V2 builder code.
- `TELEGRAM_BOT_TOKEN`: (Optional) For health alerts.
- `TELEGRAM_CHAT_ID`: (Optional) For health alerts.

## 3. Persistent Storage (CRITICAL)
Without persistent storage, the bot will lose its Markov matrices on every update/restart.
- Go to **Storage** tab in Coolify.
- Add a new **Volume**.
- **Source:** `trading-bot-data` (or any name).
- **Destination:** `/root/.trading_bot`
- **Type:** Persistent Volume.

## 4. Health Check
To prevent unnecessary restarts, configure the Coolify health check as follows:
- **Type:** HTTP
- **Port:** `8089`
- **Path:** `/health/ready`
- **Interval:** `30s`
- **Timeout:** `5s`
- **Retries:** `5`
- **Start Period (Grace Period):** `60s` (Important to allow the bot to connect to Polymarket).

## 5. Monitoring
Once deployed, you can check the status:
1. **Logs:** Look for `[MATRIX] TRANSITION` to confirm the bot is learning.
2. **Dashboard:** Open the container terminal and run:
   ```bash
   python scripts/report.py
   ```
3. **Metrics:** If you use Prometheus/Grafana, point them to `http://<your-vps-ip>:9093`.
