"""Regression tests for the Kraken price normalisation fix (bug 2026-11-01).

Live wall-clock run failed 1351× with "price must be in (0, 1]": raw Kraken
prices (BTC ~ 70 000 USD) were fed straight into DecisionEngine.should_enter,
which requires a probability in (0, 1]. The fix normalises get_ticker output
into [0.01, 0.99] over a rolling min-max window — the same method validated by
scripts/kraken_smoke_test.py.
"""
import numpy as np
import pytest

from polymarket_bot.core.decision import DecisionEngine
from polymarket_bot.core.matrix import bin_price
from polymarket_bot.core.matrix import TransitionMatrix
from polymarket_bot.exchange.kraken_client import KrakenClient


def make_closes(closes):
    """Build an OHLC-shaped candle list like KrakenClient.get_ohlc returns."""
    return [
        {"time": 1700000000 + i * 900, "open": c, "high": c, "low": c, "close": c, "vwap": c, "volume": 1.0, "count": 10}
        for i, c in enumerate(closes)
    ]


@pytest.fixture
def client(monkeypatch):
    kc = KrakenClient(dry_run=True)
    # stub network: get_ohlc returns whatever the test sets on the client
    history = {"closes": [60000.0 + 100 * i for i in range(100)]}

    async def fake_get_ohlc(asset, window, count=720):
        closes = history["closes"][-count:]
        return make_closes(closes)

    monkeypatch.setattr(kc, "get_ohlc", fake_get_ohlc)
    kc._test_history = history
    return kc


class TestNormalizationDomain:
    @pytest.mark.asyncio
    async def test_normalized_price_in_valid_domain(self, client):
        """get_ticker must return a probability in (0, 1], not a raw USD price."""
        price = await client.get_ticker("BTC", "15m")
        assert 0 < price <= 1.0
        assert price != pytest.approx(60000, abs=1000)

    @pytest.mark.asyncio
    async def test_decision_engine_accepts_normalized_price(self, client):
        """Full entry path that crashed in production must succeed now."""
        price = await client.get_ticker("BTC", "15m")
        matrix = TransitionMatrix(window_size=12, n_states=20, min_transitions=2)
        for _ in range(30):
            matrix.update(price, label="BTC:15m")
        de = DecisionEngine(tau=0.05, eps=0.01, min_probability=0.01)
        # must NOT raise ValueError("price must be in (0, 1]")
        decision, meta = de.should_enter(matrix.get_matrix(), bin_price(price), price)
        assert isinstance(decision, bool)
        assert "p_hat" in meta

    @pytest.mark.asyncio
    async def test_raw_price_still_fails_engine(self):
        """Guard: the raw-USD path is the bug we fixed — keep it detectable."""
        de = DecisionEngine(tau=0.05, eps=0.01, min_probability=0.01)
        with pytest.raises(ValueError, match="price must be in \\(0, 1\\]"):
            de.should_enter(
                np.full((20, 20), 0.5), bin_price(70000.0), 70000.0
            )


class TestRollingWindow:
    @pytest.mark.asyncio
    async def test_window_seeded_from_history(self, client):
        await client.get_ticker("BTC", "15m")
        win = client._price_windows["BTC:15m"]
        assert len(win) == client.normalization_lookback
        assert win[-1] == client._test_history["closes"][-1]

    @pytest.mark.asyncio
    async def test_window_rolls_and_tracks_new_price(self, client):
        await client.get_ticker("BTC", "15m")
        before = list(client._price_windows["BTC:15m"])
        client._test_history["closes"] = client._test_history["closes"] + [61000.0]
        await client.get_ticker("BTC", "15m")
        after = client._price_windows["BTC:15m"]
        assert after[-1] == 61000.0
        assert after[:-1] == before[1:]

    @pytest.mark.asyncio
    async def test_constant_window_returns_midpoint(self, client):
        client._test_history["closes"] = [70000.0] * 100
        price = await client.get_ticker("BTC", "15m")
        assert price == 0.5

    @pytest.mark.asyncio
    async def test_ascending_history_maps_low_to_min(self, client):
        price = await client.get_ticker("BTC", "15m")
        # ascending closes: the newest price is the max → maps to ~0.99
        assert price == pytest.approx(0.99)

    @pytest.mark.asyncio
    async def test_normalize_disabled_returns_raw(self, monkeypatch):
        kc = KrakenClient(dry_run=True, normalize_prices=False)

        async def fake_get_ohlc(asset, window, count=720):
            return make_closes([70000.0])

        monkeypatch.setattr(kc, "get_ohlc", fake_get_ohlc)
        assert await kc.get_ticker("BTC", "15m") == 70000.0

    @pytest.mark.asyncio
    async def test_windows_are_per_asset(self, client):
        await client.get_ticker("BTC", "15m")
        await client.get_ticker("ETH", "1h")
        assert "BTC:15m" in client._price_windows
        assert "ETH:1h" in client._price_windows
