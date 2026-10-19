"""
Indicators for the Lalitha strategy, computed the way TradingView does (owner's charts):

    Supertrend(10, 2)   ATR = Wilder's RMA of the true range; bands on (high + low) / 2 +- 2 x ATR
    RSI(14)             Wilder's smoothing
    Bollinger(20, 2)    SMA 20 +- 2 x population standard deviation
    Pivot (Traditional) from yesterday's daily candle: P = (H + L + C) / 3, R1 = 2P - L, S1 = 2P - H
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float


def _rma(values: Sequence[float], period: int) -> list[Optional[float]]:
    """Wilder's moving average (TradingView ta.rma): seeded with the SMA of the first `period` values."""
    out: list[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    avg = sum(values[:period]) / period
    out[period - 1] = avg
    for i in range(period, len(values)):
        avg = (avg * (period - 1) + values[i]) / period
        out[i] = avg
    return out


def supertrend(bars: Sequence[Bar], period: int = 10, multiplier: float = 2.0) -> list[tuple[Optional[float], int]]:
    """(line, direction) per bar; direction +1 = up (bullish, line below price), -1 = down. TradingView logic."""
    tr = []
    for i, b in enumerate(bars):
        prev_close = bars[i - 1].close if i else b.close
        tr.append(max(b.high - b.low, abs(b.high - prev_close), abs(b.low - prev_close)))
    atr = _rma(tr, period)
    out: list[tuple[Optional[float], int]] = []
    upper = lower = None
    direction = 1
    for i, b in enumerate(bars):
        if atr[i] is None:
            out.append((None, 0))
            continue
        hl2 = (b.high + b.low) / 2
        basic_up, basic_low = hl2 + multiplier * atr[i], hl2 - multiplier * atr[i]
        prev_close = bars[i - 1].close
        new_lower = basic_low if lower is None or basic_low > lower or prev_close < lower else lower
        new_upper = basic_up if upper is None or basic_up < upper or prev_close > upper else upper
        if upper is None:
            direction = 1
        elif direction == -1 and b.close > new_upper:  # (TradingView compares with the updated bands)
            direction = 1
        elif direction == 1 and b.close < new_lower:
            direction = -1
        lower, upper = new_lower, new_upper
        out.append((lower if direction == 1 else upper, direction))
    return out


def rsi(closes: Sequence[float], period: int = 14) -> list[Optional[float]]:
    gains = [0.0] + [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [0.0] + [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    avg_gain, avg_loss = _rma(gains[1:], period), _rma(losses[1:], period)
    out: list[Optional[float]] = [None]
    for g, l in zip(avg_gain, avg_loss):
        if g is None:
            out.append(None)
        elif l == 0:
            out.append(100.0)
        else:
            out.append(100 - 100 / (1 + g / l))
    return out


def bollinger(closes: Sequence[float], period: int = 20, mult: float = 2.0) -> list[Optional[tuple[float, float, float]]]:
    """(lower, middle, upper) per bar."""
    out: list[Optional[tuple[float, float, float]]] = []
    for i in range(len(closes)):
        if i + 1 < period:
            out.append(None)
            continue
        window = closes[i + 1 - period:i + 1]
        mid = sum(window) / period
        sd = math.sqrt(sum((x - mid) ** 2 for x in window) / period)
        out.append((mid - mult * sd, mid, mid + mult * sd))
    return out


def williams_r(bars: Sequence[Bar], period: int = 14) -> list[Optional[float]]:
    """Williams %R: (highest high - close) / (highest high - lowest low) x -100 over `period` bars (0 .. -100)."""
    out: list[Optional[float]] = []
    for i in range(len(bars)):
        if i + 1 < period:
            out.append(None)
            continue
        window = bars[i + 1 - period:i + 1]
        hh, ll = max(b.high for b in window), min(b.low for b in window)
        out.append(-100.0 * (hh - bars[i].close) / (hh - ll) if hh > ll else -50.0)
    return out


def pivots(high: float, low: float, close: float) -> dict[str, float]:
    p = (high + low + close) / 3
    return {"P": p, "R1": 2 * p - low, "S1": 2 * p - high, "R2": p + (high - low), "S2": p - (high - low)}
