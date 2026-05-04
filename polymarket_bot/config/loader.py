"""
Configuration loader and validator.

Loads YAML config, substitutes environment variables, validates schema.
Uses Pydantic for typed config objects.
"""

import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from pydantic import BaseModel, ValidationError, field_validator, Field

# ========== Pydantic Schemas ==========

class ExchangeAuthConfig(BaseModel):
    method: str = "wallet_signature"
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    wallet_address: Optional[str] = None
    private_key: Optional[str] = None

    @field_validator('api_key', 'api_secret', mode='before')
    @classmethod
    def ensure_str(cls, v):
        return str(v) if v is not None else v



class ExchangeAPIConfig(BaseModel):
    base_url: str = "https://api.polymarket.com"
    ws_url: str = "wss://api.polymarket.com/market/v1"
    timeout: int = 10
    max_retries: int = 3
    backoff_factor: float = 2.0



class GammaConfig(BaseModel):
    base_url: str = "https://gamma-api.polymarket.com"
    timeout: int = 10


class DataConfig(BaseModel):
    base_url: str = "https://data-api.polymarket.com"
    timeout: int = 10


class ClobAuthConfig(BaseModel):
    method: str = "bearer"
    token: Optional[str] = None


class ClobConfig(BaseModel):
    base_url: str = "https://clob.polymarket.com"
    timeout: int = 10
    auth: ClobAuthConfig = ClobAuthConfig()


class AMMConfig(BaseModel):
    base_url: str = "https://gamma-api.polymarket.com"
    router_address: str = "0x0000000000000000000000000000000000000000"
    timeout: int = 10
    gas_limit: int = 300000
    gas_price_gwei: int = 2


class ExchangeConfig(BaseModel):
    platform: str = "polymarket"
    gamma: GammaConfig = GammaConfig()
    data: DataConfig = DataConfig()
    clob: ClobConfig = ClobConfig()
    api: ExchangeAPIConfig = ExchangeAPIConfig()
    auth: ExchangeAuthConfig = ExchangeAuthConfig()
    amm: AMMConfig = AMMConfig()


class AssetConfig(BaseModel):
    symbol: Optional[str] = None  # filled from config key at load time
    market_id: str
    condition_id: Optional[str] = None
    token_id: Optional[str] = None
    windows: List[str] = Field(default_factory=lambda: ['5m'])
    enabled: bool = True
    max_position_usd: float = 1000.0


class MarkovConfig(BaseModel):
    n_states: int = 100
    min_transitions: int = 30
    smoothing_alpha: float = 0.3
    window_sizes: Dict[str, int] = {"5m": 5, "1h": 60}


class ThresholdsConfig(BaseModel):
    tau: float = 0.87
    eps: float = 0.05
    min_probability: float = 0.01

    @field_validator('tau', 'eps', 'min_probability')
    @classmethod
    def check_range(cls, v: float) -> float:
        if not (0.0 < v <= 1.0):
            raise ValueError(f"Must be in (0, 1], got {v}")
        return v


class PositionConfig(BaseModel):
    method: str = "kelly"  # "kelly" | "fixed" | "custom"
    kelly: Dict[str, float] = {"cap_max": 0.80, "cap_min": 0.05}
    fixed: Dict[str, float] = {"fraction": 0.10}


class ExecutionConfig(BaseModel):
    order_type: str = "limit"  # "limit" | "market"
    limit_timeout_seconds: int = 30
    slippage_tolerance_bps: int = 10



class PaperTradingConfig(BaseModel):
    """Configuration for paper trading simulation."""
    spread_bps: int = 200
    slippage_bps: int = 50
    fill_latency_ms: int = 200
    partial_fill_prob: float = 0.1
    data_dir: str = "~/.trading_bot"
    initial_balance: float = 50000.0
    swap_fee_bps: int = 200          # 2% swap fee (Polymarket AMM fee)
    gas_fee_usd: float = 0.01        # gas fee on Polygon (~$0.01 per trade)

class TradingAssetsConfig(BaseModel):
    # Dynamic: BTC, ETH, SOL, etc.
    pass


# We'll use a Dict for assets since keys are dynamic (BTC, ETH, ...)
# But we can validate each entry with AssetConfig


class KillSwitchesConfig(BaseModel):
    daily_loss_limit_usd: Optional[float] = 5000
    hourly_loss_limit_usd: Optional[float] = 1000


class RiskConfig(BaseModel):
    max_open_positions: int = 5
    max_daily_trades: int = 100
    max_drawdown: float = 0.20
    max_position_size_usd: float = 5000
    max_position_size_pct: float = 0.10
    max_total_exposure_usd: Optional[float] = None
    max_total_exposure_pct: Optional[float] = None
    max_positions_per_asset: int = 2
    kill_switches: KillSwitchesConfig = KillSwitchesConfig()


class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    prefix: str = "trading:"
    matrix_ttl: int = 3600
    password: Optional[str] = None


class PostgresConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    database: str = "trading_bot"
    user: str = "tradingbot"
    password: str = ""
    min_connections: int = 5
    max_connections: int = 20


class CheckpointConfig(BaseModel):
    enabled: bool = True
    path: str = "~/.trading_bot/checkpoint.json"
    interval_minutes: int = 60


class StorageConfig(BaseModel):
    redis: RedisConfig = RedisConfig()
    postgres: PostgresConfig = PostgresConfig()
    checkpoint: CheckpointConfig = CheckpointConfig()


class AlertsTelegramConfig(BaseModel):
    enabled: bool = True
    bot_token: str = ""
    chat_id: str = ""
    level: str = "WARNING"  # "INFO" | "WARNING" | "CRITICAL"


class AlertsSlackConfig(BaseModel):
    enabled: bool = False
    webhook: str = ""


class AlertsConfig(BaseModel):
    telegram: AlertsTelegramConfig = AlertsTelegramConfig()
    slack: AlertsSlackConfig = AlertsSlackConfig()


class SentryConfig(BaseModel):
    dsn: Optional[str] = None
    environment: str = "production"
    traces_sample_rate: float = 0.1


class MonitoringMetricsConfig(BaseModel):
    enabled: bool = True
    port: int = 9090
    path: str = "/metrics"


class MonitoringHealthConfig(BaseModel):
    enabled: bool = True
    port: int = 8080
    live_path: str = "/health/live"
    ready_path: str = "/health/ready"


class MonitoringConfig(BaseModel):
    log_level: str = "INFO"
    log_file: str = "~/.trading_bot/logs/bot-%Y-%m-%d.log"
    log_rotation: str = "daily"
    log_retention_days: int = 30
    log_json: bool = True
    metrics: MonitoringMetricsConfig = MonitoringMetricsConfig()
    health: MonitoringHealthConfig = MonitoringHealthConfig()
    sentry: SentryConfig = SentryConfig()
    alerts: AlertsConfig = AlertsConfig()

    @field_validator('log_file')
    @classmethod
    def expand_log_file(cls, v: str) -> str:
        return os.path.expanduser(v)


class BacktestConfig(BaseModel):
    enabled: bool = False
    data_source: str = "csv"
    initial_capital: float = 50000
    commission_bps: int = 20
    slippage_bps: int = 5
    latency_ms: int = 100


class AppConfig(BaseModel):
    name: str = "polymarket-markov-bot"
    version: str = "1.0.0"
    environment: str = "development"
    dry_run: bool = True
    paper_trading: bool = False


class TradingConfig(BaseModel):
    assets: Dict[str, AssetConfig]
    markov: MarkovConfig = MarkovConfig()
    thresholds: ThresholdsConfig = ThresholdsConfig()
    position: PositionConfig = PositionConfig()
    execution: ExecutionConfig = ExecutionConfig()


class FullConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    paper_trading: PaperTradingConfig = Field(default_factory=PaperTradingConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)


# ========== Config Loader ==========

def expand_path(path: str) -> str:
    """Expand ~ and environment variables in path."""
    return os.path.expanduser(os.path.expandvars(path))


def load_config(config_path: str = "config/config.yaml") -> FullConfig:
    """
    Load and validate configuration from YAML file.

    Args:
        config_path: Path to YAML config file

    Returns:
        FullConfig: validated config object
    """
    path = Path(expand_path(config_path))
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, 'r') as f:
        raw_config = yaml.safe_load(f)

    # Substitute environment variables in the dict
    raw_config = _substitute_env_vars(raw_config)

    try:
        config = FullConfig(**raw_config)
        return config
    except ValidationError as e:
        print("❌ Configuration validation failed:")
        for err in e.errors():
            loc = ".".join(str(x) for x in err['loc'])
            print(f"   {loc}: {err['msg']}")
        raise


def _substitute_env_vars(config_dict: dict) -> dict:
    """
    Recursively replace ${VAR} strings with environment variable values.
    """
    if isinstance(config_dict, dict):
        return {k: _substitute_env_vars(v) for k, v in config_dict.items()}
    elif isinstance(config_dict, list):
        return [_substitute_env_vars(item) for item in config_dict]
    elif isinstance(config_dict, str):
        import re
        pattern = r'\$\{([^}]+)\}'
        def replacer(match):
            var_expr = match.group(1)
            if ':' in var_expr:
                var_name, default = var_expr.split(':', 1)
                val = os.getenv(var_name, default)
            else:
                val = os.getenv(var_expr)
            return str(val) if val is not None else match.group(0)
        return re.sub(pattern, replacer, config_dict)
    else:
        return config_dict


def validate_config_file(config_path: str) -> list[str]:
    """
    Validate config without loading (returns list of errors).
    """
    try:
        load_config(config_path)
        return []
    except Exception as e:
        return [str(e)]


# ========== Usage Example ==========

if __name__ == "__main__":
    import sys

    print("=== Config Loader Test ===")

    # Try loading example config
    try:
        config = load_config("config/config.example.yaml")
        print("✅ Config loaded successfully!")
        print(f"   App: {config.app.name} v{config.app.version}")
        print(f"   Dry run: {config.app.dry_run}")
        print(f"   Assets: {list(config.trading.assets.keys())}")
        if 'BTC' in config.trading.assets:
            btc = config.trading.assets['BTC']
            print(f"   BTC windows: {btc.windows}")
        print(f"   Thresholds: τ={config.trading.thresholds.tau}, ε={config.trading.thresholds.eps}")
    except Exception as e:
        print(f"❌ Failed: {e}")
        sys.exit(1)
