"""
Volume Filter — Liquidity-based entry gating.

Prevents entering markets with insufficient 24h trading volume.
This protects against slippage, inability to exit, and fake markets.
"""

from typing import Optional


class VolumeFilter:
    """
    Simple threshold-based volume filter.

    Usage:
        vf = VolumeFilter(min_volume_usd=100_000.0)
        if vf.should_trade(market_id, volume_usd):
            proceed with entry
    """

    def __init__(self, min_volume_usd: float = 50_000.0):
        """
        Args:
            min_volume_usd: Minimum 24h volume in USD to consider trading.
        """
        if min_volume_usd <= 0:
            raise ValueError("min_volume_usd must be positive")
        self.min_volume_usd = min_volume_usd

    def should_trade(self, market_id: str, volume_usd: Optional[float]) -> bool:
        """
        Decide whether to trade a market based on its 24h volume.

        Args:
            market_id: Market identifier (for logging/debugging)
            volume_usd: 24h trading volume in USD (None if unavailable)

        Returns:
            True if volume >= threshold, False otherwise.
        """
        if volume_usd is None:
            # No volume data — safer to skip
            return False

        if volume_usd < 0:
            # Data error — reject
            return False

        return volume_usd >= self.min_volume_usd

    def adjust_for_extreme_volatility(self, volume_usd: float, price_volatility: float) -> bool:
        """
        Optional: further filter based on volume/volatility ratio.
        High volatility + low volume = toxic / unsafe to trade.

        Returns True if volume/volatility ratio exceeds safe threshold.
        """
        if price_volatility <= 0:
            return True
        ratio = volume_usd / (price_volatility * 1_000_000)  # arbitrary scaling
        return ratio >= 1.0  # 需要调优
