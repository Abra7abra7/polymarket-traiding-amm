#!/usr/bin/env python3
"""
Deployment helper for Polymarket trading bot.

Transitions from paper_trading → live mode with proper validation.

Usage:
  python scripts/deploy_live.py --dry-run     # Show what would change
  python scripts/deploy_live.py --paper       # Keep paper trading, just validate config
  python scripts/deploy_live.py --live        # Full live deployment (needs CLOB JWT)
"""
import argparse
import subprocess
import sys
import time
import os
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIG_YAML = REPO / "config" / "config.yaml"
CHECKPOINT = Path.home() / ".trading_bot" / "checkpoint.json"
HEALTH_URL = "http://localhost:8086/health/ready"
METRICS_URL = "http://localhost:9090/metrics"


def run(cmd, cwd=REPO, check=True):
    """Run shell command, return CompletedProcess."""
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  ❌ Command failed:\n{result.stderr[-500:]}")
        sys.exit(1)
    return result


def backup_current():
    """Backup current config, checkpoint, and logs."""
    backup_dir = REPO / "backups" / time.strftime("%Y%m%d-%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)

    files = [
        CONFIG_YAML,
        Path.home() / ".trading_bot" / "checkpoint.json",
        Path.home() / ".trading_bot" / "trades.jsonl",
    ]
    for f in files:
        if f.exists():
            dest = backup_dir / f.name
            dest.write_text(f.read_text())
            print(f"  ✓ Backed up {f.name}")

    print(f"  📦 Backup dir: {backup_dir}")
    return backup_dir


def validate_config():
    """Validate YAML config via loader."""
    print("\n1️⃣  Validating config...")
    result = run([sys.executable, "-m", "polymarket_bot.config.loader"], check=False)
    if result.returncode != 0:
        print("❌ Config validation failed")
        print(result.stdout[-500:])
        print(result.stderr[-500:])
        sys.exit(1)
    print("✅ Config structure valid")


def validate_env():
    """Check that necessary env vars are set (non-placeholder)."""
    print("\n2️⃣  Checking environment variables...")
    env_file = REPO / ".env"
    if not env_file.exists():
        print("❌ .env file not found")
        sys.exit(1)

    content = env_file.read_text()
    issues = []

    # Check for placeholders
    placeholders = ["${", "YOUR_", "poskytnutý", "***"]
    for line in content.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        if any(p in val for p in placeholders):
            issues.append(f"  ⚠️  {key} contains placeholder: {val[:50]}")

    if issues:
        print("❌ Environment issues detected:")
        for i in issues:
            print(i)
        print("\n   Edit .env and set real values before live deployment.")
        sys.exit(1)

    print("✅ All env vars appear to be set (no placeholders)")


def test_clob_connectivity():
    """Quick connectivity + auth test against CLOB /book endpoint."""
    print("\n3️⃣  Testing CLOB API connectivity...")
    test_script = REPO / "scripts" / "test_polymarket_api.py"
    if not test_script.exists():
        print("❌ Missing scripts/test_polymarket_api.py")
        sys.exit(1)

    result = run([sys.executable, str(test_script), "--quick"], check=False)
    if result.returncode != 0:
        print("❌ CLOB connectivity test failed")
        print(result.stdout[-800:])
        print(result.stderr[-500:])
        sys.exit(1)
    print("✅ CLOB API reachable and authenticated")


def stop_running_bot():
    """Stop any currently running bot process."""
    print("\n4️⃣  Stopping running bot...")
    # Find bot processes by name or PID file
    pid_file = Path.home() / ".trading_bot" / "bot.pid"
    if pid_file.exists():
        pid = int(pid_file.read_text().strip())
        try:
            os.kill(pid, 15)  # SIGTERM
            time.sleep(2)
            print(f"  ✓ Sent SIGTERM to PID {pid}")
        except ProcessLookupError:
            print(f"  ⚠️  PID {pid} not running")
        pid_file.unlink(missing_ok=True)

    # Double-check no bot.py processes remain
    result = subprocess.run(["pgrep", "-f", "polymarket_bot"], capture_output=True, text=True)
    if result.returncode == 0:
        pids = result.stdout.strip().split("\n")
        for pid in pids:
            os.kill(int(pid), 15)
            print(f"  ✓ Killed stray PID {pid}")
    else:
        print("  ✓ No running bot processes found")


def update_config_for_live(dry_run=False, paper_trading=None):
    """Switch config from dry_run → live mode."""
    print("\n5️⃣  Updating config for live mode...")
    import yaml

    with open(CONFIG_YAML) as f:
        config = yaml.safe_load(f)

    old_dry = config["app"].get("dry_run", True)
    old_paper = config["app"].get("paper_trading", False)

    config["app"]["dry_run"] = dry_run
    if paper_trading is not None:
        config["app"]["paper_trading"] = paper_trading

    with open(CONFIG_YAML, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"  ✓ app.dry_run: {old_dry} → {config['app']['dry_run']}")
    print(f"  ✓ app.paper_trading: {old_paper} → {config['app'].get('paper_trading', 'unchanged')}")


def start_bot():
    """Start the bot as a background service."""
    print("\n6️⃣  Starting bot...")
    # Use systemd, screen, or simple background process?
    # For now, use subprocess.Popen with PID tracking
    import daemon

    pid_dir = Path.home() / ".trading_bot"
    pid_dir.mkdir(exist_ok=True)

    pid_file = pid_dir / "bot.pid"

    # Simple background with nohup (will be supervised by cron/systemd later)
    log_file = pid_dir / "bot-current.log"
    cmd = [sys.executable, "-m", "polymarket_bot"]
    with open(log_file, "a") as lf:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO,
            stdout=lf,
            stderr=lf,
            preexec_fn=os.setsid
        )

    pid_file.write_text(str(proc.pid))
    print(f"  ✓ Bot started (PID {proc.pid})")
    print(f"  📋 Log: {log_file}")


def wait_for_healthy(timeout=30):
    """Poll /health/ready until bot reports ready."""
    print(f"\n7️⃣  Waiting for bot to become healthy (≤{timeout}s)...")
    import urllib.request
    import urllib.error

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=2) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read())
                    if data.get("status") == "ok":
                        print(f"  ✅ Bot ready: {data}")
                        return True
        except urllib.error.HTTPError as e:
            if e.code == 503:
                pass  # expected while starting
        except Exception:
            pass
        time.sleep(1)
        print("  …", end="", flush=True)

    print(f"\n❌ Health check timed out after {timeout}s")
    print(f"   Check logs: tail -f {Path.home()}/.trading_bot/bot-current.log")
    return False


def main():
    parser = argparse.ArgumentParser(description="Deploy Polymarket trading bot")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--live", action="store_true", help="Deploy to live trading")
    group.add_argument("--paper", action="store_true", help="Paper trading mode (validate only)")
    group.add_argument("--dry-run", action="store_true", help="Show changes without applying")

    args = parser.parse_args()

    print("🚀 Polymarket Bot Deployment")
    print(f"   Repo: {REPO}")
    print(f"   Mode: {'LIVE' if args.live else 'PAPER'}")

    if args.dry_run:
        print("\n[DRY RUN] Would:")
        print("  - backup current config/checkpoint")
        print("  - validate config structure")
        print("  - validate env vars (no placeholders)")
        print("  - test CLOB API connectivity")
        print("  - stop running bot")
        if args.live:
            print("  - set dry_run=false, paper_trading=false (LIVE)")
        else:
            print("  - set dry_run=true, paper_trading=true (PAPER)")
        print("  - start bot")
        print("  - poll /health/ready until OK")
        return

    # 1. Backup
    backup_current()

    # 2. Validate config
    validate_config()

    # 3. Env check
    validate_env()

    # 4. CLOB test (only if we have a real token, skip in mock)
    if args.live:
        test_clob_connectivity()

    # 5. Stop existing
    stop_running_bot()

    # 6. Update config
    if args.live:
        update_config_for_live(dry_run=False, paper_trading=False)
    else:
        update_config_for_live(dry_run=True, paper_trading=True)

    # 7. Start bot
    start_bot()

    # 8. Health check
    if not wait_for_healthy(timeout=30):
        sys.exit(1)

    print("\n✅ Deployment successful!")
    print(f"   Dashboard: {HEALTH_URL}")
    print(f"   Metrics:   {METRICS_URL}")
    print(f"   Logs:      {Path.home()}/.trading_bot/bot-current.log")


if __name__ == "__main__":
    main()
