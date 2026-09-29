"""
HLC strategy: pure level and candlestick logic (rules in PROJECT_STATUS.md,
"HLC strategy"). No data access - premiums and candles come in as numbers.

Morning:
  - ATM = the strike near yesterday's index close whose CE and PE closes are
    nearest each other (choose_atm).
  - Levels from that ATM's CE/PE closes: R1 = ATM + CE, R2 = ATM + (CE+PE),
    R3 = R2 + CE; S1 = ATM - PE, S2 = ATM - (CE+PE), S3 = S2 - PE; plus
    Close = yesterday's index close.
  - Each leg's label: close nearer its high = PANIC, nearer its low =
    PROFIT BOOKING (information only).
Intraday (5-minute candles): candlestick patterns at the levels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Optional, Sequence

OptionType = Literal["CE", "PE"]


@dataclass(frozen=True)
class HlcMarket:
    name: str
    strike_step: int  # option strike interval
    level_tolerance: float  # how close to a level a pattern must form (index points)
    quantity: int
    sl_points: float  # stop loss = entry premium - this (owner, 2026-09-29)
    big_gap: float  # |open - yesterday's close| at least this = big gap day (owner: NIFTY 150-200, SENSEX 300-500)


HLC_MARKETS = {
    "NIFTY": HlcMarket("NIFTY", strike_step=50, level_tolerance=15, quantity=325, sl_points=25, big_gap=150),
    "SENSEX": HlcMarket("SENSEX", strike_step=100, level_tolerance=50, quantity=300, sl_points=50, big_gap=300),
}


# --- Morning plan -----------------------------------------------------------


def choose_atm(index_price: float, step: int, premium: Callable[[float, OptionType], Optional[float]],
               search: int = 6) -> Optional[float]:
    """Strike within +-`search` steps of index_price whose CE and PE prices are
    nearest each other. `premium` returns None for a strike that isn't listed."""
    nearest = round(index_price / step) * step
    best, best_gap = None, None
    for i in range(-search, search + 1):
        strike = nearest + i * step
        ce, pe = premium(strike, "CE"), premium(strike, "PE")
        if ce is None or pe is None:
            continue
        gap = abs(ce - pe)
        if best_gap is None or gap < best_gap or (gap == best_gap and abs(strike - index_price) < abs(best - index_price)):
            best, best_gap = strike, gap
    return best


@dataclass(frozen=True)
class HlcLevels:
    close: float  # yesterday's index close
    atm: float
    ce_close: float
    pe_close: float
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float

    def ladder(self) -> list[tuple[str, float]]:
        """All levels, lowest first."""
        return sorted([("S3", self.s3), ("S2", self.s2), ("S1", self.s1), ("Close", self.close),
                       ("R1", self.r1), ("R2", self.r2), ("R3", self.r3)], key=lambda x: x[1])


def hlc_levels(index_close: float, atm: float, ce_close: float, pe_close: float) -> HlcLevels:
    both = ce_close + pe_close
    r2, s2 = atm + both, atm - both
    return HlcLevels(close=index_close, atm=atm, ce_close=ce_close, pe_close=pe_close,
                     r1=round(atm + ce_close, 2), r2=round(r2, 2), r3=round(r2 + ce_close, 2),
                     s1=round(atm - pe_close, 2), s2=round(s2, 2), s3=round(s2 - pe_close, 2))


def leg_label(high: float, low: float, close: float) -> str:
    return "PANIC" if (high - close) < (close - low) else "PROFIT BOOKING"


# --- Candlestick patterns ---------------------------------------------------


@dataclass(frozen=True)
class Candle:
    open: float
    high: float
    low: float
    close: float

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def upper(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def green(self) -> bool:
        return self.close > self.open

    @property
    def red(self) -> bool:
        return self.close < self.open


# Textbook definitions (owner to review against real charts):
DOJI_BODY = 0.1  # body <= 10% of range
SPINNING_BODY = 0.3  # body <= 30% of range, both wicks at least the body
HAMMER_WICK = 2.0  # long wick >= 2x body, other wick <= 10% of range
STAR_BODY = 0.3  # morning/evening star middle candle body <= 30% of the first body


def is_doji(c: Candle) -> bool:
    return c.range > 0 and c.body <= DOJI_BODY * c.range


def is_spinning_top(c: Candle) -> bool:
    return c.range > 0 and DOJI_BODY * c.range < c.body <= SPINNING_BODY * c.range and c.upper >= c.body and c.lower >= c.body


def _hammer_shape(c: Candle) -> bool:
    return c.range > 0 and c.lower >= HAMMER_WICK * max(c.body, 0.01) and c.upper <= 0.1 * c.range


def is_hammer(c: Candle) -> bool:  # at support
    return _hammer_shape(c)


def is_hanging_man(c: Candle) -> bool:  # same shape, at resistance
    return _hammer_shape(c)


def is_bullish_engulfing(prev: Candle, c: Candle) -> bool:
    return prev.red and c.green and c.open <= prev.close and c.close >= prev.open and c.body > prev.body


def is_bearish_engulfing(prev: Candle, c: Candle) -> bool:
    return prev.green and c.red and c.open >= prev.close and c.close <= prev.open and c.body > prev.body


def is_bullish_harami(prev: Candle, c: Candle) -> bool:
    return prev.red and c.green and c.open >= prev.close and c.close <= prev.open and c.body < prev.body


def is_bearish_harami(prev: Candle, c: Candle) -> bool:
    return prev.green and c.red and c.open <= prev.close and c.close >= prev.open and c.body < prev.body


def is_morning_star(a: Candle, b: Candle, c: Candle) -> bool:
    return (a.red and a.body > 0 and b.body <= STAR_BODY * a.body and c.green
            and c.close >= (a.open + a.close) / 2)


def is_evening_star(a: Candle, b: Candle, c: Candle) -> bool:
    return (a.green and a.body > 0 and b.body <= STAR_BODY * a.body and c.red
            and c.close <= (a.open + a.close) / 2)


DIRECTIONLESS = ("Doji", "Spinning Top")  # count for entries at a level, not as a "pattern changed" exit


def bullish_pattern(candles: Sequence[Candle]) -> Optional[tuple[str, int]]:
    """Name of a support (up-reversal) pattern ending on the last candle, and how
    many candles it spans; None if none. Owner's list: Morning Star, Hammer,
    Bullish Engulfing, Bullish Harami, plus Doji / Spinning Top at a level."""
    if not candles:
        return None
    c = candles[-1]
    if len(candles) >= 3 and is_morning_star(*candles[-3:]):
        return "Morning Star", 3
    if len(candles) >= 2 and is_bullish_engulfing(candles[-2], c):
        return "Bullish Engulfing", 2
    if len(candles) >= 2 and is_bullish_harami(candles[-2], c):
        return "Bullish Harami", 2
    if is_hammer(c):
        return "Hammer", 1
    if is_doji(c):
        return "Doji", 1
    if is_spinning_top(c):
        return "Spinning Top", 1
    return None


def bearish_pattern(candles: Sequence[Candle]) -> Optional[tuple[str, int]]:
    """Resistance (down-reversal) patterns: Evening Star, Bearish Engulfing,
    Bearish Harami, Hanging Man, Spinning Top, Doji."""
    if not candles:
        return None
    c = candles[-1]
    if len(candles) >= 3 and is_evening_star(*candles[-3:]):
        return "Evening Star", 3
    if len(candles) >= 2 and is_bearish_engulfing(candles[-2], c):
        return "Bearish Engulfing", 2
    if len(candles) >= 2 and is_bearish_harami(candles[-2], c):
        return "Bearish Harami", 2
    if is_hanging_man(c):
        return "Hanging Man", 1
    if is_doji(c):
        return "Doji", 1
    if is_spinning_top(c):
        return "Spinning Top", 1
    return None
