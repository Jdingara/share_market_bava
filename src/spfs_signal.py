"""
SPFS strategy: pure setup/level logic (ATM lock, Sniper level, Square Numbers).

Reconciled from two conflicting user-provided strategy write-ups (2026-07-26) -
see PROJECT_STATUS.md for the full reconciliation history. This module only
computes the day's setup and the pure math rules; spfs_backtester.py does the
day-by-day candle walk that actually applies them.

v1 scope, deliberately narrower than the original discussion (see
PROJECT_STATUS.md): no fake-breakout/reversal retry path - a day either
confirms and trades, or it doesn't trade at all.

Contract (same no-lookahead discipline as trend_bias.daily_trend_bias):
  - `daily_history` passed to build_daily_setup() must contain only days
    strictly BEFORE the day being traded, sorted ascending by date.
  - `day_open_spot` is that day's actual opening spot price.

ATM selection (corrected 2026-07-27, see PROJECT_STATUS.md): the ATM strike is
based on the PREVIOUS trading day's closing index value, not today's open -
e.g. previous close 23922 -> ATM 23900 (nearest_strike rounding). Today's
actual open is only used to check for the huge-gap exception (see
lock_atm_strike's docstring).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Optional

import pandas as pd

from options_pricing import (
    NIFTY_STRIKE_INTERVAL,
    black_scholes_price,
    historical_volatility,
    nearest_strike,
    next_weekly_expiry,
)
from trend_bias import daily_trend_bias

SNIPER_LEVEL_FRACTION = 0.70  # Sniper level = 70% of the ATM contract's previous-close premium (a 30% drop)
SQUARE_INTERVAL = 20.0  # "Square Number" grid applied to the OTM contract's premium, in points
STOP_LOSS_SQUARES = 1  # stop-loss = entry_square - 1 * SQUARE_INTERVAL
TARGET_SQUARES = 2  # target = entry_square + 2 * SQUARE_INTERVAL (fixed - see PROJECT_STATUS.md's
# trailing-stop finding, carried over from the sibling project, for why a fixed target - not a
# momentum-based extension - is used)
VOLATILITY_WINDOW = 20

MARKET_CLOSE_HOUR_MINUTE = (15, 30)
SECONDS_PER_YEAR = 365 * 24 * 3600
_SQUARE_TOLERANCE_REL = 1e-9


def time_to_expiry_years(as_of: datetime, expiry_date: date) -> float:
    hour, minute = MARKET_CLOSE_HOUR_MINUTE
    expiry_dt = datetime.combine(expiry_date, datetime.min.time().replace(hour=hour, minute=minute))
    as_of_naive = as_of.replace(tzinfo=None)
    return max((expiry_dt - as_of_naive).total_seconds(), 0.0) / SECONDS_PER_YEAR


ATM_GAP_THRESHOLD = NIFTY_STRIKE_INTERVAL  # a gap of one full strike interval (50pts) or more
# between today's actual open and the previous-close-based ATM triggers the "huge gap" override
ATM_SEARCH_RADIUS_STRIKES = 3  # per the user's own worked example: check up to 3 strikes above and
# 3 below the initial nearest-strike estimate for the one where CE and PE close values are closest


def _closest_ce_pe_strike(
    center_strike: float,
    reference_spot: float,
    tte: float,
    volatility: float,
    radius: int = ATM_SEARCH_RADIUS_STRIKES,
) -> float:
    """The 'true' ATM: among the strikes within `radius` of center_strike, the one
    whose CE and PE premiums (both priced off reference_spot/tte/volatility) are
    closest to each other - the standard put-call-parity definition of ATM, not
    just the strike nearest to spot. Ties broken by proximity to center_strike."""
    best_strike, best_gap = center_strike, None
    for i in range(-radius, radius + 1):
        strike = center_strike + i * NIFTY_STRIKE_INTERVAL
        ce = black_scholes_price(reference_spot, strike, tte, volatility, "CE")
        pe = black_scholes_price(reference_spot, strike, tte, volatility, "PE")
        gap = abs(ce - pe)
        if best_gap is None or gap < best_gap - 1e-9 or (
            abs(gap - best_gap) <= 1e-9 and abs(strike - center_strike) < abs(best_strike - center_strike)
        ):
            best_gap, best_strike = gap, strike
    return best_strike


def lock_atm_strike(previous_close_spot: float, day_open_spot: float, previous_tte: float, volatility: float) -> float:
    """The day's ATM strike, locked before today's session and never re-picked
    intraday.

    Primary rule (2026-07-27, refined per the user's own worked example): NOT
    just nearest_strike() rounding - starting from that as a center point,
    search the strikes within ATM_SEARCH_RADIUS_STRIKES of it and pick whichever
    has the previous day's closest CE/PE closing premiums (e.g. previous close
    23922 -> initial estimate 23900, then the closest-CE/PE-gap search may confirm
    or shift that - the user's own example shifted it to 24000).

    Huge gap exception: if today's actual open has moved a full strike interval
    or more away from that ATM, the stale one is discarded in favor of simple
    nearest_strike() rounding of today's actual open (e.g. yesterday's ATM
    24250, today opens at 24580 -> new ATM 24600) - deliberately NOT re-run
    through the CE/PE-gap search, since that search is only meaningful using
    previous-close pricing near where the previous close actually was; a gap
    scenario means today's open sits far outside where that pricing means
    anything, so refining "around today's open using yesterday's prices" would
    just walk to whichever edge of the search window happens to be nearest
    yesterday's close - not a real refinement."""
    provisional_center = nearest_strike(previous_close_spot)
    provisional_atm = _closest_ce_pe_strike(provisional_center, previous_close_spot, previous_tte, volatility)

    if abs(day_open_spot - provisional_atm) >= ATM_GAP_THRESHOLD:
        return nearest_strike(day_open_spot)
    return provisional_atm


def option_type_for_trend(trend: Literal["bullish", "bearish", "neutral"]) -> Optional[Literal["CE", "PE"]]:
    if trend == "bullish":
        return "CE"
    if trend == "bearish":
        return "PE"
    return None


def otm_strike_for(atm_strike: float, option_type: Literal["CE", "PE"]) -> float:
    """Same option type as ATM, one strike further out of the money."""
    return atm_strike + NIFTY_STRIKE_INTERVAL if option_type == "CE" else atm_strike - NIFTY_STRIKE_INTERVAL


def sniper_level(atm_previous_close_premium: float, fraction: float = SNIPER_LEVEL_FRACTION) -> float:
    return atm_previous_close_premium * fraction


def _round_to_grid(value: float, interval: float, direction: Literal["up", "down"]) -> float:
    quotient = value / interval
    nearest_int = round(quotient)
    if math.isclose(quotient, nearest_int, rel_tol=_SQUARE_TOLERANCE_REL, abs_tol=1e-9):
        return nearest_int * interval
    rounded = math.ceil(quotient) if direction == "up" else math.floor(quotient)
    return rounded * interval


def next_square(value: float, interval: float = SQUARE_INTERVAL) -> float:
    """Next Square Number at or above value - an exact multiple of `interval`
    stays itself (float-noise-safe: values within floating point error of an
    exact multiple are treated as already on the grid)."""
    return _round_to_grid(value, interval, "up")


def previous_square(value: float, interval: float = SQUARE_INTERVAL) -> float:
    """Symmetric mirror of next_square(): the Square Number at or below value."""
    return _round_to_grid(value, interval, "down")


def trade_levels(entry_square: float, interval: float = SQUARE_INTERVAL) -> tuple[float, float]:
    """(stop_loss, target) for a trade entered at entry_square."""
    return entry_square - STOP_LOSS_SQUARES * interval, entry_square + TARGET_SQUARES * interval


def is_confirmed(
    atm_premium: float,
    otm_premium: float,
    sniper_level_value: float,
    atm_previous_close_premium: float,
) -> bool:
    """OTM confirmation: ATM premium has decayed to/through the Sniper level
    (rule uses <=) AND the OTM premium has genuinely broken out past what the
    ATM contract was worth at yesterday's close (rule uses strict >)."""
    return atm_premium <= sniper_level_value and otm_premium > atm_previous_close_premium


@dataclass
class SpfsSetup:
    trend: Literal["bullish", "bearish", "neutral"]
    option_type: Optional[Literal["CE", "PE"]]
    atm_strike: Optional[float]
    otm_strike: Optional[float]
    expiry: Optional[date]
    volatility: Optional[float]
    atm_previous_close_premium: Optional[float]
    sniper_level: Optional[float]
    reasoning: str


def build_daily_setup(daily_history: pd.DataFrame, day_open_spot: float, trade_date: date) -> SpfsSetup:
    """Builds the day's locked SPFS setup. `daily_history` must contain only
    days strictly before `trade_date` (same no-lookahead contract as
    trend_bias.daily_trend_bias)."""
    trend = daily_trend_bias(daily_history)
    option_type = option_type_for_trend(trend)

    if option_type is None:
        return SpfsSetup(
            trend=trend,
            option_type=None,
            atm_strike=None,
            otm_strike=None,
            expiry=None,
            volatility=None,
            atm_previous_close_premium=None,
            sniper_level=None,
            reasoning="No clear daily trend bias (EMA20/EMA50 too close) - no ATM locked, no trade today",
        )

    previous_day = daily_history.iloc[-1]
    previous_close_spot = previous_day["close"]

    # Expiry resolved from today's date (not yesterday's) so the ATM/OTM contract
    # identity - strike + expiry - is fixed and singular for the whole day; using
    # yesterday's date could disagree with today's actual expiry right around a
    # Monday/Tuesday boundary.
    expiry = next_weekly_expiry(trade_date)
    volatility = historical_volatility(daily_history["close"], window=VOLATILITY_WINDOW)
    previous_close_time = pd.Timestamp(previous_day["date"]).to_pydatetime()
    previous_tte = time_to_expiry_years(previous_close_time, expiry)

    atm_strike = lock_atm_strike(previous_close_spot, day_open_spot, previous_tte, volatility)
    otm_strike = otm_strike_for(atm_strike, option_type)
    atm_previous_close_premium = black_scholes_price(
        previous_close_spot, atm_strike, previous_tte, volatility, option_type
    )
    level = sniper_level(atm_previous_close_premium)

    return SpfsSetup(
        trend=trend,
        option_type=option_type,
        atm_strike=atm_strike,
        otm_strike=otm_strike,
        expiry=expiry,
        volatility=volatility,
        atm_previous_close_premium=atm_previous_close_premium,
        sniper_level=level,
        reasoning=(
            f"{trend} trend -> locked ATM {atm_strike} {option_type} (OTM {otm_strike} {option_type}), "
            f"previous close premium {atm_previous_close_premium:.2f}, sniper level {level:.2f}"
        ),
    )
