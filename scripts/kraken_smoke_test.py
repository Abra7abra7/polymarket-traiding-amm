#!/usr/bin/env python3
"""
Kraken paper-trading smoke test (dry_run).

Replays ~2 days of REAL public Kraken OHLC data (no API keys) through the
Markov/Kelly decision pipeline with simulated paper fills (spread, slippage,
fees from config/config.yaml). No live orders, no real money, submit_order()
stays a stub.

Usage:
    python scripts/kraken_smoke_test.py [--days 2]
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from polymarket_bot.config.loader import load_config
from polymarket_bot.core.decision import DecisionEngine
from polymarket_bot.core.matrix import TransitionMatrix, bin_price
from polymarket_bot.exchange.kraken_client import KrakenClient


def normalize(price: float, lo: float, hi: float) -> float:
    """Min-max scale a raw close to the [0.01, 1.0] probability domain."""
    if hi - lo < 1e-12:
        return 0.5
    return 0.01 + 0.98 * (price - lo) / (hi - lo)


async def run(days: int) -> dict:
    cfg = load_config("config/config.yaml")

    pt = cfg.paper_trading
    th = cfg.trading.thresholds
    mk = cfg.trading.markov

    engine = DecisionEngine(
        tau=th.tau,
        eps=th.eps,
        min_probability=th.min_probability,
        stop_loss_pct=0.02,
        take_profit_pct=th.take_profit_pct,
        kelly_cap_max=cfg.trading.position.kelly.cap_max,
        kelly_cap_min=cfg.trading.position.kelly.cap_min,
        swap_fee=pt.swap_fee_bps / 10000.0,
        gas_cost_usd=pt.gas_fee_usd,
    )

    spread = pt.spread_bps / 10000.0
    slippage = pt.slippage_bps / 10000.0
    initial_balance = pt.initial_balance
    max_daily_trades = cfg.risk.max_daily_trades
    min_transitions = mk.min_transitions
    lookback = 100  # rolling normalization window (candles)

    assets = [("BTC", "15m"), ("BTC", "1h"), ("ETH", "15m"), ("ETH", "1h")]

    kraken = KrakenClient(dry_run=True)
    await kraken.connect()

    balance = initial_balance
    open_positions = {}   # key -> position dict
    total_trades = 0
    wins = 0
    total_pnl = 0.0
    per_asset = {}
    current_day = None
    daily_trades = 0

    try:
        for asset, window in assets:
            key = f"{asset}:{window}"
            candles = await kraken.get_ohlc(asset, window)
            if days * (24 * 60 // int(window[:-1])) < len(candles):
                candles = candles[-(days * (24 * 60 // int(window[:-1]))):]

            closes = [c["close"] for c in candles]
            matrix = TransitionMatrix(
                window_size=mk.window_sizes.get(window, 60),
                n_states=mk.n_states,
                min_transitions=min_transitions,
            )

            for i, candle in enumerate(candles):
                raw = closes[i]
                lo = min(closes[max(0, i - lookback):i + 1])
                hi = max(closes[max(0, i - lookback):i + 1])
                price = normalize(raw, lo, hi)

                ts = candle["time"]
                day = time.strftime("%Y-%m-%d", time.gmtime(ts))
                if day != current_day:
                    current_day = day
                    daily_trades = 0

                # --- exits first ---
                for pos_key in list(open_positions.keys()):
                    pos = open_positions[pos_key]
                    pos["max_price"] = max(pos["max_price"], price)
                    exit_now = None
                    if price <= pos["max_price"] * (1 - th.trailing_stop_pct):
                        exit_now = "trailing_stop"
                    elif price >= pos["entry_price"] * (1 + th.take_profit_pct):
                        exit_now = "take_profit"
                    elif price <= pos["entry_price"] * (1 - 0.02):
                        exit_now = "stop_loss"

                    if exit_now:
                        exit_fill = max(price - spread - slippage, 0.01)
                        pnl = (exit_fill - pos["entry_price"]) * pos["shares"]
                        fees = pos["shares"] * exit_fill * engine.swap_fee + engine.gas_cost_usd
                        balance += pnl - fees
                        total_pnl += pnl - fees
                        total_trades += 1
                        if pnl > 0:
                            wins += 1
                        st = per_asset.setdefault(pos["asset"] + ":" + pos["window"],
                                                  {"trades": 0, "pnl": 0.0})
                        st["trades"] += 1
                        st["pnl"] += pnl - fees
                        del open_positions[pos_key]

                # --- entries ---
                if open_positions:
                    continue
                matrix.update(price, label=key)
                if not matrix.is_valid:
                    continue
                state = bin_price(price, mk.n_states)
                decision, meta = engine.should_enter(matrix.get_matrix(), state, price)
                if not decision or daily_trades >= max_daily_trades:
                    continue

                capital, shares = engine.position_size(
                    portfolio_value=balance, p_hat=meta["p_hat"], market_price=price
                )
                if shares < 1:
                    continue
                notional = shares * price
                if notional > cfg.risk.max_position_size_usd:
                    continue

                entry_fill = min(price + spread + slippage, 1.0)
                open_positions[key] = {
                    "asset": asset, "window": window,
                    "entry_price": entry_fill, "shares": shares,
                    "entry_time": ts, "max_price": price,
                }
                daily_trades += 1
    finally:
        await kraken.disconnect()

    return {
        "initial_balance": initial_balance,
        "final_balance": round(balance, 2),
        "pnl": round(total_pnl, 2),
        "trades": total_trades,
        "wins": wins,
        "win_rate": round(wins / total_trades, 3) if total_trades else 0.0,
        "per_asset": per_asset,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=2)
    args = parser.parse_args()
    result = asyncio.run(run(args.days))
    print(json.dumps(result, indent=2))
