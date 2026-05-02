"""
Market Regime Detector — Classifies market conditions as BULL/BEAR/SIDEWAYS.

Uses rolling return statistics over a lookback window:
  - Compute cumulative return over lookback period
  - If return > up_threshold → BULL
  - If return < down_threshold → BEAR
  - Otherwise → SIDEWAYS

Regime influences tau (persistence threshold) and position sizing.
"""

from typing import Literal
import numpy as np

RegimeType = Literal["BULL", "BEAR", "SIDEWAYS", "UNKNOWN"]


class RegimeDetector:
    """
    Detects the current market regime based on recent price action.

    Logic:
      1. Take last N prices (lookback window)
      2. Compute simple return: (last - first) / first
      3. Compare to up/down thresholds
      4. Return regime label

    The regime is used to adjust trading parameters:
      - BULL:  tau × 1.2  (more conservative — trends can reverse sharply)
      - BEAR:  tau × 1.5  (very conservative — avoid catching falling knife)
      - SIDEWAYS: tau × 1.0 (normal)
    """

    # Tau multipliers per regime (tuned empirically)
    TAU_MULTIPLIERS = {
        "BULL": 1.2,
        "BEAR": 1.5,
        "SIDEWAYS": 1.0,
        "UNKNOWN": 1.0,
    }

    def __init__(
        self,
        lookback: int = 20,
        up_threshold: float = 0.03,   # +3% over lookback = BULL
        down_threshold: float = -0.03 # -3% over lookback = BEAR
    ):
        """
        Args:
            lookback: Number of recent price points to analyze (default 20)
            up_threshold: Positive return threshold to classify as BULL (default 0.03)
            down_threshold: Negative return threshold to classify as BEAR (default -0.03)
        """
        if lookback < 2:
            raise ValueError("lookback must be >= 2")
        if up_threshold <= down_threshold:
            raise ValueError("up_threshold must be greater than down_threshold")

        self.lookback = lookback
        self.up_threshold = up_threshold
        self.down_threshold = down_threshold

    def detect(self, prices: np.ndarray | list[float]) -> RegimeType:
        """
        Classify the current market regime.

        Args:
            prices: Array-like of recent closing prices (must have >= lookback)

        Returns:
            One of: "BULL", "BEAR", "SIDEWAYS", "UNKNOWN"
        """
        if prices is None:
            raise ValueError("prices cannot be None")

        # Convert to numpy array
        price_array = np.asarray(prices, dtype=float)

        if price_array.ndim != 1:
            raise ValueError("prices must be 1-dimensional")

        # Need at least `lookback` points for a reliable regime assessment
        if len(price_array) < self.lookback:
            return "UNKNOWN"

        # Use last `lookback` prices
        window = price_array[-self.lookback:]

        if len(window) < 2:
            return "UNKNOWN"

        # Compute simple return over the window
        first_price = window[0]
        last_price = window[-1]

        if first_price <= 0:
            return "UNKNOWN"  # Invalid price data

        total_return = (last_price - first_price) / first_price

        # Classify
        if total_return >= self.up_threshold:
            return "BULL"
        elif total_return <= self.down_threshold:
            return "BEAR"
        else:
            return "SIDEWAYS"

    def get_tau_multiplier(self, regime: RegimeType) -> float:
        """
        Return tau multiplier for a given regime.

        Higher multiplier = more conservative threshold.
        Args:
            regime: Regime label from detect()

        Returns:
            Multiplier value (defaults to 1.0 for unknown regimes)
        """
        return self.TAU_MULTIPLIERS.get(regime, 1.0)

    def adjust_tau(self, base_tau: float, regime: RegimeType) -> float:
        """
        Apply regime-specific multiplier to a base tau value.

        Example:
            base_tau = 0.05
            regime = "BEAR" → adjusted_tau = 0.05 * 1.5 = 0.075
        """
        multiplier = self.get_tau_multiplier(regime)
        return base_tau * multiplier

    def confidence(self, prices: np.ndarray | list[float]) -> float:
        """
        Compute confidence score for the detected regime (0.0 to 1.0).

        Higher absolute return → higher confidence.
        Used to blend between conservative and aggressive tau settings.

        Returns:
            Confidence in [0, 1] where 1 = very confident in regime classification
        """
        price_array = np.asarray(prices, dtype=float)
        if len(price_array) < 2:
            return 0.0

        window = price_array[-self.lookback:] if len(price_array) >= self.lookback else price_array
        first, last = window[0], window[-1]

        if first <= 0:
            return 0.0

        total_return = abs((last - first) / first)

        # Sigmoid-like scaling: saturates at ~1.0 for returns > 15%
        confidence = 2 / (1 + np.exp(-total_return * 20)) - 1
        return float(np.clip(confidence, 0.0, 1.0))
