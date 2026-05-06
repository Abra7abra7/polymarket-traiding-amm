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

## 🚀 5. Deployment & Verifikácia

Pred ostrým nasadením na Hetzner odporúčam tento postup:

1.  **Unit Testy**: Spusti `pytest`. Všetkých 29 testov musí prejsť.
2.  **Backtest (Simulácia)**: Spusti `python scripts/backtest.py --mock`. Overíš tým, že rozhodovacia logika (Bellman + Kelly) funguje správne na náhodných dátach.
3.  **Paper Trading**: V `config.yaml` nastav `paper_trading: true`. Bot bude simulovať obchody bez rizika reálnych peňazí.
4.  **Monitoring**: Sleduj `python scripts/report.py` pre reálny stav portfólia a P/L.

### Bezpečnostné prvky (Safety First):
- **Half-Kelly (0.5)**: Bot nikdy neriskuje celý kapitál na jeden obchod.
- **Bellman Cost-Aware**: Bot nepredá pozíciu, ak očakávaný zisk nepokryje poplatky (1.5% AMM + gas).
- **Daily Reset**: Počítadlo obchodov sa resetuje každý deň, aby bot nezostal "visieť" na limite.

**Varovanie:** Aktuálne nastavenie používa 16 trhových okien (BTC a ETH, všetky timeframy). Pred ostrým štartom na 1D/1W/1M/1Y rámcoch je potrebné aktualizovať `condition_id` v konfigurácii.
