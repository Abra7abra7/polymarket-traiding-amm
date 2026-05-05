"""
Unit tests for polymarket_bot.monitoring.metrics.MetricsExporter.

Tests:
  - Metrics server starts on configured port
  - All metric types exist (Gauge, Counter)
  - Metric values update correctly
  - Label handling (asset, window, error_type)
"""

import pytest
import time
import asyncio
from unittest.mock import patch, MagicMock
from polymarket_bot.monitoring.metrics import MetricsExporter


class DummyMonitoringConfig:
    port = 0
    metrics_path = "/metrics"


class TestMetricsExporterInit:
    """Test exporter initialization."""

    def test_creates_http_server_in_thread(self):
        """The server should start without blocking."""
        cfg = DummyMonitoringConfig()
        exporter = MetricsExporter(cfg)
        # Server thread is daemon — should be alive
        assert exporter is not None
        # Check internal metric objects exist
        assert "portfolio_value" in exporter._metrics
        assert "open_positions" in exporter._metrics
        assert "trades" in exporter._metrics
        assert "p_hat" in exporter._metrics
        assert "errors" in exporter._metrics


@pytest.mark.asyncio
class TestMetricRecording:
    """Test that metric updates work."""

    async def test_portfolio_value_set(self):
        cfg = DummyMonitoringConfig()
        exporter = MetricsExporter(cfg)
        exporter.portfolio_value(12345.67)
        # Get the underlying Prometheus Gauge value
        gauge = exporter._metrics["portfolio_value"]
        assert gauge._value.get() == 12345.67
        await exporter.stop()

    async def test_open_positions_set(self):
        cfg = DummyMonitoringConfig()
        exporter = MetricsExporter(cfg)
        exporter.open_positions(5)
        gauge = exporter._metrics["open_positions"]
        assert gauge._value.get() == 5
        await exporter.stop()

    async def test_trade_counter_inc(self):
        cfg = DummyMonitoringConfig()
        exporter = MetricsExporter(cfg)
        exporter.record_trade(asset="BTC", window="5m", entry_price=50000, shares=10, p_hat=0.7, persist=0.93)
        counter = exporter._metrics["trades"]
        # Get metric value with labels
        assert counter.labels(asset="BTC", window="5m", outcome="YES")._value.get() == 1
        await exporter.stop()

    async def test_p_hat_gauge_updates(self):
        cfg = DummyMonitoringConfig()
        exporter = MetricsExporter(cfg)
        exporter.record_p_hat("ETH", "1h", 0.82)
        gauge = exporter._metrics["p_hat"]
        assert gauge.labels(asset="ETH", window="1h")._value.get() == 0.82
        await exporter.stop()

    async def test_gap_gauge_updates(self):
        cfg = DummyMonitoringConfig()
        exporter = MetricsExporter(cfg)
        exporter.record_gap("BTC", "5m", 0.07)
        gauge = exporter._metrics["gap"]
        assert gauge.labels(asset="BTC", window="5m")._value.get() == 0.07
        await exporter.stop()

    async def test_error_counter_inc(self):
        cfg = DummyMonitoringConfig()
        exporter = MetricsExporter(cfg)
        exporter.record_error("order_failed")
        counter = exporter._metrics["errors"]
        assert counter.labels(error_type="order_failed")._value.get() == 1
        await exporter.stop()

    async def test_multiple_errors_increment(self):
        cfg = DummyMonitoringConfig()
        exporter = MetricsExporter(cfg)
        for _ in range(5):
            exporter.record_error("timeout")
        counter = exporter._metrics["errors"]
        assert counter.labels(error_type="timeout")._value.get() == 5
        await exporter.stop()


@pytest.mark.asyncio
class TestMetricsHttpEndpoint:
    """Test that /metrics HTTP endpoint serves valid Prometheus format."""

    async def test_metrics_endpoint_accessible(self):
        import urllib.request
        import time

        cfg = DummyMonitoringConfig()
        exporter = MetricsExporter(cfg)

        # Wait for server to start
        await asyncio.sleep(0.5)

        url = f"http://127.0.0.1:{exporter.port}{cfg.metrics_path}"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                body = resp.read().decode()
                assert resp.status == 200
                assert "trading_bot_portfolio_value_usd" in body
                assert "trading_bot_open_positions_count" in body
        except Exception as e:
            pytest.fail(f"Metrics server error: {e}")
        finally:
            await exporter.stop()

    async def test_metrics_endpoint_shows_labeled_values(self):
        import urllib.request
        import time

        cfg = DummyMonitoringConfig()
        exporter = MetricsExporter(cfg)
        exporter.record_trade("BTC", "5m", 50000, 10, 0.7, 0.93)

        await asyncio.sleep(0.5)

        url = f"http://127.0.0.1:{exporter.port}{cfg.metrics_path}"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                body = resp.read().decode()
                # Should contain labeled metric
                assert 'trading_bot_trades_total{asset="BTC",outcome="YES",window="5m"}' in body
                assert 'trading_bot_p_hat{asset="BTC",window="5m"} 0.7' in body or \
                       'trading_bot_p_hat{asset="BTC",window="5m"} 0.700000' in body
        finally:
            await exporter.stop()