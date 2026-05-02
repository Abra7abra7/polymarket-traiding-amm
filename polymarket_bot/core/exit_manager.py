"""
Exit Manager — Time-based exit logic for multi-window strategies.

Each timeframe has a specific hold horizon (number of bars):
  - 5m  → 12 bars  (= 1 hour)
  - 1h  →  3 bars  (= 3 hours)
  - 6h  →  2 bars  (= 12 hours)

Exit is purely time-based; price does not affect the decision.
Positions that reach their horizon are marked for exit on the next tick.
"""

from typing import Dict, Tuple

class ExitManager:
    """
    Tracks entry bar index per (asset, timeframe) and triggers exit
    when the position has been held for its configured horizon.
    """

    # Bars to hold per timeframe (backtested optimal from paper)
    EXIT_HORIZONS: Dict[str, int] = {
        "5m": 12,   # 1 hour  (12 * 5min)
        "1h": 3,    # 3 hours (3 * 1h)
        "6h": 2,    # 12 hours (2 * 6h)
    }

    def __init__(self):
        # (asset, timeframe) -> entry_bar_index
        self._entry_bar: Dict[Tuple[str, str], int] = {}

    def register_entry(self, asset: str, timeframe: str, entry_bar: int) -> None:
        """
        Record that a position was opened at the given bar index.

        Args:
            asset: Asset symbol (e.g. 'ETH')
            timeframe: Timeframe label ('5m', '1h', '6h')
            entry_bar: Bar/candle index when position was opened
        """
        if timeframe not in self.EXIT_HORIZONS:
            raise KeyError(f"Unknown timeframe '{timeframe}' — "
                           f"valid: {list(self.EXIT_HORIZONS)}")
        key = (asset, timeframe)
        self._entry_bar[key] = entry_bar

    def should_exit(self, asset: str, timeframe: str, current_bar: int) -> bool:
        """
        Check if position should be closed based on hold time.

        Args:
            asset: Asset symbol
            timeframe: Timeframe label
            current_bar: Current bar index (from data feed)

        Returns:
            True if (current_bar - entry_bar) >= horizon for this timeframe
        """
        # Validate timeframe first (fail-fast for programming errors)
        if timeframe not in self.EXIT_HORIZONS:
            raise KeyError(f"Unknown timeframe '{timeframe}' — "
                           f"valid: {list(self.EXIT_HORIZONS)}")

        key = (asset, timeframe)
        entry_bar = self._entry_bar.get(key)
        if entry_bar is None:
            return False  # No registered entry

        horizon = self.EXIT_HORIZONS[timeframe]
        bars_held = current_bar - entry_bar
        return bars_held >= horizon

    def clear(self, asset: str, timeframe: str) -> None:
        """
        Remove entry record after position is closed.
        Allows re-entry tracking for the same asset/timeframe.
        """
        key = (asset, timeframe)
        self._entry_bar.pop(key, None)

    def bars_held(self, asset: str, timeframe: str, current_bar: int) -> int:
        """
        Return how many bars the position has been held (0 if no position).
        Useful for diagnostics and graceful exit planning.
        """
        key = (asset, timeframe)
        entry_bar = self._entry_bar.get(key)
        if entry_bar is None:
            return 0
        return current_bar - entry_bar
