"""
Trailing Stop Loss — volatility-adjusted exit mechanism.

Uses high-water mark with ATR (Average True Range) buffer:
  exit if: price ≤ highest_price - (atr_multiplier × ATR)

If ATR is not provided externally, computes a simple volatility estimate
from a rolling window of recent close prices.
"""

from collections import deque
from typing import Optional
import numpy as np


class TrailingStop:
    """
    Volatility-adjusted trailing stop that tracks the high-water mark
    and exits when price drops too far below the peak.

    Designed for binary options markets where stop-loss is critical.
    """

    def __init__(
        self,
        atr_multiplier: float = 2.0,
        volatility_window: int = 14,
        min_buffer_pct: float = 0.005,  # 0.5% minimum buffer
    ):
        """
        Args:
            atr_multiplier: Buffer = multiplier × ATR (default 2.0)
            volatility_window: Number of recent bars for volatility calc (default 14)
            min_buffer_pct: Minimum buffer as fraction of price (default 0.5%)
        """
        self.atr_multiplier = atr_multiplier
        self.volatility_window = volatility_window
        self.min_buffer_pct = min_buffer_pct

        self.highest_price: Optional[float] = None
        self.price_window: deque[float] = deque(maxlen=volatility_window)
        self.exited: bool = False

    def update(self, price: float, is_entry: bool = False) -> None:
        """
        Process a new price tick.

        Args:
            price: Current market price
            is_entry: If True, resets state for a new position
        """
        if is_entry:
            self.reset()
            self.highest_price = price
        else:
            if self.highest_price is None:
                # First update without explicit entry — treat as implicit entry
                self.highest_price = price

        # Track high-water mark
        if price > self.highest_price:
            self.highest_price = price

        # Maintain rolling price window for volatility estimation
        self.price_window.append(price)

    def _current_volatility(self) -> float:
        """
        Compute sample standard deviation of recent close prices.
        Returns 0 if fewer than 2 prices in window.
        """
        if len(self.price_window) < 2:
            return 0.0
        return float(np.std(list(self.price_window), ddof=1))

    def _buffer_amount(self, atr: Optional[float] = None) -> float:
        """
        Compute stop-loss buffer distance from high-water mark.

        Uses external ATR if provided; otherwise estimates from price window.
        Ensures a minimum buffer to avoid noise-triggered exits.
        """
        if atr is not None and atr > 0:
            raw_buffer = self.atr_multiplier * atr
        else:
            # Fallback: estimate from price volatility
            volatility = self._current_volatility()
            raw_buffer = self.atr_multiplier * volatility

        # Enforce minimum buffer as percentage of high-water mark
        if self.highest_price is not None:
            min_buffer = self.highest_price * self.min_buffer_pct
            buffer = max(raw_buffer, min_buffer)
        else:
            buffer = raw_buffer or 0.01  # tiny default if no high-water

        return float(buffer)

    def should_exit(self, current_price: float, atr: Optional[float] = None) -> bool:
        """
        Determine if the trailing stop has been breached.

        Args:
            current_price: Latest market price
            atr: Optional external ATR value (0 if unavailable)

        Returns:
            True if price ≤ (highest_price − buffer), signaling exit
        """
        if self.exited:
            return True  # Already triggered — remain exited

        if self.highest_price is None:
            return False  # No position tracked

        buffer = self._buffer_amount(atr)
        stop_price = self.highest_price - buffer

        if current_price <= stop_price:
            self.exited = True
            return True
        return False

    def reset(self) -> None:
        """Clear state for a fresh position entry."""
        self.highest_price = None
        self.price_window.clear()
        self.exited = False
