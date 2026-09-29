"""
Sniper strategy: pure planning and level logic, implemented from PROJECT_STATUS.md
(the single source of truth - if this file and the spec disagree, the spec
wins and this file is the bug).

This module never fetches prices. Every function takes premiums as plain
numbers (or a lookup callable), so the same logic runs unchanged whether the
premiums come from the backtester's Black-Scholes estimates today or from real
broker option data later.

Spec sections implemented here:
  §1 Daily setup  - build_daily_plan()   (ATM, OTM strikes, Sniper, gap check, shifts)
  §2 Entry logic  - trade_setups(), entry_window_for()
  §3 Square rule  - square_levels()
  §4 Limits       - is_sideways(), EXIT_BY, MAX_TRADES_PER_HALF
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Callable, Literal, Optional

OptionType = Literal["CE", "PE"]
Half = Literal["first", "second"]
Direction = Literal["down", "up"]

# (strike, option_type) -> that contract's previous trading day closing premium
PremiumLookup = Callable[[float, OptionType], float]


@dataclass(frozen=True)
class MarketConfig:
    name: str
    strike_step: float  # ATM rounding, OTM distance and shift size (spec §1: 100)
    min_gap: float  # spec §1 gap check
    expiry_weekday: int  # Monday=0. Only used by the backtester's premium estimates - live trading
    # must take the real expiry from the broker's instrument list, not this guess.
    lot_size: int  # checked against Kite's instrument lists 2026-09-28
    max_lots: int  # owner's maximum per trade (spec §7 item 5)
    index_token: int  # the index's instrument token on Kite
    options_exchange: str  # Kite exchange holding the index's option contracts

    @property
    def quantity(self) -> int:
        return self.lot_size * self.max_lots


MARKETS = {
    "NIFTY": MarketConfig(name="NIFTY", strike_step=100, min_gap=25, expiry_weekday=1, lot_size=65, max_lots=5,
                          index_token=256265, options_exchange="NFO"),  # NSE, Tuesday expiry, 325 qty
    "SENSEX": MarketConfig(name="SENSEX", strike_step=100, min_gap=35, expiry_weekday=3, lot_size=20, max_lots=15,
                           index_token=265, options_exchange="BFO"),  # BSE, Thursday expiry, 300 qty
}

MAX_SHIFTS = 3

CANDLE_MINUTES = 5
FIRST_HALF_WINDOW = (time(9, 30), time(12, 0))
SECOND_HALF_WINDOW = (time(12, 30), time(15, 0))
EXIT_BY = time(15, 0)
MAX_TRADES_PER_HALF = 1


# --- §1 Daily setup ---------------------------------------------------------


def nearest_atm(index_close: float, strike_step: float) -> float:
    """Nearest strike-step multiple to the index close. An exact half-way close
    (e.g. 23150) rounds up - Python's round() would round half to even."""
    return math.floor(index_close / strike_step + 0.5) * strike_step


@dataclass(frozen=True)
class StrikeRow:
    """One row of the spec §5 table: the setup evaluated at one ATM candidate."""

    atm_strike: float
    otm_ce_strike: float
    otm_pe_strike: float
    atm_ce_close: float
    atm_pe_close: float
    otm_ce_close: float
    otm_pe_close: float
    sniper: float
    ce_gap: float  # ATM CE close - Sniper
    pe_gap: float  # ATM PE close - Sniper
    ce_ok: bool
    pe_ok: bool


def evaluate_strike(atm_strike: float, market: MarketConfig, premium: PremiumLookup) -> StrikeRow:
    otm_ce_strike = atm_strike + market.strike_step
    otm_pe_strike = atm_strike - market.strike_step
    atm_ce_close = premium(atm_strike, "CE")
    atm_pe_close = premium(atm_strike, "PE")
    otm_ce_close = premium(otm_ce_strike, "CE")
    otm_pe_close = premium(otm_pe_strike, "PE")
    sniper = (otm_ce_close + otm_pe_close) / 2
    ce_gap = atm_ce_close - sniper
    pe_gap = atm_pe_close - sniper
    return StrikeRow(
        atm_strike=atm_strike,
        otm_ce_strike=otm_ce_strike,
        otm_pe_strike=otm_pe_strike,
        atm_ce_close=atm_ce_close,
        atm_pe_close=atm_pe_close,
        otm_ce_close=otm_ce_close,
        otm_pe_close=otm_pe_close,
        sniper=sniper,
        ce_gap=ce_gap,
        pe_gap=pe_gap,
        ce_ok=ce_gap >= market.min_gap,
        pe_ok=pe_gap >= market.min_gap,
    )


@dataclass(frozen=True)
class DailyPlan:
    market: str
    index_close: float
    attempts: tuple[StrikeRow, ...]  # every ATM tried, in order - the first is the nearest ATM
    final: Optional[StrikeRow]  # None -> no plan today
    reason: str


def build_daily_plan(index_close: float, market: MarketConfig, premium: PremiumLookup) -> DailyPlan:
    """Spec §1: start at the nearest ATM; if only the PE gap fails shift ATM up,
    if only the CE gap fails shift ATM down, recalculating each time. Both gaps
    failing on any attempt, or still failing after MAX_SHIFTS shifts, is no plan."""
    atm = nearest_atm(index_close, market.strike_step)
    attempts: list[StrikeRow] = []

    for shift in range(MAX_SHIFTS + 1):
        row = evaluate_strike(atm, market, premium)
        attempts.append(row)

        if row.ce_ok and row.pe_ok:
            return DailyPlan(market.name, index_close, tuple(attempts), row, f"ATM {atm:g} after {shift} shift(s)")
        if not row.ce_ok and not row.pe_ok:
            return DailyPlan(market.name, index_close, tuple(attempts), None, f"both gaps fail at ATM {atm:g}")

        atm += market.strike_step if not row.pe_ok else -market.strike_step

    return DailyPlan(market.name, index_close, tuple(attempts), None, f"still failing after {MAX_SHIFTS} shifts")


# --- §3 Square-number rule --------------------------------------------------


@dataclass(frozen=True)
class SquareLevels:
    trigger: float
    n: int
    entry: int  # n^2 - the square at or above the trigger, never below
    stop_loss: int  # (n-1)^2
    target: int  # (n+2)^2


def square_levels(trigger: float) -> SquareLevels:
    if trigger <= 0:
        raise ValueError(f"trigger must be positive, got {trigger}")
    n = math.isqrt(math.floor(trigger))
    if n * n < trigger:
        n += 1
    return SquareLevels(trigger=trigger, n=n, entry=n * n, stop_loss=(n - 1) ** 2, target=(n + 2) ** 2)


# --- §2 Entry logic ---------------------------------------------------------


@dataclass(frozen=True)
class TradeSetup:
    half: Half
    direction: Direction  # "down": ATM CE falling, buy OTM PE. "up": ATM PE falling, buy OTM CE.
    falling_type: OptionType  # which ATM leg must be below its yesterday close
    buy_strike: float
    buy_type: OptionType
    levels: SquareLevels


def trade_setups(row: StrikeRow) -> list[TradeSetup]:
    """The four possible trades for the day (spec §5's second table)."""
    setups = []
    for half in ("first", "second"):
        for direction in ("down", "up"):
            if direction == "down":
                falling_type, buy_strike, buy_type, falling_close = "CE", row.otm_pe_strike, "PE", row.atm_ce_close
            else:
                falling_type, buy_strike, buy_type, falling_close = "PE", row.otm_ce_strike, "CE", row.atm_pe_close
            trigger = falling_close if half == "first" else row.sniper
            setups.append(TradeSetup(half, direction, falling_type, buy_strike, buy_type, square_levels(trigger)))
    return setups


def candle_close_time(candle_start: datetime) -> time:
    return (candle_start + timedelta(minutes=CANDLE_MINUTES)).time()


def entry_window_for(candle_start: datetime) -> Optional[Half]:
    """Which half's entry window a 5-minute candle falls in, judged by when it
    closes (entries act on candle closes). The 09:30 candle closes at 09:35, so
    the first eligible first-half candle is the one starting 09:30 and the last
    is the one closing at 12:00; likewise 12:30-15:00 for the second half."""
    start = candle_start.time()
    close = candle_close_time(candle_start)
    for half, (window_start, window_end) in (("first", FIRST_HALF_WINDOW), ("second", SECOND_HALF_WINDOW)):
        if start >= window_start and close <= window_end:
            return half
    return None


# --- §4 Limits --------------------------------------------------------------


def is_sideways(current: dict[str, float], previous_close: dict[str, float]) -> bool:
    """All four strikes (keys: atm_ce, atm_pe, otm_ce, otm_pe) trading below
    their yesterday close."""
    return all(current[key] < previous_close[key] for key in ("atm_ce", "atm_pe", "otm_ce", "otm_pe"))


def previous_closes(row: StrikeRow) -> dict[str, float]:
    return {
        "atm_ce": row.atm_ce_close,
        "atm_pe": row.atm_pe_close,
        "otm_ce": row.otm_ce_close,
        "otm_pe": row.otm_pe_close,
    }
