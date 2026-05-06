# AGENTS.md — Projektový Manifest & Technická Dokumentácia (v3.0 - Production Ready)

**Projekt:** Polymarket Markov Trading Bot  
**Architektúra:** Resilient Orchestrator (24/7 Autonomous)  
**Matematické jadro:** Markovove reťazce, Bellmanove rovnice, Kellyho kritérium (5% Cap)  
**Deployment:** Coolify / Docker / Hetzner VPS

---

## 🧠 1. Core Logic & Stratégia

Bot využíva kombináciu pravdepodobnostného modelovania a teórie hier:
1.  **Markovove reťazce**: Modelujú dynamiku ceny v 20 diskrétnych stavoch. Predpovedajú `p_hat` (očakávanú cenu v nasledujúcom kroku).
2.  **Bellmanove rovnice**: Riešia problém optimálneho zastavenia. Bot nečaká na fixný zisk, ale predáva vtedy, keď očakávaná hodnota držania klesne pod hodnotu okamžitého predaja.
3.  **Kellyho kritérium**: Dynamicky určuje veľkosť pozície. Implementovaný **hard cap 5%** kapitálu na jeden obchod pre maximálnu bezpečnosť.

---

## 🛡️ 2. Resilient Architecture (Novinka v v3.0)

Pre zabezpečenie 24/7 prevádzky bol implementovaný `resilient_runner.py`:
-   **Auto-Recovery**: Ak proces bota spadne (napr. chyba siete), runner ho do 30 sekúnd automaticky reštartuje.
-   **Port Conflict Resolution**: 
    -   Bot implementuje **Port Fallback**. Ak sú porty 8089 (Health) alebo 9093 (Metrics) obsadené, automaticky sa posúva na ďalšie voľné (8090, 9094, atď.).
    -   Runner dynamicky detekuje aktívne porty cez `/root/.trading_bot/health_port`.
-   **Signal Handling**: Runner korektne spracováva SIGINT/SIGTERM, čo umožňuje čisté vypnutie v Docker/Coolify prostredí.

---

## ⚙️ 3. Konfigurácia & Environment

Bot je plne optimalizovaný pre Cloud-Native nasadenie:
-   **Environment Variables**: Prioritne sa využívajú systémové premenné (Coolify UI). Podporované sú:
    -   `POLYMARKET_PRIVATE_KEY` (64-znakové hex)
    -   `POLYMARKET_API_KEY` / `POLYMARKET_API_SECRET`
    -   `POLYMARKET_WALLET_ADDRESS`
-   **Dry Run Mode**: V `config.yaml` nastavený `dry_run: true` pre bezpečné testovanie na reálnych dátach bez rizika straty kapitálu.

---

## 📊 4. Monitoring & Správa

-   **`scripts/report.py`**: Profesionálny dashboard zobrazujúci Equity, P/L, Win Rate a stav Markovových matíc.
-   **`scripts/reset_bot.py`**: Resetuje históriu a kapitál na $5,000 pri **zachovaní naučených matíc** (pamäť bota zostáva).
-   **Health Probes**: Bot poskytuje `/health/ready` endpoint, ktorý sleduje:
    -   Pripojenie k burze.
    -   Stav inicializácie matíc.
    -   Počet otvorených pozícií.

---

## 🏗️ 5. Perzistencia (Volume Mapping)

V Docker prostredí je kritické mapovať volume `/root/.trading_bot`:
-   `checkpoint.json`: Ukladá stav matíc a otvorených obchodov.
-   `logs/`: JSONL logy pre audit a analýzu.
-   `health_port`: Súbor pre dynamickú komunikáciu portov medzi botom a runnerom.

---

## 🚀 6. Prevádzkové pokyny

1.  **Štart**: `python resilient_runner.py` (toto spustí bota a bude ho strážiť).
2.  **Kontrola logov**: `tail -f amm_bot_24h.log` pre sledovanie runnera.
3.  **Live Logy bota**: Logy bota v JSON formáte sú v `~/.trading_bot/logs/`.
4.  **Záloha**: Raz týždenne odporúčame zálohovať `checkpoint.json` (mozog bota).

**Bezpečnostné upozornenie:** Aktuálna verzia je vo fáze **Production-Testing**. Pred prechodom na ostrý kapitál overte stabilitu runnera aspoň po dobu 48 hodín.
