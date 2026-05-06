"""
Prometheus metrics exporter for the trading bot.

Runs a lightweight HTTP server exposing /metrics for monitoring.
"""

import socketserver
import threading
import weakref
import asyncio
from http.server import BaseHTTPRequestHandler
from typing import Dict, Any
from prometheus_client import generate_latest, CollectorRegistry, Gauge, Counter


class _MetricsHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler serving /metrics in Prometheus text format."""

    def do_GET(self) -> None:
        if self.path == '/metrics':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.end_headers()
            # self.server.registry is set by MetricsExporter
            self.wfile.write(generate_latest(self.server.registry))
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Not Found. Use /metrics for Prometheus data.")

    def log_message(self, fmt, *args):
        pass  # Suppress request logs – noisy in tests


class MetricsExporter:
    """
    Exports metrics via HTTP.

    Manages a global registry of live exporters to avoid port conflicts
    in long-running processes (e.g., test suites).
    """

    _lock = threading.Lock()
    _live: Dict[int, Dict[str, Any]] = {}  # port -> {thread, server, ref}

    def __init__(self, cfg):
        # Registry for this exporter
        self.registry = CollectorRegistry()

        # Metric objects
        self._metrics: Dict[str, Any] = {}
        self._metrics["portfolio_value"] = Gauge(
            "trading_bot_portfolio_value_usd", "Current total portfolio value in USD",
            registry=self.registry
        )
        self._metrics["open_positions"] = Gauge(
            "trading_bot_open_positions_count", "Number of currently open positions",
            registry=self.registry
        )
        self._metrics["trades"] = Counter(
            "trading_bot_trades_total", "Total number of trades executed",
            ["asset", "window", "outcome"], registry=self.registry
        )
        self._metrics["p_hat"] = Gauge(
            "trading_bot_p_hat", "Model-estimated probability for last trade",
            ["asset", "window"], registry=self.registry
        )
        self._metrics["gap"] = Gauge(
            "trading_bot_gap", "Observed gap between p_hat and market price",
            ["asset", "window"], registry=self.registry
        )
        self._metrics["errors"] = Counter(
            "trading_bot_errors_total", "Total number of errors encountered",
            ["error_type"], registry=self.registry
        )

        # Markov matrix health metrics
        self._metrics["matrix_transitions"] = Gauge(
            "trading_bot_matrix_transitions_total",
            "Total number of state transitions recorded in the Markov matrix",
            ["asset", "window"], registry=self.registry
        )
        self._metrics["matrix_valid"] = Gauge(
            "trading_bot_matrix_valid",
            "Whether the transition matrix is currently valid (1) or not (0)",
            ["asset", "window"], registry=self.registry
        )
        self._metrics["matrix_diag_mean"] = Gauge(
            "trading_bot_matrix_diagonal_mean",
            "Mean value of diagonal elements in the transition matrix",
            ["asset", "window"], registry=self.registry
        )
        # Paper trading metrics
        self._metrics["paper_trades_total"] = Counter(
            "trading_bot_paper_trades_total", "Total number of paper trades executed",
            ["asset", "side", "type"], registry=self.registry
        )
        self._metrics["paper_pnl_usd"] = Gauge(
            "trading_bot_paper_pnl_usd", "Cumulative realized P&L from paper trading", registry=self.registry
        )
        self._metrics["paper_unrealized_pnl"] = Gauge(
            "trading_bot_paper_unrealized_pnl_usd", "Unrealized P&L from open paper positions", registry=self.registry
        )
        self._metrics["paper_positions"] = Gauge(
            "trading_bot_paper_positions_count", "Number of open paper positions", registry=self.registry
        )
        self._metrics["paper_fill_rate"] = Gauge(
            "trading_bot_paper_fill_rate", "Fraction of paper orders that were filled", registry=self.registry
        )

        # Resolve port (flat or nested)
        base_port = self._resolve_port(cfg)
        self._port = base_port

        # Attempt to bind with fallback ports if original is taken
        for port_offset in range(10):  # Try 10 consecutive ports
            current_port = base_port + port_offset
            with MetricsExporter._lock:
                if current_port in MetricsExporter._live:
                    prev = MetricsExporter._live[current_port]
                    try: prev['server'].shutdown()
                    except: pass
                    try: prev['server'].server_close()
                    except: pass
                    MetricsExporter._live.pop(current_port, None)

                try:
                    self._server = socketserver.TCPServer(("0.0.0.0", current_port), _MetricsHandler, bind_and_activate=False)
                    self._server.allow_reuse_address = True
                    self._server.server_bind()
                    self._server.server_activate()
                    self._port = current_port
                    self._server.registry = self.registry
                    
                    if current_port != base_port:
                        print(f"[Metrics] Port {base_port} busy, using fallback: {current_port}")
                    break 
                except OSError as e:
                    if port_offset == 9: # Last attempt
                        raise RuntimeError(f"Metrics server failed to bind after 10 attempts: {e}") from e
                    continue

        # Finalizer – runs when this instance is GC'd
        self._finalizer = weakref.finalize(self, self._cleanup, self._port)

    @property
    def port(self) -> int:
        """Return the port the server is listening on."""
        return self._port

    @staticmethod
    def _resolve_port(cfg) -> int:
        # Prefer nested metrics.port; fallback to top-level port; default 9090
        if hasattr(cfg, 'metrics') and hasattr(cfg.metrics, 'port'):
            return cfg.metrics.port
        return getattr(cfg, 'port', 9090)

    def record_paper_trade(self, asset: str, side: str, trade_type: str) -> None:
        self._metrics["paper_trades_total"].labels(asset=asset, side=side, type=trade_type).inc()

    def record_paper_pnl(self, realized: float, unrealized: float) -> None:
        self._metrics["paper_pnl_usd"].set(realized)
        self._metrics["paper_unrealized_pnl"].set(unrealized)

    def record_paper_positions(self, count: int) -> None:
        self._metrics["paper_positions"].set(count)

    def record_paper_fill_rate(self, rate: float) -> None:
        self._metrics["paper_fill_rate"].set(rate)

    @classmethod
    def _cleanup(cls, port: int) -> None:
        """Synchronous finalizer – schedule async cleanup if loop running."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(cls._async_cleanup(port))
            else:
                entry = cls._live.get(port)
                if entry:
                    try:
                        entry['server'].shutdown()
                    except Exception:
                        pass
                    try:
                        entry['thread'].join(timeout=2.0)
                    except Exception:
                        pass
                    try:
                        entry['server'].server_close()
                    except Exception:
                        pass
                    cls._live.pop(port, None)
        except Exception:
            pass
    # Convenience methods
    def portfolio_value(self, value_usd: float) -> None:
        self._metrics["portfolio_value"].set(value_usd)

    def open_positions(self, count: int) -> None:
        self._metrics["open_positions"].set(count)

    def record_trade(self, asset: str, window: str, entry_price: float, shares: int, p_hat: float, persist: float) -> None:
        self._metrics["trades"].labels(asset=asset, window=window, outcome="YES").inc()
        # Also record the model probability for monitoring
        self.record_p_hat(asset, window, p_hat)

    def record_p_hat(self, asset: str, window: str, value: float) -> None:
        self._metrics["p_hat"].labels(asset=asset, window=window).set(value)

    def record_gap(self, asset: str, window: str, value: float) -> None:
        self._metrics["gap"].labels(asset=asset, window=window).set(value)

    def record_error(self, error_type: str) -> None:
        self._metrics["errors"].labels(error_type=error_type).inc()

    def record_matrix_stats(self, asset: str, window: str, transitions: int, valid: bool, diag_mean: float = 0.0) -> None:
        self._metrics["matrix_transitions"].labels(asset=asset, window=window).set(transitions)
        self._metrics["matrix_valid"].labels(asset=asset, window=window).set(1 if valid else 0)
        self._metrics["matrix_diag_mean"].labels(asset=asset, window=window).set(diag_mean)

    async def stop(self) -> None:
        """Gracefully shut down the HTTP server and clean up."""
        # Idempotent: if already stopped, return
        if not hasattr(self, "_server") or self._server is None:
            return

        # Signal shutdown to stop the serve_forever loop
        try:
            self._server.shutdown()
        except Exception:
            pass

        # Close the listening socket immediately to unblock accept()
        try:
            self._server.server_close()
        except Exception:
            pass

        # Wait for the thread to exit
        if hasattr(self, "_thread") and self._thread.is_alive():
            try:
                self._thread.join(timeout=2.0)
            except Exception:
                pass

        # Remove from live registry
        with self._lock:
            MetricsExporter._live.pop(self._port, None)

        # Detach finalizer to avoid double cleanup
        if hasattr(self, "_finalizer"):
            self._finalizer.detach()

        self._server = None
        self._thread = None
