#!/usr/bin/env python3
"""Resilient 24h AMM Bot Runner — auto-recovery + health monitoring."""
import subprocess, time, os, sys, signal, json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR   = Path(__file__).parent.absolute()
CONFIG     = BASE_DIR / "config" / "config.yaml"
PID_FILE   = BASE_DIR / "amm_bot_24h.pid"
LOG_FILE   = BASE_DIR / "amm_bot_24h.log"
REPORT_DIR = BASE_DIR / "reports"
HEALTH_URL = "http://localhost:8089/health/ready"

MAX_RESTARTS_PER_HOUR = 30
RESTART_COOLDOWN      = 2
HEALTH_INTERVAL       = 30

def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except: pass

def validate_env() -> bool:
    required = {"POLYMARKET_WALLET_ADDRESS", "POLYMARKET_PRIVATE_KEY"}
    
    # Debug: Print what we see in the environment
    found_keys = [k for k in os.environ.keys() if k.startswith("POLYMARKET_")]
    log(f"Debug: Found POLYMARKET_* keys: {found_keys}")

    # 1. Check if they already exist in the environment (e.g. set by Coolify/Docker)
    env_vars = {k: os.environ.get(k) for k in required if os.environ.get(k)}
    
    # 2. If not found, try to load from .env file
    if len(env_vars) < len(required):
        # Check both project root and current working directory
        env_file = BASE_DIR / ".env"
        if not env_file.exists():
            env_file = Path.cwd() / ".env"
        
        log(f"Checking .env file at: {env_file}")
        if env_file.exists():
            try:
                content = env_file.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip()
                        if k in required and not env_vars.get(k):
                            env_vars[k] = v
            except Exception as e:
                log(f"Error reading .env: {e}")

    missing = required - set(env_vars.keys())
    if missing or not all(env_vars.get(k) for k in required):
        log(f"Error: Missing required environment variables: {missing}")
        log("Hint: Set them in Coolify UI or create a .env file.")
        return False
        
    log("Status: Environment validated (vars found)")
    return True

def cleanup_ports():
    """Kill any processes using the bot's ports to prevent 'Address already in use'."""
    ports = [8089, 9093]
    for port in ports:
        try:
            if os.name == 'posix':
                # Attempt fuser cleanup
                subprocess.run(['fuser', '-k', '-9', f'{port}/tcp'], capture_output=True)
                # Attempt lsof cleanup as fallback
                try:
                    result = subprocess.run(['lsof', '-t', '-i', f':{port}'], capture_output=True, text=True)
                    pids = result.stdout.strip().split()
                    if pids:
                        log(f"Found stale processes on port {port}: {pids}. Killing...")
                    for pid in pids:
                        subprocess.run(['kill', '-9', pid], capture_output=True)
                except: pass
            else:
                # Windows cleanup
                output = subprocess.check_output(['netstat', '-ano', '-p', 'tcp']).decode()
                for line in output.splitlines():
                    if f':{port}' in line:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            log(f"Found stale Windows process on port {port} (PID {pid}). Killing...")
                            subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True)
        except: pass

def start_bot() -> subprocess.Popen | None:
    cleanup_ports()
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
    # Try to read dynamic port from file first
    port = 8089
    port_file = Path("/root/.trading_bot/health_port")
    if port_file.exists():
        try:
            port = int(port_file.read_text().strip())
        except: pass

    url = f"http://localhost:{port}/health/ready"
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode())
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
        log("⚠️  Rate-limit reštartov — 30s pauza")
        time.sleep(30)
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
        log(f"Report saved: {rpt_file}")
    except Exception as e:
        log(f"Report failed: {e}")

def main():
    log("="*60)
    log("Resilient 24h AMM Bot Runner started")
    log("="*60)

    if not validate_env():
        log("Validation failed - exiting")
        return

    proc = start_bot()
    if not proc:
        log("Initial start failed - exiting")
        return

    start_time = time.time()
    deadline   = start_time + 86400
    last_health_check = time.time()
    
    log(f"Runner started. Target deadline: {datetime.fromtimestamp(deadline, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

    keep_running = True
    while time.time() < deadline and keep_running:
        try:
            # Check if process is still alive
            if proc.poll() is not None:
                log(f"Bot process died with code {proc.returncode}")
                if should_restart():
                    proc = start_bot()
                    if not proc: break
                    continue
                else:
                    keep_running = False
                    break

            # Periodic health check
            now = time.time()
            if now - last_health_check > HEALTH_INTERVAL:
                last_health_check = now
                if not is_healthy():
                    log("Bot unhealthy - restarting")
                    proc = restart_bot(proc)
                    if not proc: break
                else:
                    log("Bot healthy")

            time.sleep(5)

        except (KeyboardInterrupt, SystemExit):
            log("Shutdown requested via signal")
            keep_running = False
        except Exception as e:
            log(f"Runner error: {e}")
            time.sleep(5)

    if time.time() >= deadline:
        log("⏰ 24h deadline reached — shutting down")
    else:
        log("🛑 Shutdown initiated before deadline")

    if proc:
        try:
            log("Stopping bot process...")
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
