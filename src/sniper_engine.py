"""
Candle-by-candle Sniper state machine (PROJECT_STATUS.md §2-§4), shared by the
backtester and the live paper bot so both follow exactly the same rules.

It only sees premium bars - one (high, low, close) per contract per 5-minute
candle - and never knows whether they are real option candles (live) or
Black-Scholes estimates (backtest).

Conventions where the spec leaves room for interpretation (listed in
PROJECT_STATUS.md's Open Decisions until the owner confirms them):
  - Entry: a candle whose close falls in a half's window, with the falling ATM
    leg below its yesterday close and the bought OTM's candle close strictly
    above the entry square. Filled at that candle close (not at the square
    itself - a buy only happens after the close is known, above the square).
  - With require_cross (the default), the OTM must close above a square
    having closed at/below it on the previous candle (yesterday's close before
    the day's first candle) - the candle that crosses the square, not any
    candle already far above it.
  - Higher squares (owner decision 2026-09-28): the crossed square may be the
    plan's entry square n^2 or ANY square above it. If the OTM already ran past
    n^2 (e.g. a gap), the next square it crosses becomes the entry square k^2,
    and SL/target are measured from that square: SL (k-1)^2, target (k+2)^2.
    A candle that jumps several squares uses the highest one it crossed.
  - No new entry on the candle closing at 15:00: it would be exited instantly.
  - Sideways (all 4 strikes below yesterday close) is checked on each candle
    before any entry - a whole-day check would need to know the future.
  - Stop/target are checked against each bar's high/low from the candle after
    entry. If both are crossed within one candle, the stop is assumed to have
    hit first. Stop/target fill at their level.
  - Trailing SL (owner decision 2026-09-28): each time the bought option's
    candle closes above a square k^2 (k > n), the stop moves up to (k-1)^2 -
    one square behind - and never moves down. Entry 100 (10^2): close above
    121 -> SL 100, above 144 -> SL 121, above 169 -> SL 144. Applied from the
    entry candle's own close; a raised stop that is hit exits as TRAIL_STOP.
    Whether the fixed (n+2)^2 target stays alongside it is still open
    (keep_target).
  - Anything still open is exited at the close of the candle ending 15:00.
  - Up to one trade per half; a second-half trade may open while a first-half
    trade is still running.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from sniper_signal import (
    EXIT_BY,
    OptionType,
    StrikeRow,
    TradeSetup,
    candle_close_time,
    entry_window_for,
    is_sideways,
    previous_closes,
    trade_setups,
)

CONTRACT_KEYS = ("atm_ce", "atm_pe", "otm_ce", "otm_pe")
TRAILING_SL = True
KEEP_FIXED_TARGET = True


@dataclass(frozen=True)
class Bar:
    """One contract's premium over one 5-minute candle."""

    high: float
    low: float
    close: float


@dataclass
class TradeResult:
    date: str
    half: str
    direction: str
    buy_strike: float
    buy_type: str
    trigger: float
    entry_square: int
    stop_loss: int
    target: int
    entry_time: str
    entry_fill: float
    exit_time: str = ""
    exit_premium: float = 0.0
    exit_reason: str = ""  # TARGET | STOPLOSS | TRAIL_STOP | TIME_EXIT_1500 | DATA_END
    trail_stop: float = 0.0  # current stop - starts at stop_loss, raised by the trailing rule
    pnl_points: float = 0.0
    pnl_pct: float = 0.0
    note: str = ""  # e.g. "catch-up" when the live bot found this entry while replaying candles after a restart


@dataclass(frozen=True)
class Event:
    kind: Literal["ENTRY", "EXIT"]
    trade: TradeResult


def _otm_key(option_type: OptionType) -> str:
    return "otm_ce" if option_type == "CE" else "otm_pe"


def highest_square_below(value: float) -> int:
    """k such that value is strictly above k^2 but not above (k+1)^2."""
    k = math.isqrt(math.floor(value))
    return k - 1 if k * k >= value else k


def trailed_stop(current_stop: float, close: float) -> float:
    """The stop after a candle closing at `close`: one square behind the
    highest square the close is strictly above, never lower than before."""
    k = highest_square_below(close)  # "closes above" is strict: a close exactly on 121 is not above 121
    return max(current_stop, float((k - 1) ** 2)) if k >= 1 else current_stop


class SniperDay:
    def __init__(
        self,
        day: date,
        row: StrikeRow,
        require_cross: bool = True,
        trailing: bool = TRAILING_SL,
        keep_target: bool = KEEP_FIXED_TARGET,
    ):
        self.day = day
        self.row = row
        self.require_cross = require_cross
        self.trailing = trailing
        self.keep_target = keep_target
        self.setups = trade_setups(row)
        self.prev = previous_closes(row)
        self.open_trades: list[tuple[TradeSetup, TradeResult]] = []
        self.trades: list[TradeResult] = []
        self.halves_used: set[str] = set()
        self.sideways_candles = 0
        self.done = False
        # Each OTM's previous candle close, for the crossing check. Seeded with yesterday's close.
        self._last_otm_close = {"otm_ce": row.otm_ce_close, "otm_pe": row.otm_pe_close}

    def _close(self, trade: TradeResult, when: datetime, premium: float, reason: str) -> Event:
        trade.exit_time = when.isoformat()
        trade.exit_premium = round(premium, 2)
        trade.exit_reason = reason
        trade.pnl_points = round(premium - trade.entry_fill, 2)
        trade.pnl_pct = round((premium - trade.entry_fill) / trade.entry_fill * 100, 2)
        return Event("EXIT", trade)

    def on_candle(self, when: datetime, bars: dict[str, Bar]) -> list[Event]:
        """Feed one completed 5-minute candle (`when` = its start time) with a
        Bar for each of CONTRACT_KEYS. Candles must arrive in time order."""
        if self.done:
            return []
        if when.time() >= EXIT_BY:
            self.done = True
            return []

        events: list[Event] = []
        closes_at_exit = candle_close_time(when) >= EXIT_BY
        previous_otm_close = self._last_otm_close
        self._last_otm_close = {"otm_ce": bars["otm_ce"].close, "otm_pe": bars["otm_pe"].close}

        for setup, trade in list(self.open_trades):
            bar = bars[_otm_key(setup.buy_type)]
            if bar.low <= trade.trail_stop:
                reason = "TRAIL_STOP" if trade.trail_stop > trade.stop_loss else "STOPLOSS"
                events.append(self._close(trade, when, trade.trail_stop, reason))
            elif self.keep_target and bar.high >= trade.target:
                events.append(self._close(trade, when, trade.target, "TARGET"))
            elif closes_at_exit:
                events.append(self._close(trade, when, bar.close, "TIME_EXIT_1500"))
            else:
                if self.trailing:
                    trade.trail_stop = trailed_stop(trade.trail_stop, bar.close)
                continue
            self.open_trades.remove((setup, trade))

        if closes_at_exit:
            self.done = True
            return events

        half = entry_window_for(when)
        if half is None or half in self.halves_used:
            return events

        current = {key: bars[key].close for key in CONTRACT_KEYS}
        if is_sideways(current, self.prev):
            self.sideways_candles += 1
            return events

        for setup in (s for s in self.setups if s.half == half):
            falling_key = "atm_ce" if setup.falling_type == "CE" else "atm_pe"
            if current[falling_key] >= self.prev[falling_key]:
                continue
            otm_key = _otm_key(setup.buy_type)
            buy_close = current[otm_key]
            k = highest_square_below(buy_close)  # the highest square this close is above
            if k < setup.levels.n:
                continue
            if self.require_cross and previous_otm_close[otm_key] > k * k:
                continue
            trade = TradeResult(
                date=self.day.isoformat(),
                half=setup.half,
                direction=setup.direction,
                buy_strike=setup.buy_strike,
                buy_type=setup.buy_type,
                trigger=round(setup.levels.trigger, 2),
                entry_square=k * k,
                stop_loss=(k - 1) ** 2,
                target=(k + 2) ** 2,
                entry_time=when.isoformat(),
                entry_fill=round(buy_close, 2),
                trail_stop=float((k - 1) ** 2),
            )
            if self.trailing:
                trade.trail_stop = trailed_stop(trade.trail_stop, buy_close)
            self.trades.append(trade)
            self.open_trades.append((setup, trade))
            self.halves_used.add(half)
            events.append(Event("ENTRY", trade))
            break

        return events

    def finish(self, when: datetime, bars: dict[str, Bar]) -> list[Event]:
        """Data ended before 15:00: close anything still open at the last bars."""
        events = [
            self._close(trade, when, bars[_otm_key(setup.buy_type)].close, "DATA_END") for setup, trade in self.open_trades
        ]
        self.open_trades.clear()
        self.done = True
        return events
