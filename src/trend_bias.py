"""
Minimal, independent daily trend-bias calculation for the SPFS strategy.

This is a deliberately small extraction (not an import) of the EMA20/EMA50
trend rule originally developed in the sibling "share-market-bro" project's
signal_engine.py. Kept as its own tiny module here - rather than depending on
that project's much larger signal_engine.py (which also has RSI/Fibonacci/
candlestick confluence logic SPFS doesn't use) - so this project has no
runtime dependency on the other one at all.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

EMA_FAST_PERIOD = 20
EMA_SLOW_PERIOD = 50
TREND_NEUTRAL_BAND_PCT = 0.001  # EMA20/EMA50 within 0.1% of each other -> no clear trend


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False).mean()


def daily_trend_bias(daily_df: pd.DataFrame) -> Literal["bullish", "bearish", "neutral"]:
    """EMA(20) vs EMA(50) on daily closes, as of the last row in daily_df.

    Contract: daily_df must contain only days strictly BEFORE the day being
    traded, sorted ascending by date - this is what makes the trend read
    legitimate (it can only see what was actually known before today).
    """
    closes = daily_df["close"]
    ema_fast = ema(closes, EMA_FAST_PERIOD).iloc[-1]
    ema_slow = ema(closes, EMA_SLOW_PERIOD).iloc[-1]

    if abs(ema_fast - ema_slow) / ema_slow <= TREND_NEUTRAL_BAND_PCT:
        return "neutral"
    return "bullish" if ema_fast > ema_slow else "bearish"
