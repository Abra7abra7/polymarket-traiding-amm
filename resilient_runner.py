#!/usr/bin/env python3
"""Resilient 24h AMM Bot Runner — auto-recovery + health monitoring."""
import subprocess, time, os, sys, signal, json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR   = Path("/opt/trading_bot_amm")
CONFIG     = BASE_DIR / "config/config.yaml"
PID_FILE   = Path("/tmp/amm_bot_24h.pid")
LOG_FILE   = Path("/tmp/amm_bot_24h.log")
REPORT_DIR = BASE_DIR / "reports"
HEALTH_URL = "http://localhost:8089/health/ready"

MAX_RESTARTS_PER_HOUR = 5
RESTART_COOLDOWN      = 5
HEALTH_INTERVAL       = 30

def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")

def validate_env() -> bool:
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        log("❌ .env chýba")
        return False
    required = {"POLYMARKET_WALLET_ADDRESS", "POLYMARKET_PRIVATE_KEY"}
    env_vars = {}
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    missing = required - set(env_vars.keys())
    if missing or not all(env_vars.get(k) for k in required):
        log(f"❌ Chýbajúce env vars: {missing}")
        return False
    log("✅ Env valid")
    return True

def start_bot() -> subprocess.Popen | None:
    PID_FILE.unlink(missing_ok=True)
    if LOG_FILE.exists():
        LOG_FILE.rename(LOG_FILE.with_suffix(f".{int(time.time())}.log"))
    cmd = [sys.executable, "-m", "polymarket_bot", "--config", str(CONFIG), "--dry-run", "--log-level", "INFO"]
    log(f"🚀 Starting: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd, cwd=BASE_DIR,
            stdout=open(LOG_FILE, "a"),
            stderr=subprocess.STDOUT
        )
        PID_FILE.write_text(str(proc.pid))
        log(f"✅ Bot launched PID={proc.pid}")
        return proc
    except Exception as e:
        log(f"❌ Start failed: {e}")
        return None

def is_healthy() -> bool:
    try:
        import requests
        r = requests.get(HEALTH_URL, timeout=5)
        if r.status_code == 200:
            data = r.json()
            # Accept both "ok" (standard) and "ready" (our bot's implementation)
            status = data.get("status")
            return status in ["ok", "ready"] and data.get("matrices", 0) >= 1
    except Exception:
        pass
    return False

restart_times = []
def should_restart() -> bool:
    now = time.time()
    global restart_times
    restart_times = [t for t in restart_times if now - t < 3600]
    if len(restart_times) >= MAX_RESTARTS_PER_HOUR:
        log("⚠️  Rate-limit reštartov — 600s pauza")
        time.sleep(600)
        restart_times.clear()
        return True
    restart_times.append(now)
    return True

def restart_bot(proc: subprocess.Popen) -> subprocess.Popen | None:
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    log("🔄 Restarting…")
    time.sleep(RESTART_COOLDOWN)
    return start_bot()

def generate_report():
    log("📊 Generating 24h report…")
    try:
        tail_log = "\n".join(LOG_FILE.read_text().splitlines()[-100:]) if LOG_FILE.exists() else ""
        stats = {"trades": 0, "pnl": 0, "wins": 0}
        try:
            import psycopg2, os
            conn = psycopg2.connect(
                host="localhost", port=5432, database="trading_bot",
                user=os.getenv("DB_USER","postgres"), password=os.getenv("DB_PASSWORD","")
            )
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*), SUM(pnl_usd), COUNT(*) FILTER (WHERE outcome='win')
                FROM trade_history WHERE entry_time >= NOW() - INTERVAL '24 hours'
            """)
            row = cur.fetchone()
            stats = {"trades": row[0] or 0, "pnl": row[1] or 0, "wins": row[2] or 0}
            cur.close(); conn.close()
        except Exception as e:
            stats["error"] = str(e)

        rpt = f"""# 📈 AMM Bot — 24h Report
Generated: {datetime.now(timezone.utc).isoformat()}

## Summary
- Trades (24h): {stats['trades']}
- Wins: {stats['wins']}
- Total P&L: ${stats['pnl']:,.2f}
- DB error: {stats.get('error','none')}

## Recent Log (last 100 lines)
```
{tail_log}
```
"""
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        rpt_file = REPORT_DIR / f"report_24h_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        rpt_file.write_text(rpt)
        log(f"✅ Report saved: {rpt_file}")
    except Exception as e:
        log(f"❌ Report failed: {e}")

def main():
    log("="*60)
    log("🚀 Resilient 24h AMM Bot Runner started")
    log("="*60)

    if not validate_env():
        log("❌ Validation failed – exiting")
        sys.exit(1)

    proc = start_bot()
    if not proc:
        sys.exit(1)

    start_time = time.time()
    deadline   = start_time + 86400
    last_hc    = time.time()

    while time.time() < deadline:
        if time.time() - last_hc >= HEALTH_INTERVAL:
            healthy = is_healthy()
            last_hc = time.time()
            log(f"Health: {'✅' if healthy else '❌'}")

            if not healthy:
                log("⚠️  Unhealthy → restart")
                if should_restart():
                    proc = restart_bot(proc)
                continue

        if proc.poll() is not None:
            log(f"⚠️  Bot exited code={proc.poll()} → restart")
            if should_restart():
                proc = restart_bot(proc)
            else:
                time.sleep(30)
            continue

        elapsed  = int(time.time() - start_time)
        remain   = int(deadline - time.time())
        log(f"⏳ {elapsed//60}m / {remain//60}m remaining | PID {proc.pid}")
        time.sleep(30)

    log("⏰ 24h reached — shutting down")
    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=30)
        log("✅ Bot stopped")
    except Exception as e:
        log(f"⚠️  Graceful stop failed: {e} → SIGKILL")
        proc.kill()

    generate_report()
    log("🎉 Run complete")

if __name__ == "__main__":
    main()
