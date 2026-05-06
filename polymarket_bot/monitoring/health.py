"""Health check endpoints for Kubernetes / load balancer probes.

Provides liveness (/health/live) and readiness (/health/ready) checks.
"""

import asyncio
import weakref
from datetime import datetime, timezone
from aiohttp import web
from typing import Dict, Any, Optional


class HealthServer:
    """HTTP health check server running in background thread."""

    _lock = asyncio.Lock()
    _live: Dict[int, Dict[str, Any]] = {}

    def __init__(self, cfg, bot):
        # Resolve port
        port = self._resolve_port(cfg)
        self._port: int = port

        # Resolve endpoint paths
        live_path, ready_path = self._get_paths(cfg)
        self._live_path: str = live_path
        self._ready_path: str = ready_path

        self.bot = bot
        self.app = web.Application()
        self.app.router.add_get(self._live_path, self._handle_live)
        self.app.router.add_get(self._ready_path, self._handle_ready)
        self.app.router.add_get("/health", self._handle_ready)

        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self._finalizer: Optional[weakref.finalize] = None

    @property
    def port(self) -> int:
        """Return the port the server is listening on."""
        return self._port

    @staticmethod
    def _resolve_port(cfg):
        if hasattr(cfg, "health_port"):
            return cfg.health_port
        if hasattr(cfg, "health") and hasattr(cfg.health, "port"):
            return cfg.health.port
        return 8080

    def _get_paths(self, cfg):
        if hasattr(cfg, "health_live_path"):
            live = cfg.health_live_path
        elif hasattr(cfg, "health") and hasattr(cfg.health, "live_path"):
            live = cfg.health.live_path
        else:
            live = "/health/live"
        if hasattr(cfg, "health_ready_path"):
            ready = cfg.health_ready_path
        elif hasattr(cfg, "health") and hasattr(cfg.health, "ready_path"):
            ready = cfg.health.ready_path
        else:
            ready = "/health/ready"
        return live, ready

    async def _handle_live(self, request):
        """Liveness probe — always returns 200 when server is up."""
        return web.json_response(
            {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
        )

    async def _handle_ready(self, request: web.Request) -> web.Response:
        """Liveness probe: check if bot is initialized and connected."""
        # Bot must be running
        if not getattr(self.bot, "running", False):
            return web.json_response(
                {"status": "not_ready", "reason": "exchange_not_connected"},
                status=503,
            )

        # Exchange client must be connected
        client = getattr(self.bot, "client", None)
        if client is not None:
            connected = getattr(client, "connected", False)
            if not connected:
                return web.json_response(
                    {"status": "not_ready", "reason": "exchange_not_connected"},
                    status=503,
                )

        # At least one matrix must be initialized
        matrices = getattr(self.bot, "matrices", {})
        if not matrices:
            return web.json_response(
                {"status": "not_ready", "reason": "no_matrices"}, status=503
            )

        # Ready
        open_positions = len(getattr(self.bot, "positions", {}))
        portfolio_value = getattr(self.bot, "portfolio_value", 0.0)
        daily_trades = getattr(self.bot, "daily_trades_count", 0)
        uptime = str(datetime.now(timezone.utc) - getattr(self.bot, "stats", {}).get("start_time", datetime.now(timezone.utc)))
        
        return web.json_response(
            {
                "status": "ready",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "matrices": len(matrices),
                "open_positions": open_positions,
                "portfolio_value": portfolio_value,
                "daily_trades": daily_trades,
                "uptime": uptime
            }
        )

    async def start(self) -> None:
        """Start HTTP server (non-blocking)."""
        # Clean up any previous server on same port if possible
        if self._port in HealthServer._live:
            prev = HealthServer._live[self._port]
            try:
                p_site = prev.get("site")
                if p_site:
                    await p_site.stop()
            except Exception:
                pass
            try:
                await prev["runner"].cleanup()
            except Exception:
                pass
            HealthServer._live.pop(self._port, None)

        # Create and start new server
        base_port = self._port
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        # Attempt to bind with fallback ports
        for port_offset in range(10):
            current_port = base_port + port_offset
            try:
                self.site = web.TCPSite(self.runner, "0.0.0.0", current_port)
                await self.site.start()
                self._port = current_port
                
                if current_port != base_port:
                    print(f"[Health] Port {base_port} busy, using fallback: {current_port}")
                
                # Write current health port to a file so the runner can find us
                try:
                    port_file = "/root/.trading_bot/health_port"
                    with open(port_file, "w") as f:
                        f.write(str(current_port))
                except: pass
                
                break
            except OSError:
                if port_offset == 9:
                    raise
                continue

        # Register in live map
        HealthServer._live[self._port] = {
            "runner": self.runner,
            "site": self.site,
            "ref": weakref.ref(self),
        }

        # Finalizer will clean up when this object is GC'd
        self._finalizer = weakref.finalize(self, self._cleanup, self._port)

    async def stop(self) -> None:
        """Gracefully stop HTTP server and clear from live registry."""
        entry = HealthServer._live.get(self._port)
        if entry and entry.get("runner") is self.runner:
            # Stop site first
            try:
                if self.site is not None:
                    await self.site.stop()
            except Exception:
                pass
            # Then cleanup runner
            try:
                await self.runner.cleanup()
            except Exception:
                pass
            self.runner = None
            self.site = None
            HealthServer._live.pop(self._port, None)
            # Brief yield to allow loop to close sockets
            await asyncio.sleep(0.05)

    @classmethod
    async def _async_cleanup(cls, port: int) -> None:
        """Async cleanup helper."""
        entry = cls._live.get(port)
        if entry:
            try:
                if entry.get("site") is not None:
                    await entry["site"].stop()
            except Exception:
                pass
            try:
                await entry["runner"].cleanup()
            except Exception:
                pass
            cls._live.pop(port, None)

    @classmethod
    def _cleanup(cls, port: int) -> None:
        """Synchronous finalizer — schedules async cleanup if loop running."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(cls._async_cleanup(port))
            else:
                entry = cls._live.get(port)
                if entry:
                    try:
                        # Best effort sync stop
                        loop.run_until_complete(entry["site"].stop())
                    except Exception:
                        pass
                    try:
                        entry["runner"].cleanup()
                    except Exception:
                        pass
                    cls._live.pop(port, None)
        except Exception:
            pass
