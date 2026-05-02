"""
Test suite for portfolio-level risk management.
Enforces position sizing, exposure caps, and correlation constraints.
"""

import pytest
from polymarket_bot.core.risk_manager import PortfolioRiskManager, RiskViolation

class TestPortfolioRiskManager:
    def setup_method(self):
        """Fresh risk manager for each test."""
        self.rm = PortfolioRiskManager(
            max_total_exposure_usd=100.0,
            max_single_position_usd=50.0,
            max_positions=3,
            max_correlated_exposure_usd=80.0,
        )

    def test_accepts_single_position_within_limits(self):
        """A single small position is accepted."""
        violation = self.rm.check_entry(
            asset="ETH",
            proposed_size_usd=30.0,
            correlations={"ETH": 1.0, "BTC": 0.2}
        )
        assert violation is None

    def test_rejects_position_exceeds_single_limit(self):
        """Position larger than max_single_position_usd is rejected."""
        violation = self.rm.check_entry(
            asset="BTC",
            proposed_size_usd=60.0,
            correlations={"BTC": 1.0}
        )
        assert violation is not None
        assert violation.reason == "single_position_limit_exceeded"

    def test_rejects_when_total_exposure_cap_hit(self):
        """Cannot exceed total exposure limit across all positions."""
        self.rm.record_entry("ETH", 40.0)
        self.rm.record_entry("BTC", 30.0)  # total 70
        violation = self.rm.check_entry("PRG_RAIN", 50.0, {})
        assert violation is not None
        assert violation.reason == "total_exposure_cap"

    def test_rejects_correlated_exposure_limit_independent_of_total(self):
        """Correlation-weighted exposure can block even if total cap not hit."""
        self.rm = PortfolioRiskManager(
            max_total_exposure_usd=200.0,
            max_single_position_usd=100.0,
            max_positions=5,
            max_correlated_exposure_usd=80.0,
        )
        self.rm.record_entry("ETH", 50.0)
        # Corr(ETH,BTC)=0.8 → correlated exposure = 50*1.0 + 45*0.8 = 50+36=86 > 80
        violation = self.rm.check_entry(
            asset="BTC",
            proposed_size_usd=45.0,
            correlations={"BTC": 1.0, "ETH": 0.8}
        )
        assert violation is not None
        assert violation.reason == "correlated_exposure_limit"

    def test_accepts_uncorrelated_position_near_cap(self):
        """Uncorrelated asset counts less toward correlated exposure."""
        self.rm.record_entry("ETH", 50.0)
        # RAIN near-zero correlation to ETH
        violation = self.rm.check_entry(
            asset="VIE_RAIN",
            proposed_size_usd=40.0,
            correlations={"VIE_RAIN": 1.0, "ETH": 0.05}
        )
        assert violation is None

    def test_max_positions_count_enforced(self):
        """Cannot open more than max_positions simultaneously."""
        self.rm.record_entry("ETH", 10.0)
        self.rm.record_entry("BTC", 10.0)
        self.rm.record_entry("TAO", 10.0)  # now at max=3
        violation = self.rm.check_entry("HL", 10.0, {})
        assert violation is not None
        assert violation.reason == "max_positions_reached"

    def test_clear_position_on_exit(self):
        """When position exits, exposure is freed."""
        self.rm.record_entry("ETH", 40.0)
        assert self.rm.current_exposure == 40.0
        self.rm.record_exit("ETH", 40.0)
        assert self.rm.current_exposure == 0.0
        assert "ETH" not in self.rm.positions

    def test_zero_or_negative_size_rejected(self):
        """Invalid sizes are rejected."""
        violation = self.rm.check_entry("ETH", 0.0, {})
        assert violation is not None
        assert violation.reason == "invalid_size"
        violation_neg = self.rm.check_entry("ETH", -10.0, {})
        assert violation_neg is not None
        assert violation_neg.reason == "invalid_size"

    def test_get_available_capital(self):
        """Returns remaining capital under total exposure cap."""
        self.rm.record_entry("ETH", 30.0)
        assert self.rm.get_available_capital() == 70.0  # 100 - 30

    def test_correlation_matrix_multiple_positions(self):
        """Correlation weights are summed across all open positions."""
        self.rm = PortfolioRiskManager(
            max_total_exposure_usd=300.0,
            max_single_position_usd=150.0,
            max_positions=5,
            max_correlated_exposure_usd=150.0,
        )
        self.rm.record_entry("ETH", 60.0)
        self.rm.record_entry("BTC", 40.0)  # correlated to ETH at 0.8
        # correlated_exposure so far: 60*1.0 + 40*0.8 = 60+32=92
        # Add ETH2 with corr 0.9 to ETH, 0.8 to BTC: weighted = 30*0.9 + 40*0.8? Wait that's backwards.
        # Actually when checking new asset, we compute:
        #   correlated_sum = proposed_size + sum(existing_size * corr_to_existing)
        # where corr_to_existing is the correlation between the new asset (ETH2) and each existing.
        # So for ETH2=30, corr(ETH2,ETH)=0.9, corr(ETH2,BTC)=0.8
        # Sum = 30 + 60*0.9 + 40*0.8 = 30 + 54 + 32 = 116.  Still < 150 → pass
        v1 = self.rm.check_entry("ETH2", 30.0, {"ETH2": 1.0, "ETH": 0.9, "BTC": 0.8})
        assert v1 is None
        # If ETH2 were recorded, then ETH3 check would include it. Since we don't record, simulate:
        # After ETH2 is hypothetically recorded, positions: ETH=60, BTC=40, ETH2=30
        # Now check ETH3=30 with same correlations: sum = 30 + 60*0.9 + 40*0.8 + 30*0.9 = 30+54+32+27=143 <150
        # To exceed, we need bigger size or more positions. Let's just verify that after recording ETH2, checking a new correlated position fails.
        self.rm.record_entry("ETH2", 30.0)  # Now positions: ETH, BTC, ETH2
        v2 = self.rm.check_entry("ETH3", 30.0, {"ETH3": 1.0, "ETH": 0.9, "BTC": 0.8, "ETH2": 0.9})
        # correlated_sum = 30 + 60*0.9 + 40*0.8 + 30*0.9 = 30+54+32+27 = 143 < 150 — still OK!
        # To trigger fail, increase size or tighten cap
        v3 = self.rm.check_entry("ETH4", 40.0, {"ETH4": 1.0, "ETH": 0.9, "BTC": 0.8, "ETH2": 0.9})
        # Sum = 40 + 54+32+27 = 153 > 150 → should fail
        assert v3 is not None
        assert v3.reason == "correlated_exposure_limit"

    def test_reset_clears_all_state(self):
        """Reset clears all positions and exposure."""
        self.rm.record_entry("ETH", 30.0)
        self.rm.record_entry("BTC", 20.0)
        self.rm.reset()
        assert self.rm.current_exposure == 0.0
        assert len(self.rm.positions) == 0
