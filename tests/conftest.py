"""
Pytest configuration and fixtures for the trading bot test suite.

Fixtures provide:
  - tmp_config: temporary YAML config file
  - mock_client: PolymarketClient in dry-run mode
  - matrix: TransitionMatrix fixture with synthetic data
  - decision_engine: DecisionEngine with test thresholds
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import numpy as np

# Add project to path
import sys
sys.path.insert(0, '/opt/trading_bot')

from polymarket_bot.config.loader import load_config
from polymarket_bot.core.matrix import TransitionMatrix, bin_price
from polymarket_bot.core.decision import DecisionEngine
from polymarket_bot.exchange.client import PolymarketClient


# ========== Config Fixtures ==========

@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Create a minimal valid config YAML for testing."""
    config_content = """
app:
  name: "test-bot"
  version: "1.0.0"
  environment: "test"
  dry_run: true

exchange:
  platform: "polymarket"
  api:
    base_url: "https://api.polymarket.com"
    ws_url: "wss://api.polymarket.com/market/v1"
    timeout: 5
    max_retries: 1
    backoff_factor: 1.0
  auth:
    method: "wallet_signature"

trading:
  assets:
    BTC:
      symbol: "BTC"
      market_id: "0xTEST123"
      windows: ["5m", "1h"]
      enabled: true
      max_position_usd: 100.0
    ETH:
      symbol: "ETH"
      market_id: "0xTEST456"
      windows: ["5m"]
      enabled: true
      max_position_usd: 50.0
  markov:
    n_states: 50
    min_transitions: 5
    smoothing_alpha: 0.3
    window_sizes:
      "5m": 5
      "1h": 60
  thresholds:
    tau: 0.87
    eps: 0.05
    min_probability: 0.01
  position:
    method: "kelly"
    kelly:
      cap_max: 0.05
      cap_min: 0.01
  execution:
    order_type: "limit"
    limit_timeout_seconds: 10
    slippage_tolerance_bps: 5

risk:
  max_open_positions: 3
  max_daily_trades: 50
  max_drawdown: 0.20
  max_position_size_usd: 500.0
  max_position_size_pct: 0.10
  kill_switches:
    daily_loss_limit_usd: 100.0
    hourly_loss_limit_usd: 20.0

storage:
  redis:
    host: "localhost"
    port: 6379
    db: 0
    prefix: "test:"
    matrix_ttl: 60
  postgres:
    host: "localhost"
    port: 5432
    database: "test_db"
    user: "test_user"
    password: "test_pass"
    min_connections: 1
    max_connections: 5
  checkpoint:
    enabled: false
    path: "~/.trading_bot/test_checkpoint.json"
    interval_minutes: 5

monitoring:
  log_level: "DEBUG"
  log_file: "~/.trading_bot/test-logs/bot-%Y-%m-%d.log"
  log_rotation: "daily"
  log_retention_days: 7
  log_json: true
  metrics:
    enabled: true
    port: 9091
    path: "/metrics"
  health:
    enabled: true
    port: 8081
    live_path: "/health/live"
    ready_path: "/health/ready"
  sentry:
    dsn: null
    environment: "test"
    traces_sample_rate: 0.0
  alerts:
    telegram:
      enabled: false
      bot_token: ""
      chat_id: ""
      level: "INFO"
    slack:
      enabled: false
      webhook: ""

backtest:
  enabled: false
  data_source: "csv"
  initial_capital: 10000.0
  commission_bps: 10
  slippage_bps: 5
  latency_ms: 50
"""
    cfg_file = tmp_path / "test_config.yaml"
    cfg_file.write_text(config_content)
    return cfg_file


@pytest.fixture
def loaded_config(tmp_config: Path):
    """Load and return validated config from tmp YAML."""
    return load_config(str(tmp_config))


# ========== Matrix Fixtures ==========

@pytest.fixture
def simple_matrix():
    """Create a small TransitionMatrix for unit tests."""
    return TransitionMatrix(n_states=10, window_size=5, smoothing_alpha=0.5, min_transitions=3)


@pytest.fixture
def populated_matrix(simple_matrix):
    """Matrix with synthetic price sequence fed in."""
    # Simulate: price oscillates between states 3-4-5
    prices = [0.30, 0.32, 0.35, 0.33, 0.31,  # window 1
              0.34, 0.36, 0.38, 0.37, 0.35,  # window 2
              0.37, 0.39, 0.41, 0.40, 0.38]  # window 3
    for p in prices:
        simple_matrix.update(p)
    return simple_matrix


# ========== Decision Engine Fixtures ==========

@pytest.fixture
def decision_engine():
    """Standard DecisionEngine with test thresholds."""
    return DecisionEngine(tau=0.87, eps=0.05, min_probability=0.01)


# ========== Client Fixtures ==========

@pytest.fixture
def mock_client():
    """PolymarketClient in dry-run (mock) mode."""
    return PolymarketClient(dry_run=True, sandbox=False)


# ========== Helper Fixtures ==========

@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Ensure test directories exist."""
    test_log_dir = Path.home() / ".trading_bot" / "test-logs"
    test_log_dir.mkdir(parents=True, exist_ok=True)
    yield
    # No cleanup — keep logs for debugging


@pytest.fixture
def event_loop():
    """Create a fresh event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ========== Parametric Test Data ==========

MATRIX_SIZES = [10, 50, 100]
"""Parametrize matrix tests across different state counts."""

TAU_VALUES = [0.80, 0.87, 0.93]
"""Diagonal persistence threshold values to test."""

EPS_VALUES = [0.03, 0.05, 0.10]
"""Arbitrage gap threshold values."""

# ========== Resource Cleanup (autouse) ==========



@pytest.fixture(autouse=True)
def reset_health_server_state():
    """Reset HealthServer class-level state per test (sync wrapper)."""
    from polymarket_bot.monitoring.health import HealthServer
    import asyncio

    # Create fresh lock per test
    HealthServer._lock = asyncio.Lock()

    yield

    # No cleanup — tests manage their own health server lifecycle
@pytest.fixture(autouse=True)
def cleanup_monitoring_resources():
    """
    Ensure all monitoring servers (metrics, health) are stopped after each test.
    This prevents port-binding conflicts in sequential tests.
    """
    yield

    # ---- After-test cleanup (sync) ----
    from polymarket_bot.monitoring.metrics import MetricsExporter
    from polymarket_bot.monitoring.health import HealthServer
    import asyncio

    # 1) Stop any live MetricsExporter instances
    with MetricsExporter._lock:
        for port, entry in list(MetricsExporter._live.items()):
            try:
                entry['server'].shutdown()
            except Exception:
                pass
            try:
                entry['server'].server_close()
            except Exception:
                pass
            try:
                entry['thread'].join(timeout=5)
            except Exception:
                pass
            MetricsExporter._live.pop(port, None)

    # 2) Stop any live HealthServer instances via asyncio.run()
    def _cleanup():
        async def cleanup():
            async with HealthServer._lock:
                for port, entry in list(HealthServer._live.items()):
                    try:
                        if entry.get('site') is not None:
                            await entry['site'].stop()
                    except Exception:
                        pass
                    try:
                        await entry['runner'].cleanup()
                    except Exception:
                        pass
                    HealthServer._live.pop(port, None)
        asyncio.run(cleanup())

    try:
        _cleanup()
    except Exception:
        pass
