# Polymarket AMM Markov Trading Bot – Strategy & Operations Report

**Version:** 1.0 (AMM Γamma Integration)  
**Date:** 2026-04-23  
**Repository:** `github.com/Abra7abra7/polymarket-traiding-amm`  
**Branch:** `master`  
**Commit:** `08e5537` (config: initial_balance $50k)  

---

## 1. Executive Summary

Tento dokument opisuje **architektúru, strategickú logiku a prevádzku** bota pre obchodovanie na Polymarket pomocou **AMM (Automated Market Maker)** a **Markovovských reťazcov**.

Bot aktuálne beží v **paper trading režime** s **$50,000 simulačného kapitálu** a obchoduje binárne predikčné trhy (YES/NO) na kryptomeny **BTC, ETH a HYPE** v **5-minútovom timeframe**.

---

## 2. Architektúra Systému

```
┌─────────────────────────────────────────────────────────────┐
│                   TradingBot (__main__.py)                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Event Loop (každých ~60 sekúnd)                      │  │
│  │  1. check_exits() – Bellman optimal stopping          │  │
│  │  2. evaluate_one() pre každé asset+window             │  │
│  │  3. Ulož checkpoint (každých 60s)                      │  │
│  │  4. Metrics (Prometheus) + Health (HTTP)               │  │
│  └─────────────────────────┬─────────────────────────────┘  │
│                            │                                 │
│      ┌─────────────────────▼─────────────┐                  │
│      │   PaperTradingEngine (wrapper)    │                  │
│      │   - Simuluje spread, slippage     │                  │
│      │   - Sleduje pozície a P&L         │                  │
│      │   - get_balance() → $50,000       │                  │
│      └─────────────────────┬─────────────┘                  │
│                            │                                 │
│      ┌─────────────────────▼─────────────────┐              │
│      │  PolymarketAMMClient (Γamma API)      │              │
│      │  - get_ticker(asset, window) → float  │              │
│      │  - get_markets() → 1000 trhov         │              │
│      │  - submit_order() – stub (live)       │              │
│      └───────────────────────────────────────┘              │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  DecisionEngine + MarkovMatrix (per asset:window)    │  │
│  │  - should_enter(price, equilibrium, τ)               │  │
│  │  - should_exit(Bellman value)                        │  │
│  │  - kelly_fraction(p_hat, price)                      │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Dátový priebuh

```
Γamma API (https://gamma-api.polymarket.com/markets?limit=1000)
         │
         ▼
   AMMClient.connect()
         │
         ├─ Stiahne 1000 trhov (JSON)
         ├─ Zkonštruuje _market_by_condition_id mapu
         └─ Načíta condition_id z config.yaml (BTC, ETH, HYPE)
         │
         ▼
   Každý evaluation cyklus (60s):
   1. get_ticker("BTC","5m") → lastTradePrice (0.495)
   2. MarkovMatrix.update(0.495) → state 49 (discretizácia)
   3. Vypočíta stationary distribution π z P
   4. equilibrium = Σ π[i] * bin_center[i]
   5. Porovná |price - equilibrium| s τ
   6. Ak signál → PaperTradingEngine.buy() (simulácia)
   7. Zapíše metrics, checkpoint
```

---

## 3. Markov Strategia – Teória

### 3.1 Discretizácia ceny

Cena v [0.01, 0.99] sa delí do **100 binov** (stavov):
```
State 0   = [0.00, 0.01)   → bin center = 0.005
State 1   = [0.01, 0.02)   → bin center = 0.015
...
State 99  = [0.99, 1.00]   → bin center = 0.995
```
Mapovanie: `state_index = floor(price * n_states)`

### 3.2 Transition Matrix P

`P` je `n_states × n_states` matica, kde:
```
P[i][j] = P( cena_t+1 je v bin_j | cena_t je v bin_i )
```
- Buffer posledných `window_size` cien (5m = 5 tickov za minútu? Actually 5-minúta candlesticks; aktuálne použité `window_size=5` z configu)
- Pre každý pár (from_state, to_state) incrementuj `counts[from][to]`
- Normalizuj: `P[i][j] = counts[i][j] / Σ_j counts[i][j]`

### 3.3 Stationary Distribution π

π je ľavý vlastný vektor P (λ=1):
```
π = π · P,   Σ π[i] = 1
```
Vytvorí sa pomocou `numpy.linalg.eig(P.T)` a extrakcie eigenvektora pre eigenvalue ~1.

**Equilibrium price:**
```
E = Σ_i π[i] · bin_center[i]
```
Toto je dlhodobo očakávaná cena (stavová rovnováha).

### 3.4 Entry Condition (Mean-Reversion)

```
diff = | current_price - equilibrium |
if diff ≥ τ  AND  diagonal_mean(P) ≥ 0.87:
    → LONG (buy YES)
```
- `τ` (tau) – threshold z `config/trading/thresholds/tau` (aktuálne 0.05 = 5%)
- `diagonal_mean` – priemer diagonálnych prvkov P[i][i]; väčšia hodnota = trh sidewayuje (stabilný)

### 3.5 Exit Condition (Bellman Optimal Stopping)

Pre každú otvorenú pozíciu:
```
V(s) = max( sell_now, γ · Σ_j P[s][j] · V(j) )
```
kde:
- `sell_now = current_price` (v paper trading bez spread; v live by bolo `current_price - spread`)
- `γ = 0.95` (discount factor)
- `V(j)` Predictive value v novej stave j

Ak `V(current_state) ≤ sell_now` → **SELL** (optimal exit).

### 3.6 Position Sizing – Kelly Criterion

```
f* = (p_hat - (1 - p_hat)/r)    (ak p_hat > 1/(1+r))
```
kde:
- `p_hat` = max(π[i] pre stavy v okolí aktuálnej ceny) – odhad pravdepodobnosti rastu
- `r` = risk-reward ratio (v binárnom trhu: (1-price)/price)

USD notional:
```
size = min( portfolio_value * f*, max_position_usd )
```

---

## 4. AMM Γamma API Integrácia

### 4.1Endpointy

| Endpoint | Purpose |
|----------|---------|
| `GET /markets?limit=1000` | Fetch all active markets (includes conditionId, clobTokenIds, outcomePrices, lastTradePrice, question, slug) |
| (future) `/pools` | Get AMM pool reserves for price impact |

### 4.2 Market Mapping

V `config.yaml` defineujeme pre každý asset:

```yaml
BTC:
  condition_id: '0xbb57ccf5853a85487bc3d83d04d669310d28c6c810758953b9d9b91d1aee89f2'
  token_id: '105267568073659068217311993901927962476298440625043565106676088842803600775810'
```

Načítanie:
1. `AMMClient.connect()` fetches 1000 markets
2. `_load_asset_maps_from_config()` načíta condition_id z configu do `_condition_id_by_asset`
3. `_build_market_maps()` vytvára `condition_id → full_market` lookup

### 4.3 get_ticker(asset, window)

```python
async def get_ticker(self, asset: str, window: str) -> float:
    cid = self._condition_id_by_asset[asset]
    market = self._market_by_condition_id[cid]
    last_price = market.get('lastTradePrice')
    if last_price is None:
        prices = json.loads(market['outcomePrices'])   # [YES, NO]
        last_price = float(prices[0])                  # YES probability
    return round(float(last_price), 4)
```

---

## 5. Paper Trading Engine

### 5.1 Simulation Parameters

```yaml
paper_trading:
  initial_balance: 50000.0
  spread_bps: 200          # 2% simulated spread
  slippage_bps: 50         # size-based slippage
  fill_latency_ms: 200     # artificial delay
  partial_fill_prob: 0.1   # 10% chance partial/none
```

### 5.2 Buy Simulation

```
fill_price = price + (price * spread_bps/20000) + slippage(size)
shares = size_usd / fill_price
position = SimulatedPosition(asset, entry_price=fill_price, shares, entry_time=now)
```

### 5.3 Sell Simulation

```
fill_price = price - (price * spread_bps/20000) - slippage
P&L = (fill_price - entry_price) * shares
balance += P&L
```

### 5.4 State Persistence

- **Positions** stored in `~/.trading_bot/paper_positions.json`
- **Trade log** appended to `~/.trading_bot/paper_trades.json`
- **Checkpoint** (full matrix + positions) saved every 60s to `~/.trading_bot/checkpoint.json`

---

## 6. Konfigurácia (config/config.yaml)

```yaml
app:
  name: polymarket-amm-bot
  version: 1.0.0
  dry_run: false
  paper_trading: true           # ← currently TRUE (simulation)

exchange:
  platform: polymarket
  amm:
    base_url: https://gamma-api.polymarket.com
    router_address: '0x0000000000000000000000000000000000000000'  # TBD
    gas_limit: 300000
    gas_price_gwei: 2
  auth:
    wallet_address: ${POLYMARKET_WALLET_ADDRESS}
    private_key: ${POLYMARKET_PRIVATE_KEY}

trading:
  assets:
    BTC:
      condition_id: '0xbb57ccf5853a85487bc3d83d04d669310d28c6c810758953b9d9b91d1aee89f2'
      token_id: '105267568073659068217311993901927962476298440625043565106676088842803600775810'
      windows: ['5m']
      enabled: true
      max_position_usd: 1000.0
    ETH:
      condition_id: '0xfc6260666d020a912a87d9000eff5116d2adfb8c30aba543427a4c1f1411f1a0'
      token_id: '57301498276970257025109591078431189727442302532145853906375186182281603517458'
      windows: ['5m']
      enabled: true
      max_position_usd: 1000.0
    HYPE:
      condition_id: '0xfa88bedd0403281fac1b3c8b310755040aabed8ba12ded1b2e3205a3d05a4a28'
      token_id: '101513571766435454355723114188696307527864518980689079866102837918467349506537'
      windows: ['5m']
      enabled: true
      max_position_usd: 1000.0
    SOL: {enabled: false}
  matrix:
    n_states: 100
    smoothing_alpha: 0.3
    min_transitions: 30
  thresholds:
    tau: 0.05
    epsilon: 0.01

risk:
  max_open_positions: 5
  max_daily_trades: 100
  max_drawdown: 0.2
  max_position_size_usd: 5000
  max_total_exposure_usd: 15000
  kill_switches:
    daily_loss_limit_usd: 5000

storage:
  redis:
    host: localhost
    port: 6379
  checkpoint:
    enabled: true
    interval_minutes: 60

monitoring:
  metrics:
    enabled: true
    port: 9091
  health:
    enabled: true
    port: 8087

paper_trading:
  initial_balance: 50000.0      # ← CURRENT
  spread_bps: 200
  slippage_bps: 50
  fill_latency_ms: 200
  partial_fill_prob: 0.1
  data_dir: ~/.trading_bot
```

---

## 7. Current Operational Status (2026-04-23 19:45)

| Položka | Hodnota |
|---------|---------|
| **Režim** | Paper Trading (simulácia) |
| **Počiatočný kapitál** | $50,000.00 |
| **Aktívne aktíva** | BTC:5m, ETH:5m, HYPE:5m |
| **Γamma API** | ✅ Pripojené, 1000 trhov načítaných |
| **Metrics endpoint** | `http://localhost:9091/metrics` |
| **Health endpoint** | `http://localhost:8087/health/ready` |
| **Checkpoint** | `~/.trading_bot/checkpoint.json` každých 60s |
| **Matrix valid?** | ❌ (potreba ≥30 prechodov; aktuálne ~4–5) |
| **Otvorené pozície** | 0 |
| **Portfolio value** | $50,000.00 |

### Procesy

```
PID 262896 – python -m polymarket_bot (paper mode)
PID 262903 – monitor_24h.py (zapisuje portfolio každých 10s)
```

### Log snippet (posledné minúty)

```
[EVAL] Loop iteration start
[EXIT] Checking exits for open positions...
[EVAL] Running gather for 3 tasks
[EVAL] start BTC:5m   → matrix transitions 49→49 (buffer=4/30)
[EVAL] start ETH:5m   → matrix transitions 28→28 (buffer=4/30)
[EVAL] start HYPE:5m  → matrix transitions 31→31 (buffer=4/30)
[EVAL] Gather completed, results count=3
[EVAL] Metrics updated
[EVAL] About to sleep/wait (sleep_time=59.95)
```

**Záver:** Matrix ešte nie je validná (menej ako 30 prechodov). Bot momentálne **zbiera dáta**; prvý obchod sa spustí, keď matrix dosiahne `min_transitions=30` a trh prekročí `tau=0.05`.

---

## 8. Očakávaný Prybeh Po 24 Hodínách

| Čas od štartu | Stav matrix | Pravdepodobnosť obchodu |
|---------------|-------------|------------------------|
| 0–10 min      | buffer 4–10 | veľmi nízka |
| 10–20 min     | buffer 10–20| stále nízka |
| 20–30 min     | buffer 20–30| ak matrix_valid → čaká na diff ≥ τ |
| 30–60 min     | buffer ≥30 | 🎯 Mohlo by nastať prvé vstupné podmienky |
| 1–6 h         | Náhodné výskyty | 0–5 obchodov za hodinu |
| 6–24 h        | Plné cykly | 10–50 obchodov celkom |

**Portfolio zmena:** V paper mode P&L je len simulačný; reálne obchody by generovali on-chain transakcie.

---

## 9. Monitoring & Metriky

### 9.1 Prometheus Metrics (localhost:9091/metrics)

```
trading_bot_portfolio_value_usd 50000.0
trading_bot_open_positions_count 0.0
trading_bot_matrix_valid{asset="BTC",window="5m"} 0.0
trading_bot_trades_total 0.0
trading_bot_paper_pnl_usd 0.0
```

### 9.2 Health Endpoint

```bash
curl http://localhost:8087/health/ready
# → {"status":"ok"}
```

### 9.3 Log Sledovanie

```bash
tail -f /root/live_bot_24h.log
# Hľadaj: [EVAL], [EXIT], Trade entered, Order filled, Checkpoint saved
```

### 9.4 24h CSV Záznam

Súbor `~/portfolio_24h.csv` (každých 10 sekúnd):
```csv
timestamp,portfolio_value,open_positions,matrix_valid_count,metrics_ok
2026-04-23T19:35:00Z,50000.0,0,0,true
2026-04-23T19:35:10Z,50000.0,0,0,true
...
```

---

## 10. Riziká & Obmedzenia

| Riziko | Popis |
|--------|-------|
| **Orderbook neaktívny** | CLOB endpoint vracia 404; trhy nie sú live na orderbook |
| **Binárne trhy – expirácia** | Každý trh expiruje po 5 minútach (5m okno) |
| **Sparse matrix** | n_states=100, window=5 → veľa nulových prechodov |
| **Nízka volatilita** | Ak cena v úzkej škale, `|diff| < τ` → žiadne obchody |
| **Paper vs Live discrepancy** | Simulácia nezahráva on-chain gas, fill probability sa líši |

---

## 11. Next Steps (Pre Live Trading)

1. Overiť CLOB orderbook status (čakáme na 200)
2. Implementovať `submit_order` v `amm_client.py` (on-chain swap)
3. Test live s `max_position_usd: 10` po 10 minútach
4. Pridať Telegram notifikácie na entry/exit
5. Pridať multi-window fusion (5m + 1h + 6h)

---

## 12. FAQ

**Q: Prečo matrix_valid=0?**  
A: Potrebných 30 validných prechodov. Počas prvých 20 minút bufferotočí pomaly (ceny každú minútu). Čakajte.

**Q: Kedy bot nakupuje?**  
A: Keď (1) matrix ≥30 prechodov, (2) |cena - equilibrium| ≥ 0.05, (3) diagonal stability ≥ 0.87.

**Q: Ako zmeniť počet obchodov?**  
A: Znížte `tau` (0.03 alebo 0.02) alebo znížte `min_transitions` (napr. 10).

**Q: Je možné obchodovať na live?**  
A: Áno, nastavte `paper_trading: false` v config.yaml a spustite znova. Vyžaduje KYC, USDC balance a orderbook live.

**Q: Ako sledujem P&L?**  
A: Metrics `trading_bot_portfolio_value_usd` alebo `paper_pnl_usd` v Prometheus; checkpoint ukladá históriu.

---

**Report generated:** 2026-04-23  
**Bot version:** 1.0.0 (AMM)  
**Git commit:** `08e5537` (master)  

---

## 13. Technical Reference – Key Source Files

| Súbor | Účel |
|-------|------|
| `polymarket_bot/__main__.py` | Hlavný event loop, checkpoint, metrics, orchestration |
| `polymarket_bot/exchange/amm_client.py` | Γamma API integration, get_ticker, submit_order stub |
| `polymarket_bot/paper_trading.py` | Simulačný engine (spread, slippage, state) |
| `polymarket_bot/core/matrix.py` | Markov TransitionMatrix (update, build, to_dict) |
| `polymarket_bot/core/decision.py` | Entry/exit logika (should_enter, should_exit, kelly) |
| `polymarket_bot/config/loader.py` | YAML config načítanie + validácia |
| `config/config.yaml` | Trading parameters, assets, thresholds |
| `~/.trading_bot/checkpoint.json` | Persistent state (matrices, positions) |

---

*End of Report*
