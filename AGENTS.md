# AGENTS.md — Projektový Manifest & Technická Dokumentácia (v2.5)

**Projekt:** Polymarket Markov Trading Bot  
**Architektúra:** Modulárny Orchestrátor (Asyncio)  
**Matematické jadro:** Markovove reťazce, Bellmanove rovnice, Kellyho kritérium  
**Deployment:** Optimalizované pre Hetzner VPS (Linux/Ubuntu)

---

## 🧠 1. Ako projekt funguje (Core Logic)

Bot je postavený na predpoklade, že ceny na predikčných trhoch vykazujú určitú mieru "pamäte" a trendovosti, ktorú je možné zachytiť pomocou diskrétnych stavov.

### Matematický Aparát:
1.  **Markovove reťazce (Predikcia):**
    -   Ceny (0.0 až 1.0) rozdeľujeme do **20 binov** (diskrétne stavy).
    -   Bot udržiava **Transition Matrix (P)** pre každý pár (Asset + Timeframe).
    -   **p_hat (p̂):** Pravdepodobnosť prechodu do nasledujúceho stavu. Ak je p̂ výrazne vyššie ako aktuálna cena, vzniká nákupný signál.
2.  **Bellmanove rovnice (Optimal Exit):**
    -   Namiesto fixného Take-Profitu bot rieši problém **Optimal Stopping**.
    -   V každom kroku porovnáva okamžitý zisk z predaja (`Reward`) s očakávanou hodnotou držania pozície do ďalšieho kroku (`V(s)`).
    -   Predaj nastane v momente, keď je marginálna hodnota čakania nižšia ako istota okamžitého zisku.
3.  **Kellyho kritérium (Position Sizing):**
    -   Bot nevstupuje do pozície s fixnou sumou.
    -   Veľkosť stávky sa vypočítava ako `f = (bp - q) / b`, kde `edge` je rozdiel medzi `p_hat` a trhovou cenou.
    -   V konfigu sú nastavené limity (`cap_min`, `cap_max`), aby bot nevsadil príliš veľa pri extrémnych predpovediach.

---

## 🏗️ 2. Architektúra Systému

Kód je striktne rozdelený na logické vrstvy (Clean Architecture):

-   **`polymarket_bot/__main__.py`**: Orchestrátor. Riadi asynchrónnu slučku (`asyncio`), spracováva signály (SIGINT/SIGTERM) a koordinuje cyklus: *Fetch -> Evaluate -> Execute -> Checkpoint*.
-   **`polymarket_bot/core/decision.py`**: "Mozog" bota. Čistá matematika bez API volaní. Obsahuje logiku pre Markovove matice a Bellmanove výpočty.
-   **`polymarket_bot/core/state_manager.py`**: Zabezpečuje perzistenciu. Ukladá matice a otvorené pozície do JSON checkpointov. Pri reštarte bota sa stav okamžite obnoví.
-   **`polymarket_bot/monitoring/`**:
    -   **HealthServer (Port 8089)**: Liveness/Readiness sondy pre monitoring.
    -   **MetricsExporter (Port 9093)**: Prometheus exportér pre vizualizáciu pNL, počtu obchodov a presnosti matíc v Grafane.

---

## 🧪 3. Testovacia Stratégia (TDD)

Projekt dodržiava **100% Test Driven Development**. Žiadna funkcia nie je nasadená bez testu.

-   **Unit Testy (190+):** Overujú izolovanú logiku (normalizácia matíc, Kellyho limity, validácia konfigu).
-   **Integration Testy (20+):** Simulujú kompletný beh bota v `dry_run` móde, vrátane štartu HTTP serverov a sieťovej komunikácie.
-   **Dynamic Testing:** Testy používajú dynamickú alokáciu portov (port 0), čo eliminuje konflikty pri paralelných testoch na Windows/CI.

**Príkaz na spustenie:**
```bash
pytest -v --cov=polymarket_bot tests/
```

---

## ⚙️ 4. Čo sa dá upravovať (Konfigurácia)

Všetky dôležité parametre nájdeš v `config/config.yaml`:

### Stratégia (`thresholds`):
-   **`eps` (0.15)**: Minimálny rozdiel medzi predpoveďou a cenou pre vstup.
-   **`tau` (0.05)**: Prah stability matice. Ak je model príliš "rozlietaný", bot neobchoduje.
-   **`p_hat_entry` (0.55)**: Minimálna istota smeru pre nákup.

### Riziko (`risk`):
-   **`max_open_positions` (15)**: Limit počtu súbežných obchodov.
-   **`daily_loss_limit_usd` (1000)**: Automatický Stop-Loss pre celý deň.
-   **`max_daily_trades` (100)**: Ochrana proti "over-tradingu" v prípade šumu.

### Trhy (`trading.assets`):
-   Tu pridávaš nové ID trhov z Polymarketu. Každý asset môže mať povolené rôzne timeframy (1m, 5m, 1h, 4h).

---

## 🚀 5. Deployment na Hetzner VPS

1.  Naklonuj repo a vytvor `.env` (použi `.env.example`).
2.  Nainštaluj závislosti: `pip install -r requirements.txt`.
3.  Spusti bota cez systemd (odporúčané) alebo screen/tmux.
4.  Sleduj logy: `tail -f ~/.trading_bot/logs/bot-*.log`.

**Varovanie:** Bot je v `paper_trading: true` móde. Pred prepnutím na live trading (`dry_run: false`) sa uisti, že máš dostatočnú históriu v maticiach.
