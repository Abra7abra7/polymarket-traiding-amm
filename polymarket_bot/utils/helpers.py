import os
from datetime import datetime, timezone
from typing import Dict

def get_window_duration_days(window: str) -> float:
    """Convert window label to fractional days."""
    mapping = {
        '5m': 5 / (60 * 24),
        '15m': 15 / (60 * 24),
        '1h': 1 / 24,
        '4h': 4 / 24,
        '6h': 6 / 24,
        '1d': 1.0,
    }
    return mapping.get(window, 1.0)

def resolve_market_id(asset_cfg, window: str) -> str:
    """Build correct market_id for asset+window."""
    crypto = ('BTC', 'ETH', 'TAO', 'HL', 'HYPERLIQUID', 'HYPE', 'SOL', 'DOGE', 'XRP')
    symbol = getattr(asset_cfg, 'symbol', None)
    if symbol in crypto:
        return f"{symbol}_{window.upper()}"
    
    # Weather/exotic assets: use market_id base
    base = getattr(asset_cfg, 'market_id', symbol)
    return f"{base}_{window.upper()}"

def get_market_volatility(asset_cfg) -> float:
    """Fetch volatility from market config, default 0.03."""
    if asset_cfg:
        return getattr(asset_cfg, 'volatility', 0.03)
    return 0.03
