# 📈 Polymarket Markov Trading Bot

> Production-ready quantitative trading bot using Markov Chain transition matrices for Polymarket prediction markets.

## Table of Contents

1. [Concept](#1-concept)
2. [Installation](#2-installation)
3. [Configuration](#3-configuration)
4. [Running](#4-running)
5. [Monitoring](#5-monitoring)
6. [Docker Deployment](#6-docker-deployment)
7. [Systemd Service](#7-systemd-service)
8. [Mathematical Background](#8-mathematical-background)

---

## 1. Concept

The bot implements a **Markov Chain transition matrix** strategy based on the research paper *"Transition Matrix and Quantitative Trading"*.

### Core Mechanics

| Step | Description |
|------|-------------|
| **State Binning** | Continuous price → discrete state (0–N) |
| **Matrix Update** | P(i→j) counts updated via sliding window |
| **Smoothing** | Exponential smoothing α = 0.3 |
| **Entry Check** | Diagonal τ ≥ 0.87 **AND** arbitrage gap ε ≥ 0.05 |
| **Position Sizing** | Kelly Criterion: f\* = p̂ − (1−p̂)/b (cap 80%, floor 5%) |
| **Exit** | Not implemented - model assumes mean reversion exit |

### Example State Transition

```
State 0 (low price) → State 1 (higher) → ... → State N (high price)

Diagonal persistence τ = P(i→i) = 0.93  ✓
Arbitrage gap ε = p̂ − β = 0.07        ✓
→ ENTRY SIGNAL
```

---

## 2. Installation

### Prerequisites

```bash
# Root access on Hetzner server
python3 --version  # ≥ 3.9
pip --version
```

### Quick Install

```bash
cd /opt/trading_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Dependencies

Key packages:
- `numpy` — matrix operations
- `yaml` / `pydantic` — config validation
- `structlog` — structured logging
- `prometheus-client` — metrics export
- `aiohttp` — health server & exchange API
- `eth-account` — wallet signing (future)
- `websockets` — real-time market data

Full list: `requirements.txt`

---

## 3. Configuration

### Config File Structure

```yaml
# config/config.yaml  (copy from config.example.yaml)

app:
  dry_run: true           # Paper trading first! MAXIMUM SAFETY
  environment: production

exchange:
  platform: polymarket
  api:
    base_url: https://api.polymarket.com
    ws_url: wss://api.polymarket.com/market/v1

trading:
  assets:
    BTC:
      symbol: BTC
      market_id: "0x1234..."   # Polymarket market contract
      windows: ["5m", "1h"]    # Time windows to evaluate
      enabled: true
    ETH:
      symbol: ETH
      market_id: "0x5678..."
      windows: ["5m"]
      enabled: true
  thresholds:
    tau: 0.87    # Diagonal persistence threshold
    eps: 0.05    # Arbitrage gap threshold
  position:
    method: kelly
    kelly:
      cap_max: 0.80
      cap_min: 0.05

risk:
  max_open_positions: 5
  max_daily_trades: 100
  max_position_size_usd: 10000

storage:
  redis:
    host: localhost
    port: 6379
  postgres:
    host: localhost
    port: 5432
```

### Validate Config

```bash
python -c "from polymarket_bot.config.loader import load_config; load_config()"
```

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `POLYMARKET_PRIVATE_KEY` | Wallet private key for live trading |
| `POSTGRES_PASSWORD` | Database password |

---

## 4. Running

### Dry-Run (Paper Trading)

```bash
# From project root
python -m polymarket_bot --config config/config.yaml --dry-run
```

Output: JSON lines with evaluation decisions.

### Live Trading (EXTREME CAUTION)

```bash
python -m polymarket_bot --config config/config.yaml --no-dry-run
```

⚠️ **Only run live when you have:**
- Tested ≥ 1 week in dry-run mode
- Verified matrix math with historical data
- Set `risk.max_position_size_usd` to conservative values

### Command-Line Options

```
--config PATH        Config file path
--dry-run            Enable paper trading (default)
--no-dry-run         Disable → LIVE TRADING
--log-level LEVEL    Override config log level (DEBUG|INFO|WARNING|ERROR)
```

---

## 5. Monitoring

The bot exposes 2 monitoring ports by default:

| Endpoint | Purpose |
|----------|---------|
| `http://localhost:9090/metrics` | Prometheus metrics |
| `http://localhost:8080/health/live` | Liveness probe |
| `http://localhost:8080/health/ready` | Readiness probe |

### Prometheus Metrics

| Metric | Labels | Description |
|--------|--------|-------------|
| `trading_bot_portfolio_value_usd` | — | Current portfolio value |
| `trading_bot_open_positions_count` | — | Number of open positions |
| `trading_bot_trades_total` | asset, window, outcome | Trade entries |
| `trading_bot_p_hat` | asset, window | Estimated probability |
| `trading_bot_persistence` | asset, window | Diagonal τ value |
| `trading_bot_errors_total` | error_type | Error count by type |

### Logging

All logs are JSON-structured: `~/.trading_bot/logs/bot-YYYY-MM-DD.log`

Log levels (configurable):
- `DEBUG` — Full matrix telemetry
- `INFO` — Trades, evaluations, portfolio updates
- `WARNING` — Threshold misses, connection issues
- `ERROR` — Placement failures, crashes

---

## 6. Docker Deployment

```bash
docker build -t polymarket-markov-bot .
docker run -v $(pwd)/config:/app/config \
           -v $(pwd)/logs:/app/logs \
           -e POLYMARKET_PRIVATE_KEY=... \
           polymarket-markov-bot
```

Dockerfile template (create separately):
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-m", "polymarket_bot", "--dry-run"]
```

---

## 7. Systemd Service

Create a production service:

`/etc/systemd/system/polymarket-bot.service`

```ini
[Unit]
Description=Polymarket Markov Trading Bot
After=network-online.target redis.service postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/trading_bot
Environment="PYTHONPATH=/opt/trading_bot"
Environment="POLYMARKET_PRIVATE_KEY=${POLYMARKET_PRIVATE_KEY}"
ExecStart=/opt/trading_bot/.venv/bin/python -m polymarket_bot --config /opt/trading_bot/config/config.yaml
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=polymarket-bot

# Security
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/trading_bot/logs /opt/trading_bot/config

[Install]
WantedBy=multi-user.target
```

Enable & start:

```bash
systemctl daemon-reload
systemctl enable --now polymarket-bot
systemctl status polymarket-bot
journalctl -u polymarket-bot -f
```

---

## 8. Mathematical Background

### Transition Matrix

Let `P ∈ ℝ^{N×N}` where `P[i][j]` = probability of transitioning from state `i` → `j`.

State bins: `n_states = 100`, equally spaced from `min_price` to `max_price`.

### Diagonal Persistence `τ`

```
τ = (1/N) · Σᵢ P[i][i]
```

High `τ` indicates mean-reverting regime (desired).

### Arbitrage Gap `ε`

```
p̂ = row_state[future_state]  # Transition prob to UP state
β  = 1 − implied_probability  # Market odds
ε  = p̂ − β                   # Our edge
```

When `ε ≥ 0.05` and `τ ≥ 0.87` → trade.

### Kelly Fraction `f*`

```
b = payoff_odds  # e.g., YES @ 0.60 → b = (1−0.6)/0.6 = 0.667
p = p̂           # Our estimated probability
f* = p − (1-p)/b
Capped 5–80%
```

### Matrix Update (Sliding Window)

```python
window = deque(maxlen=window_size)   # Last N price ticks
if persistent:
    P = α·P_smoothed + (1−α)·P_raw
```

### Parameters

From research paper:

- `N STATES` = 100
- `α SMOOTHING` = 0.3
- `τ_ENTRY` = 0.87
- `ε_MIN` = 0.05
- `KELLY_CAP` = 0.80

---

## File Structure

```
polymarket_bot/
├── __main__.py          # Main orchestrator
├── config/
│   ├── loader.py        # YAML loader + Pydantic validation
│   └── config.example.yaml
├── core/
│   ├── matrix.py        # TransitionMatrix class
│   └── decision.py      # Kelly + threshold checks
├── exchange/
│   └── client.py        # Polymarket API wrapper
├── monitoring/
│   ├── logging.py       # structlog setup
│   ├── metrics.py       # Prometheus exporter
│   └── health.py        # HTTP health server
└── wiki/                # Karpathy-style knowledge base
```

---

## FAQ

### Q: Can I use this with other prediction markets?
A: Yes — change `exchange.base_url`, `market_id`, and adapt `client.py` for API differences.

### Q: How do I backtest?
A: Set `backtest.enabled: true` and point `backtest.data_source` to CSV OHLCV.

### Q: What happens during network outage?
A: Bot stops evaluation, logs warning, retries with backoff.

### Q: Does it short-sell?
A: No — only long YES positions.

---

**⚠️ DISCLAIMER**: This is experimental software. Use at your own risk. Not financial advice.
