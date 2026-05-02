"""
Unit tests for polymarket_bot.monitoring.health.HealthServer.

Tests:
  - Server starts and listens on configured port
  - /health/live returns 200 always
  - /health/ready returns 503 when bot not ready, 200 when ready
  - JSON response structure
"""

import pytest
import asyncio
import aiohttp
from unittest.mock import MagicMock
from polymarket_bot.monitoring.health import HealthServer


class DummyMonitoringConfig:
    # HealthServer uses 8086 in test mode
    health_port = 8086
    health_live_path = "/health/live"
    health_ready_path = "/health/ready"


class DummyBot:
    """Stand-in for TradingBot with minimal attributes."""
    def __init__(self, running=False, client=None, matrices=None):
        self.running = running
        self.client = client
        self.matrices = matrices or []


class DummyClient:
    """Stand-in for PolymarketClient."""
    def __init__(self, connected=True):
        self.connected = connected


@pytest.mark.asyncio
class TestHealthServer:
    """Test HealthServer endpoints."""

    async def test_server_starts(self):
        cfg = DummyMonitoringConfig()
        bot = DummyBot()
        server = HealthServer(cfg, bot)
        await server.start()
        # Server should be listening
        assert server.site is not None
        await server.stop()

    async def test_live_always_200(self):
        cfg = DummyMonitoringConfig()
        bot = DummyBot(running=False)
        server = HealthServer(cfg, bot)
        await server.start()

        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{cfg.health_port}{cfg.health_live_path}") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "ok"
                assert "timestamp" in data

        await server.stop()

    async def test_ready_503_when_bot_not_running(self):
        cfg = DummyMonitoringConfig()
        bot = DummyBot(running=False)
        server = HealthServer(cfg, bot)
        await server.start()

        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{cfg.health_port}{cfg.health_ready_path}") as resp:
                assert resp.status == 503
                data = await resp.json()
                assert data["status"] == "not_ready"
                assert data["reason"] == "exchange_not_connected"

        await server.stop()

    async def test_ready_503_when_client_disconnected(self):
        cfg = DummyMonitoringConfig()
        bot = DummyBot(running=True, client=DummyClient(connected=False))
        server = HealthServer(cfg, bot)
        await server.start()

        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{cfg.health_port}{cfg.health_ready_path}") as resp:
                assert resp.status == 503
                data = await resp.json()
                assert data["reason"] == "exchange_not_connected"

        await server.stop()

    async def test_ready_503_when_no_matrices(self):
        cfg = DummyMonitoringConfig()
        bot = DummyBot(running=True, client=DummyClient(connected=True), matrices=[])
        server = HealthServer(cfg, bot)
        await server.start()

        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{cfg.health_port}{cfg.health_ready_path}") as resp:
                assert resp.status == 503
                data = await resp.json()
                assert data["reason"] == "no_matrices"

        await server.stop()

    async def test_ready_200_when_fully_ready(self):
        cfg = DummyMonitoringConfig()
        bot = DummyBot(running=True, client=DummyClient(connected=True), matrices=[1, 2, 3])
        server = HealthServer(cfg, bot)
        await server.start()

        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{cfg.health_port}{cfg.health_ready_path}") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "ready"
                assert data["matrices"] == 3
                assert data["open_positions"] == 0
                assert "timestamp" in data

        await server.stop()

    async def test_server_stops_cleanly(self):
        cfg = DummyMonitoringConfig()
        bot = DummyBot()
        server = HealthServer(cfg, bot)
        await server.start()
        assert server.site is not None
        await server.stop()
        # After stop, site should be None or closed
        assert server.site is None or server.site._server is None


@pytest.mark.asyncio
class TestHealthJsonFormat:
    """Test JSON response structure."""

    async def test_live_response_keys(self):
        cfg = DummyMonitoringConfig()
        server = HealthServer(cfg, DummyBot())
        await server.start()

        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{cfg.health_port}{cfg.health_live_path}") as resp:
                data = await resp.json()
                assert set(data.keys()) == {"status", "timestamp"}

        await server.stop()

    async def test_ready_response_keys(self):
        cfg = DummyMonitoringConfig()
        bot = DummyBot(running=True, client=DummyClient(connected=True), matrices=[1])
        server = HealthServer(cfg, bot)
        await server.start()

        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{cfg.health_port}{cfg.health_ready_path}") as resp:
                data = await resp.json()
                keys = set(data.keys())
                assert keys >= {"status", "matrices", "open_positions", "timestamp"}

        await server.stop()
