"""
Unit tests for polymarket_bot.config.loader.

Tests:
  - load_config() — valid config loads
  - Invalid config raises ValidationError with helpful messages
  - Environment variable substitution (${VAR}, ${VAR:default})
  - Path expansion (~)
  - Config schema validation (required sections, types)
"""

import pytest
import tempfile
from pathlib import Path
from polymarket_bot.config.loader import load_config, expand_path, _substitute_env_vars


class TestExpandPath:
    """Test path expansion utility."""

    def test_expand_home(self):
        path = expand_path("~/.trading_bot/config.yaml")
        assert path.startswith(str(Path.home()))

    def test_expand_env_vars(self, monkeypatch):
        monkeypatch.setenv("TEST_DIR", "/tmp/test")
        path = expand_path("$TEST_DIR/file.yaml")
        assert path == "/tmp/test/file.yaml"

    def test_expand_combined(self, monkeypatch):
        monkeypatch.setenv("CONF", "config")
        path = expand_path("~/$CONF/file.yaml")
        assert "~" not in path
        assert Path.home().as_posix() in path


class TestEnvSubstitution:
    """Test ${VAR} replacement in config dicts."""

    def test_simple_substitution(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "secret123")
        raw = {"key": "${API_KEY}"}
        result = _substitute_env_vars(raw)
        assert result["key"] == "secret123"

    def test_substitution_with_default(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        raw = {"key": "${MISSING_VAR:default_value}"}
        result = _substitute_env_vars(raw)
        assert result["key"] == "default_value"

    def test_nested_dict_substitution(self, monkeypatch):
        monkeypatch.setenv("HOST", "localhost")
        raw = {"db": {"host": "${HOST}", "port": 5432}}
        result = _substitute_env_vars(raw)
        assert result["db"]["host"] == "localhost"

    def test_list_substitution(self, monkeypatch):
        monkeypatch.setenv("URL", "https://api.example.com")
        raw = {"endpoints": ["${URL}/v1", "${URL}/v2"]}
        result = _substitute_env_vars(raw)
        assert result["endpoints"][0] == "https://api.example.com/v1"

    def test_missing_var_returns_original(self, monkeypatch):
        monkeypatch.delenv("UNDEFINED", raising=False)
        raw = {"key": "${UNDEFINED}"}
        result = _substitute_env_vars(raw)
        # Should return original string (or warning printed)
        assert result["key"] == "${UNDEFINED}"


class TestLoadConfigValid:
    """Test loading a valid config file."""

    def test_load_minimal_config(self, tmp_path):
        yaml_content = """
app:
  dry_run: true
exchange:
  platform: "test"
trading:
  assets:
    BTC:
      symbol: "BTC"
      market_id: "0xBTC"
      windows: ["5m"]
risk: {}
monitoring: {}
storage: {}
backtest: {}
"""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml_content)

        cfg = load_config(str(cfg_file))
        assert cfg.app.dry_run is True
        assert cfg.trading.assets["BTC"].symbol == "BTC"
        assert "5m" in cfg.trading.assets["BTC"].windows

    def test_load_full_config(self, tmp_config):
        cfg = load_config(str(tmp_config))
        assert cfg.app.name == "test-bot"
        assert cfg.exchange.api.base_url == "https://api.polymarket.com"
        assert len(cfg.trading.assets) == 2
        assert cfg.risk.max_open_positions == 3
        assert cfg.monitoring.metrics.port == 9091

    def test_config_values_types(self, tmp_config):
        cfg = load_config(str(tmp_config))
        assert isinstance(cfg.app.dry_run, bool)
        assert isinstance(cfg.trading.thresholds.tau, float)
        assert isinstance(cfg.trading.assets["BTC"].max_position_usd, float)
        assert isinstance(cfg.risk.max_open_positions, int)


class TestLoadConfigInvalid:
    """Test config validation errors."""

    def test_missing_required_section(self, tmp_path):
        yaml_content = """
app:
  dry_run: true
# missing exchange, trading, risk, monitoring, storage, backtest
"""
        cfg_file = tmp_path / "bad.yaml"
        cfg_file.write_text(yaml_content)

        with pytest.raises(Exception):  # ValidationError
            load_config(str(cfg_file))

    def test_invalid_threshold_range(self, tmp_path):
        yaml_content = """
app:
  dry_run: true
exchange:
  platform: "test"
trading:
  assets:
    BTC:
      symbol: "BTC"
      market_id: "0x1"
      windows: ["5m"]
  thresholds:
    tau: 1.5   # invalid: > 1.0
    eps: 0.05
risk: {}
monitoring: {}
storage: {}
backtest: {}
"""
        cfg_file = tmp_path / "bad.yaml"
        cfg_file.write_text(yaml_content)

        with pytest.raises(Exception):
            load_config(str(cfg_file))

    def test_invalid_asset_type(self, tmp_path):
        yaml_content = """
app:
  dry_run: true
exchange:
  platform: "test"
trading:
  assets:
    BTC:
      symbol: 123   # should be string
      market_id: "0x1"
      windows: ["5m"]
risk: {}
monitoring: {}
storage: {}
backtest: {}
"""
        cfg_file = tmp_path / "bad.yaml"
        cfg_file.write_text(yaml_content)

        with pytest.raises(Exception):
            load_config(str(cfg_file))

    def test_missing_asset_required_fields(self, tmp_path):
        yaml_content = """
app:
  dry_run: true
exchange:
  platform: "test"
trading:
  assets:
    BTC: {}   # missing symbol, market_id, windows
risk: {}
monitoring: {}
storage: {}
backtest: {}
"""
        cfg_file = tmp_path / "bad.yaml"
        cfg_file.write_text(yaml_content)

        with pytest.raises(Exception):
            load_config(str(cfg_file))


class TestConfigFileNotFound:
    """Test missing config file."""

    def test_load_nonexistent_config_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")


class TestConfigEnvSubstitutionIntegration:
    """Test ${VAR} substitution in real config file."""

    def test_env_substitution_in_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "abc123")
        yaml_content = """
app:
  dry_run: true
exchange:
  platform: "test"
  api:
    base_url: "${API_BASE_URL}"
trading:
  assets:
    BTC:
      symbol: "BTC"
      market_id: "0x1"
      windows: ["5m"]
risk: {}
monitoring: {}
storage:
  postgres:
    password: "${DB_PASS}"
backtest: {}
"""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml_content)

        # API_BASE_URL not set → should remain as-is with warning
        cfg = load_config(str(cfg_file))
        # DB_PASS not set → remains as-is
        assert cfg.storage.postgres.password == "${DB_PASS}"
