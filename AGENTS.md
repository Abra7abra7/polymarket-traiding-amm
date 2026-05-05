# AGENTS.md — Projektový Manifest & Technická Dokumentácia (v2.6)

**Projekt:** Polymarket Markov Trading Bot  
**Architektúra:** Modulárny Orchestrátor (Asyncio)  
**Matematické jadro:** Markovove reťazce, Bellmanove rovnice, Kellyho kritérium  
**Deployment:** Optimalizované pre Hetzner VPS (Linux/Ubuntu)

---

## 🧠 1. Core Logic & Stratégia

Bot využíva kombináciu pravdepodobnostného modelovania a teórie hier:
1.  **Markovove reťazce**: Modelujú dynamiku ceny v 20 diskrétnych stavoch. Predpovedajú `p_hat` (očakávanú cenu v nasledujúcom kroku).
2.  **Bellmanove rovnice**: Riešia problém optimálneho zastavenia (Optimal Stopping). Bot nečaká na fixný zisk, ale predáva vtedy, keď očakávaná hodnota držania klesne pod hodnotu okamžitého predaja.
3.  **Kellyho kritérium**: Dynamicky určuje veľkosť pozície (štandardne cap 1% - 5% kapitálu) podľa „edge“ (rozdielu medzi predpoveďou a trhovou cenou).

---

## 🛠️ 2. Nové Nástroje (Scripts)

V priebehu optimalizácie sme pridali kľúčové nástroje pre správu bota:

-   **`scripts/report.py` (Dashboard)**:
    -   Zobrazuje **Equity** (celkový majetok), **Cash** (voľnú hotovosť), **Realized P/L** a **Unrealized P/L**.
    -   Vypočítava Win Rate a priemerný zisk na obchod.
    -   Ukazuje stav naučených matíc (Model Readiness).
-   **`scripts/reset_bot.py` (Clean Start)**:
    -   Umožňuje „tvrdý reset“ obchodnej histórie a kapitálu na $5,000.
    -   **Kľúčová vlastnosť**: Ponecháva naučené Markovove matice (pamäť bota), takže po resete nezačínaš s hlúpym botom.

---

## 📊 3. Analýza nákladov (Live Trading Ready)

V kóde sú implementované reálne trhové vplyvy (v `config.yaml` sekcia `paper_trading`):
-   **Spread (200 bps)**: Rozdiel medzi nákupom a predajom.
-   **Fees (200 bps)**: Poplatky platformy.
-   **Gas ($0.01)**: Sieťové poplatky Polygonu.

**Záver**: Bot musí dosiahnuť „edge“ aspoň 5-6% na obchod, aby bol v zisku. Pri kapitále pod **$500** začínajú fixné náklady (gas) výrazne znižovať efektivitu. Ideálna suma pre štart je **$1,000+**.

---

## 🏗️ 4. Perzistencia & Stabilita

-   **Checkpointy**: Stav sa ukladá do `~/.trading_bot/checkpoint.json` každých 60 minút.
-   **Odolnosť voči reštartom**: Po páde servera bot automaticky načíta matice a otvorené pozície a pokračuje v práci.
-   **Logovanie**: Podrobné JSON logy v `~/.trading_bot/logs/` pre neskoršiu analýzu.

---

## 🚀 5. Deployment na Hetzner

1.  Naklonuj repo a nainštaluj závislosti:
    ```bash
    git clone https://github.com/Abra7abra7/polymarket-traiding-amm.git
    cd polymarket-traiding-amm
    pip install -r requirements.txt
    ```
2.  Nastav `.env` s tvojimi kľúčmi.
3.  **Nainštaluj bota ako systémovú službu** (pre stabilitu):
    ```bash
    chmod +x scripts/install_service.sh
    ./scripts/install_service.sh
    ```
4.  Monitoruj stav:
    - `python scripts/report.py` (Zisky a obchody)
    - `sudo systemctl status trading-bot` (Stav služby)

**Varovanie:** Aktuálne nastavenie používa 16 trhových okien (BTC a ETH, všetky timeframy). Pred ostrým štartom na 1D/1W/1M/1Y rámcoch je potrebné aktualizovať `condition_id` v konfigurácii.
