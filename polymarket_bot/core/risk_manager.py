"""
Portfolio Risk Manager — Enforces position sizing and exposure limits.

Tracks open positions and validates new trade proposals against:
  - Total capital exposure cap
  - Single-position size limit
  - Maximum concurrent positions
  - Correlation-weighted exposure (prevents over-concentration in correlated assets)

Used by the main trading loop before placing any order.
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class RiskViolation:
    """
    Describes why a proposed trade was rejected by risk manager.
    """
    reason: str
    detail: Optional[str] = None

    def __str__(self) -> str:
        return f"Risk violation: {self.reason}" + (f" ({self.detail})" if self.detail else "")


class PortfolioRiskManager:
    """
    Real-time risk guard for the trading portfolio.

    Example:
        rm = PortfolioRiskManager(
            max_total_exposure_usd=100.0,
            max_single_position_usd=30.0,
            max_positions=4,
            max_correlated_exposure_usd=80.0,
        )
        rm.record_entry("ETH", 25.0)
        violation = rm.check_entry("BTC", 30.0, correlations={"BTC": 1.0, "ETH": 0.8})
        if violation:
            log.warning(f"Blocked: {violation}")
    """

    def __init__(
        self,
        max_total_exposure_usd: float,
        max_single_position_usd: float,
        max_positions: int,
        max_correlated_exposure_usd: Optional[float] = None,
    ):
        """
        Args:
            max_total_exposure_usd: Hard cap on sum of all position sizes.
            max_single_position_usd: Max size per individual position.
            max_positions: Maximum number of concurrent open positions.
            max_correlated_exposure_usd: Soft cap on correlation-weighted exposure.
                If None, correlation check is disabled.
        """
        if any(x <= 0 for x in [max_total_exposure_usd, max_single_position_usd, max_positions]):
            raise ValueError("All limits must be positive")

        self.max_total_exposure = max_total_exposure_usd
        self.max_single_position = max_single_position_usd
        self.max_positions = max_positions
        self.max_correlated_exposure = max_correlated_exposure_usd

        # State tracking
        self.positions: Dict[str, float] = {}  # asset -> size_usd
        self.current_exposure: float = 0.0

    def check_entry(
        self,
        asset: str,
        proposed_size_usd: float,
        correlations: Dict[str, float],
    ) -> Optional[RiskViolation]:
        """
        Validate whether a new position can be opened.

        Args:
            asset: Asset symbol (e.g. 'ETH')
            proposed_size_usd: Desired position size in USD
            correlations: Dict mapping other relevant assets → correlation coefficient [0,1]
                (asset itself must be included with corr=1.0 for the weighted sum)

        Returns:
            None if trade passes all checks, else RiskViolation explaining the block.
        """
        # Basic sanity
        if proposed_size_usd <= 0:
            return RiskViolation("invalid_size", f"Proposed size {proposed_size_usd} is not positive")

        if proposed_size_usd > self.max_single_position:
            return RiskViolation(
                "single_position_limit_exceeded",
                f"Size {proposed_size_usd:.2f} > max {self.max_single_position:.2f}"
            )

        # Position count limit
        if len(self.positions) >= self.max_positions:
            return RiskViolation(
                "max_positions_reached",
                f"Already have {len(self.positions)} open positions (max={self.max_positions})"
            )

        # Total exposure check
        projected_total = self.current_exposure + proposed_size_usd
        if projected_total > self.max_total_exposure:
            return RiskViolation(
                "total_exposure_cap",
                f"Projected exposure ${projected_total:.2f} exceeds cap ${self.max_total_exposure:.2f}"
            )

        # Correlation-weighted exposure check (if enabled)
        if self.max_correlated_exposure is not None:
            correlated_sum = proposed_size_usd  # start with proposed
            for other_asset, other_size in self.positions.items():
                corr = correlations.get(other_asset, 0.0)
                # Correlated exposure contribution = position_size * correlation
                correlated_sum += other_size * corr

            if correlated_sum > self.max_correlated_exposure:
                return RiskViolation(
                    "correlated_exposure_limit",
                    f"Correlation-weighted exposure ${correlated_sum:.2f} exceeds ${self.max_correlated_exposure:.2f}"
                )

        # All clear
        return None

    def record_entry(self, asset: str, size_usd: float) -> None:
        """
        Record that a position has been opened.
        Should be called only after check_entry() returned None.
        """
        if asset in self.positions:
            raise ValueError(f"Asset {asset} already has an open position")
        self.positions[asset] = size_usd
        self.current_exposure += size_usd

    def record_exit(self, asset: str, size_usd: float) -> None:
        """
        Record that a position has been closed.
        Size should match the recorded entry size (partial exits handled by repeated calls).
        """
        if asset not in self.positions:
            raise ValueError(f"No open position for {asset}")
        current = self.positions[asset]
        if size_usd > current:
            raise ValueError(f"Cannot exit {size_usd} > open position {current}")
        self.positions[asset] -= size_usd
        self.current_exposure -= size_usd
        if self.positions[asset] <= 0.001:  # effectively zero
            del self.positions[asset]

    def get_available_capital(self) -> float:
        """Return remaining capital available for new positions."""
        return max(0.0, self.max_total_exposure - self.current_exposure)

    def reset(self) -> None:
        """Clear all positions (e.g., after emergency stop or daily reset)."""
        self.positions.clear()
        self.current_exposure = 0.0
