# AGENTS.md — Project Guide for Autonomous Agents

**Project:** Polymarket Markov Trading Bot  
**Repo:** `github.com/<user>/polymarket-bot` (replace with actual URL)  
**Purpose:** Predictions-market trading bot using Markov chains and multi-window fusion.

---



---

## 🧪 Testing Strategy (Paper Trading — $100)

**Objective:** Validate API connectivity, matrix updates, and simulated order flow risk-free.

### Phase 1 — API Sanity Check
```bash
# Ensure .env is loaded
python scripts/test_polymarket_api.py
```
Expected: Wallet address resolved; API base URLs respond (200). If `Invalid token id` appears, check `.env` keys.

### Phase 2 — Dry Run (5 minutes)
```bash
# Start bot with paper_trading=true
python -m polymarket_bot
```
Observe:
- No `Order rejected` errors (orders are mock-simulated)
- Matrices count corresponds to enabled asset/window pairs in `config.yaml`
- Health endpoint returns `{"status":"ok"}` on port 8089
- Metrics available at `http://localhost:9093/metrics`
- Checkpoint written to `~/.trading_bot/checkpoint.json` after first cycle

### Phase 3 — Metrics Validation
```bash
curl http://localhost:9093/metrics | grep -E 'portfolio_value|open_positions|trades'
```
- `portfolio_value` should reflect `initial_capital_usd` (100.00) + any unrealized P&L
- `open_positions` starts at 0
- `trades` increments on each simulated fill

### Phase 4 — Extended Run (1 hour)
Let bot complete ≥10 evaluation cycles. Then:
```bash
curl http://localhost:8089/health/ready
```
Should return `{"status":"ok"}`. Inspect logs for errors. If stable, proceed to live deployment prep.

**Stop:** `kill <pid>` or send SIGTERM — bot checkpoint before exit.

---

## 📊 Current Deployment Status (2026-05-04)

### Active Markets (BTC & ETH — Multi-timeframe)

| Asset | Windows | Condition ID (V2) | Market |
|-------|---------|-------------------|--------|
| BTC | 5m, 15m, 1h, 4h | `0xe718f96...` | Will Bitcoin go up? |
| ETH | 5m, 15m, 1h, 4h | `0x6e8fd54...` | Will Ethereum go up? |

- **Timeframes active**: Multi-window fusion enabled for 5m, 15m, 1h, and 4h horizons.
- **CLOB V2 status**: Fully migrated and operational on Polymarket's V2 contracts.
### Pipeline Status
- ✅ Config: BTC and ETH mapped across 4 timeframes each
- ✅ Auth: V2 SDK + EIP-712 signing + L2 credentials working
- ✅ Client: Standardized `@property connected` interface across all clients
- ✅ Token mapping: pUSD collateral integration complete
- ✅ Orderbook: Operational on V2 endpoints
- ✅ Ticker: Live feed processing into Markov matrices
- ✅ Matrix: Transitions and Bellman values computing correctly
- ✅ Paper trading: Fully synchronized with live prices and simulated execution
- ✅ Live orders: Blocked only by `dry_run: true` setting or optional geofencing

### Next Steps
1. **Optimize Tau** — Current `tau: 0.05` is calibrated for low-volatility paper runs; monitor and adjust for live market spikes.
2. **Expand Assets** — Enable SOL, HYPE, and XRP once V2 liquidity stabilizes for those markets.
3. **Short-selling** — Currently config uses YES tokens; implement NO side flipping for full market coverage.
---


## 🚀 Going Live (Real Money)

**WARNING:** Only after Phase 4 passes and API keys are verified.

1. Set `app.paper_trading: false` in `config/config.yaml`.
2. Ensure wallet has sufficient USDC balance on Polymarket.
3. Restart bot — it will now POST real orders via `PolymarketLiveClient`.
4. Monitor alerts (Telegram configured via `monitoring.alerts.telegram`).

## 📁 Directory Structure

```
polymarket_bot/
├── __main__.py            # Main orchestration, event loop, checkpointing
├── config/
│   └── config.yaml        # All parameters (assets, thresholds, risk limits)
├── core/
│   ├── decision.py        # Entry/exit logic, tau/eps thresholds
│   ├── matrix.py          # MarkovMatrix: update, compute Bellman value
│   ├── fusion.py          # Multi-window signal combination
│   ├── risk_manager.py    # Portfolio-level risk (drawdown, position sizing)
│   ├── trailing_stop.py   # Trailing stop logic
│   ├── exit_manager.py    # Exit signal coordination across windows
│   ├── volume_filter.py   # Filter assets by 24h volume
│   ├── regime_detector.py # Market regime detection (trending/mean-reverting)
│   └── __init__.py
├── exchange/
│   ├── client.py          # PolymarketClient (mock + live exchange API)
│   ├── interface.py       # BaseExchangeClient abstract class
│   └── live_client.py     # Production client (Polymarket API)
├── monitoring/
│   ├── metrics.py         # Prometheus metrics exposition
│   ├── health.py          # Health check endpoints
│   └── logging.py         # Structured JSON logging setup
├── models/
│   └── state.py           # State discretization helpers
└── utils/
    └── helpers.py         # Misc utilities (yaml load, time windows)

tests/
├── conftest.py
├── test_metrics.py
├── test_health.py
├── test_adaptive_tau.py
├── test_exit_multi_window.py
├── test_regime_detector.py
├── test_risk_manager.py
├── test_trailing_stop.py
└── test_volume_filter.py

scripts/
├── daily_report.py
├── daily_report_telegram.py
└── run_daily_report.sh

config/config.yaml          # Main configuration
pyproject.toml             # Package metadata & dependencies
README.md                  # User-facing documentation
```

---

## 🔄 How It Works — End-to-End Flow

### 1. Startup (`__main__.py:main()`)
```text
- Load config (config.yaml)
- Initialize exchange client (MockClient for dry-run, LiveClient for prod)
- Create DecisionEngine with thresholds (tau, eps)
- For each asset × window (e.g. BTC:1h, ETH:5m):
    • Load or create MarkovMatrix(buffer_size=window, n_states=20)
    • Restore from checkpoint if available
    • Start async evaluation loop
- Start metrics server (Prometheus), health endpoint
- Begin main event loop: evaluate_all() every 5 minutes
```

### 2. Evaluation Cycle (`evaluate_one()` per asset+window)
```text
a) Fetch current price via client.get_ticker(market_id)
b) Update matrix: matrix.update(price)  ← adds state transition
c) If matrix.valid (transitions ≥ min_transitions):
    • Compute stationary_distribution (π)
    • Compute equilibrium_price = Σ π[i] * bin_center[i]
    • Compute Bellman value V (solve (I − γP)v = r)
    • Call decision.should_enter(price, V, equilibrium, tau)
    • If signal → PortfolioRiskManager approves size → submit order
d) Check exits: decision.should_exit() + stop-loss + trailing stop
e) Log metrics, save checkpoint every 60 seconds
```

### 3. Multi-Window Fusion (`fusion.py`)
```
Each asset has up to 3 windows (5m, 1h, 6h), each producing a signal:
  Signal = { LONG, SHORT, FLAT }
Fusion rule:
  - All 3 agree → FULL position (max_size)
  - 2/3 agree → HALF position
  - Else → no trade
Window weights: `{5m: 0.3, 1h: 0.5, 6h: 0.2}` (configurable)
```

### 4. Risk Management (`risk_manager.py`)
```
- Position size = Kelly fraction * portfolio_value * window_weight
- Absolute cap: max_position_ratio (default 10% of portfolio)
- Daily P&L tracking; if daily_drawdown_limit (2%) hit → halt for the day
- Global position exposure limit (sum of all positions ≤ 80% of portfolio)
```

### 5. Checkpointing (`__main__.py:save_checkpoint()`)
```
Every 60 seconds:
- Serialize all matrices (state, counts, transitions)
- Serialize open positions (entry price, size, timestamp)
- Write to ~/.trading_bot/checkpoint.json
- On restart: restore matrices and positions automatically
```

---

## 🎯 Key Parameters (config.yaml)

| Section | Parameter | Meaning | Default |
|---|---|---|---|
| `trading.assets` | list of `SYMBOL:WINDOW` | Assets & timeframes to trade | 8 enabled |
| `trading.markov.n_states` | int | Discretization bins (0–19) | **20** |
| `trading.markov.window_sizes` | `{5m:40, 1h:24, ...}` | Buffer length for each window | Variable |
| `trading.markov.min_transitions` | int | Min transitions for matrix validity | **20** |
| `trading.thresholds.tau` | float (0–1) | Entry threshold: \`|V − Veq| > tau\` | **0.05** |
| `trading.thresholds.eps` | float (0–1) | Exit tolerance: price near opposite outcome | **0.15** |
| `trading.risk.max_position_ratio` | float (0–1) | Max size per position | 0.05 |
| `trading.risk.daily_drawdown_limit` | float (0–1) | Stop trading after daily loss | 0.02 |
| `trading.filters.volume_filter` | float (USD) | Minimum 24h volume | 100_000 |
| `trading.regime_filter.enabled` | bool | Enable regime-aware position sizing | false |

### Why This Combo?
- **`n_states=20` + `window=60` + `min_transitions=5`**  
  Ensures every matrix row gets enough transitions (~3 avg) without excessive warm-up time. Lower `n_states` (e.g. 100) produced sparse matrices; higher `window` slows warm-up.

- **`tau=0.3`** is high because **mock data has artificially low volatility** (0.02). Lower tau would flood with false signals in simulation. On live markets with real volatility, reduce to `0.15–0.2`.

- **`eps=0.02`** tight exit: triggers when price crosses the opposite outcome threshold minus small epsilon.

- **All assets share identical thresholds** — no per-asset tuning (simplicity, avoids overfitting).

---

## 🧩 Markov Logic Deep Dive

### State Discretization (`matrix.py:discretize(price)`)
```
buffer = deque(maxlen=window_size) maintains last N prices
range = max(buffer) − min(buffer)
bin_width = range / n_states
state = floor((price − min(buffer)) / bin_width)
state = clamp(state, 0, n_states−1)
```

### Transition Counting
```
Each update:
  old_state = current_state
  new_state = discretize(new_price)
  P[old_state, new_state] += 1
  total_transitions += 1
```

### Validity Check
```
Matrix is "valid" when:
  - total_transitions ≥ min_transitions
  - Every row sums to ≈1 (after normalization)
  - No row is all zeros (handled in decision.py should_enter)
```

### Bellman Value Computation (`matrix.compute_value(gamma=0.95)`)
```
We define immediate reward r[i] = bin_center[i] (normalized 0–1)
Solve: v = r + γ · P · v   ⇒   v = (I − γP)⁻¹ r
Implemented via iterative power method: v_{k+1} = r + γ·P·v_k
Converges in ~50 iterations.

Equilibrium price (stationary) = Σ π[i] · bin_center[i]
where π is left eigenvector of P (sum(π)=1).
```

---

## 📡 Asset Definitions

### Crypto (realistic mock IDs)
| Asset | Windows | Market ID suffix | Notes |
|---|---|---|---|
| BTC | 5m, 1h, 6h | `BTC_5M`, `BTC_1H`, `BTC_6H` | Base volatility 0.05 |
| ETH | 5m, 1h, 6h | `ETH_5M`, … | Base vol 0.05 |
| TAO | 5m, 1h, 6h | `TAO_5M`, … | Added 2026-04-22 |
| HYPERLIQUID | 5m, 1h, 6h | `HL_5M`, … | Added 2026-04-22 |

### Weather (18 EU cities × 4 metrics, only 1h window)
| City | Code | Metrics | Example market ID |
|---|---|---|---|
| London | LON | RAIN, SUN, WIND, STORM | `LON_RAIN_1H` |
| Vienna | VIE | … | `VIE_RAIN_1H` |
| Prague | PRG | … | `PRG_RAIN_1H` |
| Rome | ROM | … | `ROM_RAIN_1H` |
| Madrid | MAD | … | `MAD_RAIN_1H` |
| Amsterdam | AMS | … | `AMS_RAIN_1H` |
| Brussels | BRU | … | `BRU_RAIN_1H` |
| Stockholm | STO | … | `STO_RAIN_1H` |
| Oslo | OSL | … | `OSL_RAIN_1H` |
| Copenhagen | CPH | … | `CPH_RAIN_1H` |
| Helsinki | HEL | … | `HEL_RAIN_1H` |
| Warsaw | WAW | … | `WAW_RAIN_1H` |
| Budapest | BUD | … | `BUD_RAIN_1H` |
| Athens | ATH | … | `ATH_RAIN_1H` |
| Lisbon | LIS | … | `LIS_RAIN_1H` |
| Dublin | DUB | … | `DUB_RAIN_1H` |
| Paris | PAR | … | `PAR_RAIN_1H` |
| Berlin | BER | … | `BER_RAIN_1H` |

> Weather assets have `base_volume = 150_000` and `volatility = 0.02` (low).

---

## 🛠️ Code Map — Who Does What

| File | Responsibility |
|---|---|
| `__main__.py` | Orchestration: init, main loop, checkpoint, signal handling |
| `core/decision.py` | Entry/exit threshold checks (`should_enter`, `should_exit`) |
| `core/matrix.py` | Markov matrix: update, normalization, Bellman value, equilibrium |
| `core/fusion.py` | Multi-window voting logic (combines signals per asset) |
| `core/risk_manager.py` | Position sizing, drawdown halting, portfolio limits |
| `core/trailing_stop.py` | Dynamic exit: follows price, locks profit |
| `core/exit_manager.py` | Coordinates all exit conditions (signal, stop-loss, trailing) |
| `core/volume_filter.py` | Pre-trade volume check (skip if < threshold) |
| `core/regime_detector.py` | Classifies market regime; adjusts position sizing |
| `exchange/client.py` | `PolymarketClient`: mock markets + price generation; `get_ticker`, `buy`, `sell` |
| `exchange/interface.py` | `BaseExchangeClient` abstract methods |
| `exchange/live_client.py` | Real Polymarket API client (production) |
| `monitoring/metrics.py` | Prometheus metrics (trades, P&L, positions, errors) |
| `monitoring/health.py` | `/health` endpoint for Kubernetes/uptime checks |
| `monitoring/logging.py` | JSON logger setup, structured fields |
| `utils/helpers.py` | YAML loader, time window alignment helpers |

---

## 🐛 Debugging & Observability

### Logs
```bash
journalctl -u polymarket-bot.service -f          # Follow live
journalctl -u polymarket-bot.service --since "10:00" --until "11:00"
```

**Important log prefixes:**
- `[MATRIX] TRANSITION` → matrix updates; shows `from→to buffer=X min=Y`
- `[DECISION]` → entry/exit checks (`value=..., eq=..., tau=...`)
- `[EXEC]` → order placed (`SIDE size price asset`)
- `[EXIT]` → exit reason (`EXIT_REASON=...`)
- `[CHECKPOINT]` → saved/restored counts
- `[ERROR]` / `[WARNING]` → issues

### Metrics (Prometheus)
Exposed on `http://localhost:9093/metrics` (or configured port):
```
polymarket_positions_active{asset="BTC:1h"} 1
polymarket_matrix_transitions_total{asset="ETH:5m"} 127
polymarket_trades_total{side="long",outcome="YES"} 5
polymarket_portfolio_value_usd 51234.56
polymarket_daily_pnl 123.45
polymarket_entry_signals_total 12
polymarket_exit_signals_total 11
```

### Health Check
`GET /health` returns:
```json
{
  "status": "healthy",
  "active_positions": 3,
  "matrix_count": 8,
  "uptime_seconds": 5432
}
```

### Checkpoint File
`~/.trading_bot/checkpoint.json`:
```json
{
  "timestamp": "2026-04-22T13:52:16Z",
  "positions": { ... },
  "matrices": { "BTC:5m": { "state": 4, "transitions": 127, ... }, ... }
}
```
On startup, bot restores matrices and reopens positions.

---

## 🧪 Testing

All tests live in `tests/`. Run locally:
```bash
pytest -v tests/
pytest -k test_adaptive_tau
```

Key test modules:
- `test_metrics.py` — metrics aggregation
- `test_health.py` — health endpoint responses
- `test_adaptive_tau.py` — dynamic threshold adjustment
- `test_exit_multi_window.py` — fusion logic
- `test_risk_manager.py` — position sizing, drawdown halt
- `test_trailing_stop.py` — trailing stop arithmetic
- `test_volume_filter.py` — volume thresholding
- `test_regime_detector.py` — trend/mean-revert classification

---

## 🚀 Deployment

### Systemd Service
`/etc/systemd/system/polymarket-bot.service`:
```
[Unit]
Description=Polymarket Markov Trading Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/trading_bot
Environment="PYTHONPATH=/opt/trading_bot"
ExecStart=/opt/trading_bot/.venv/bin/python -m polymarket_bot
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Environment
```
DRY_RUN=true            # false for live trading
POLYMARKET_PRIVATE_KEY=… # required for live
POLYMARKET_API_KEY=…    # required for live
LOG_LEVEL=INFO
PROMETHEUS_PORT=9093
```

### Config Reload
No dynamic reload yet — edit `config/config.yaml` and restart:
```bash
systemctl restart polymmarket-bot.service
```

---

## 🔧 Common Tasks for Agents

### **Add a new asset**
1. Edit `config/config.yaml`: append to `trading.assets` list (symbol + windows).
2. If asset is not standard crypto, add mock entry in `exchange/client.py::_mock_markets` with appropriate `window` suffix.
3. Ensure `symbol` matches filter logic (volume check uses `base_volume`).
4. Restart service.

### **Change thresholds**
Edit `config/config.yaml` → `trading.thresholds`: adjust `tau` (entry sensitivity) and `eps` (exit margin).  
Lower `tau` → more trades (riskier). Higher `tau` → fewer, stronger signals.

### **Warm-up acceleration**
Reduce `min_transitions` (e.g., 3) or increase `window_size` (e.g., 120).  
Trade-off: smaller `min_transitions` reduces matrix quality; larger `window` delays first trade.

### **Inspect why an asset isn't trading**
```bash
journalctl -u polymarket-bot.service | grep ASSET_ID
```
Look for:
- `[MATRIX]` — transition count; if buffer < min_transitions → still warming up.
- `[DECISION]` — shows `value`, `eq`, `tau`; if `|diff| < tau` → threshold not met.
- `[EXEC]` — order execution; if absent → risk manager rejected (position limit, daily drawdown).

### **Force-reset checkpoint** (e.g., after config changes requiring clean slate)
```bash
systemctl stop polymarket-bot
rm -f ~/.trading_bot/checkpoint.json
systemctl start polymarket-bot
```
Bot rebuilds matrices from scratch with new config.

---

## 📈 Performance Notes

- Each `evaluate_one()` call: fetch price (mock: instant), update matrix, compute value — avg < 10ms.
- Full cycle for 82 assets × 3 windows ≈ 246 evaluations per 5 minutes → negligible CPU.
- Main bottlenecks: exchange API latency (live), Prometheus scrape interval.
- Memory: Each matrix (20×20 float64) ≈ 3.2 KB × 246 windows ≈ 0.8 MB total.

---

## ❓ FAQ

**Q: Why do we use Markov chains for prediction markets?**  
A: Binary outcomes (YES/NO) map naturally to a two-state Markov chain. The transition probabilities capture short-term price momentum; stationary distribution gives long-term equilibrium. Deviation from equilibrium signals mispricing.

**Q: Why multi-window?**  
A: Short windows (5m) capture micro-moves; long windows (6h) capture trend. Consensus across windows reduces false signals.

**Q: Why is tau so high (0.3)?**  
A: In dry-run with mock data (volatility 0.02), price changes are tiny; low tau would trigger constantly. On live markets with real volatility (~0.05–0.1), lower tau (0.15–0.2) is appropriate.

**Q: When will the first trade happen?**  
A: After each matrix accumulates `min_transitions` (5) transitions AND `|value − equilibrium| > tau`. With window=60 and 5-minute updates, warm-up is ~12 iterations (~1 hour) for 5m/1h windows; 6h window takes ~72 minutes. Crypto assets usually go valid first (higher volatility).

**Q: Can I run multiple bot instances?**  
A: No — they would share the same checkpoint and portfolio, causing race conditions. Use separate configs + checkpoints + API keys.

---

## 📚 References

- Markov chain basics: https://en.wikipedia.org/wiki/Markov_chain
- Bellman equation: https://en.wikipedia.org/wiki/Bellman_equation
- Kelly criterion: https://en.wikipedia.org/wiki/Kelly_criterion

---

*Last updated: 2026-04-22 (commit f446739)*


---

## 📝 Paper Trading Mode

Pre testovanie stratégie na reálnych cenách bez rizika použite **paper trading**.

### Konfigurácia

```yaml
app:
  dry_run: false          # must be false to use live data
  paper_trading: true     # ← enable paper mode

paper_trading:
  spread_bps: 200         # simulated bid/ask spread (2 %)
  slippage_bps: 50        # extra slippage for larger sizes (0.5 %)
  fill_latency_ms: 200    # artificial delay before fill (200 ms)
  partial_fill_prob: 0.1  # 10 % chance order is not filled
  data_dir: ~/.trading_bot # where paper_positions.json is stored
```

### Ako funguje

1. **`PaperTradingEngine`** obaluje `LiveClient`:
   - `get_ticker()`, `get_markets()`, `get_volume_24h()` → volá sa priamo na Polymarket API (reálne dáta).
   - `buy()` / `sell()` → **nie** skutočné objednávky; namiesto toho sa:
     - Použije `spread_bps` (cena purchaser dostane o spread horšia).
     - Pridá `slippage_bps` podľa veľkosti pozície.
     - Simuluje `fill_latency_ms` (naraz‑ofline, ale logicky).
     - S pravdepodobnosťou `1 - partial_fill_prob` sa order **nevyplní**.
   - Výsledok (fill price, quantity) sa zapíše do `paper_positions.json` a `paper_trades.json`.

2. **Mark‑to‑market**: Po každej iterácii `evaluate_one()` volá `client.update_market_prices()` a aktualizuje `current_pnl` pre otvorené pozície.

3. **Portfólio**: Simulovaný cash balance (`current_balance`) sa mení pri entries/exits. Na exit sa vypočíta P&L a pripočíta.

4. **Metriky** (exponované na `/metrics`):
   ```
   trading_bot_paper_trades_total{asset, side, type}
   trading_bot_paper_pnl_usd
   trading_bot_paper_unrealized_pnl_usd
   trading_bot_paper_positions_count
   trading_bot_paper_fill_rate
   ```

### Porovnanie mock vs. paper

| Metrika | Mock (dry‑run) | Paper (real‑time data) |
|---|---|---|
| Cena | GBM simulácia (hladká) | Skutočný last price z API |
| Spread | Žiadny | Simulovaný (200 bps default) |
| Slippage | Žiadny | Simulovaný (50 bps + size) |
| Fill guarantee | 100 % | 90 % (default) |
| Latency | 0 ms | 200 ms simulovaná |
| Objem | Fixný `base_volume` | Skutočný `volume24h` (filter pracuje) |
| výsledok P&L | Optimistický | Reálnejší (bez rizika) |

### Workflow pre testovanie

```bash
# 1. Nastav paper mode v config.yaml
app:
  dry_run: false
  paper_trading: true

# 2. Spusti bot (je stále systemctl)
sudo systemctl restart polymarket-bot.service

# 3. Sleduj logy – uvidíš [PAPER] messages
journalctl -u polymarket-bot.service -f

# 4. Skontroluj pozície
cat ~/.trading_bot/paper_positions.json | jq .

# 5. Metriky
curl http://localhost:9092/metrics | grep paper_
```

### Prechod na live trading

Ako si overíš, že stratégia prežije reálny trh:

1. **Paper trading 1–2 týždne** – zaznamenaj `paper_pnl_usd` a `paper_fill_rate`.  
   Ak je P&L záporný, skontroluj:
   - `tau` príliš vysoké? → veľa signálov, ale malé výnosy?
   - `spread_bps` nastavený príliš nízko? → realný spread je vyšší.

2. **Porovnaj mock vs. paper** – ak mock dáva +5 % mesačne a paper −2 %, problém je v **simulácii** (presne spread/slippage) alebo v **parametrom tau** (príliš nízké pre live).

3. **Live s minimálnou pozíciou** – až budeš spokojný, prepni `paper_trading: false` a nastav `max_position_ratio: 0.01` (1 % portfólia) na prvý týždeň.

---

## 🧪 Backtesting & Analytics

### Scripts
```bash
# Daily P&L report (generuje PDF/Markdown)
./scripts/daily_report.sh

# Telegram alert (ak je nakonfigurovaný)
./scripts/daily_report_telegram.sh
```

### Log analysis
```bash
# Number of entries per asset
journalctl -u polymarket-bot.service | grep "\[DECISION\]" | grep "ENTRY" | wc -l

# Exit reasons
journalctl -u polymarket-bot.service | grep "EXIT_" | sort | uniq -c
```

### Checkpoint inspection
```bash
python -c "import json; d=json.load(open('/root/.trading_bot/checkpoint.json')); print(d.keys())"
```

---

## 🐛 Debugging Common Issues

| Problem | Check | Fix |
|---|---|---|
| Bot nezačína | Look for `[RUN] Bot initializing` in logs | Ensure config path correct, API keys set if not dry-run |
| `Abstract class` error | `Can't instantiate abstract class PolymarketClient` | Ensure `get_volume_24h()` implemented in chosen client (already fixed) |
| Matrix never valid | `[MATRIX] TRANSITION` count stagnant | Increase `window_size` or decrease `min_transitions` |
| Too many trades, low P&L | `[DECISION]` shows many entries with small diff | Increase `tau` or decrease position sizing |
| No fills in paper mode | `[PAPER] BUY not filled` frequent | Increase `partial_fill_prob`? Actually decrease it (currently 0.1 means 10% not filled – adjust to market) |
| Spread too high | P&L negative even on winning signals | Lower `paper_trading.spread_bps` to match real market spread |
| API rate limits | `429 Too Many Requests` in logs | Increase `trading.interval_seconds` or add exponential back‑off |

---

## 📚 Architecture Decisions

- **Why Markov chains?**  
  Short‑term price momentum in binary markets is well‑captured by a 2‑state Markov process. Long‑term equilibrium gives a fair price reference.

- **Why multi‑window?**  
  Reduces false positives: a true signal should appear across multiple time horizons.

- **Why paper trading wrapper instead of separate client?**  
  Re‑uses live API connection; only execution path is simulated. No code duplication.

- **Why store paper trades separately?**  
  Allows side‑by‑side comparison with live trades when you eventually switch.

- **Why not use Kelly directly?**  
  Kelly fraction is capped by `max_position_ratio` to avoid over‑concentration; also adjusted by regime detector (not enabled by default).

---

*Last updated: 2026-05-04 (commit CLOB-V2-STABLE)*
