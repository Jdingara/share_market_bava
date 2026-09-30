"""
Candle-by-candle Sniper state machine (PROJECT_STATUS.md §2-§4), shared by the
backtester and the live paper bot so both follow exactly the same rules.

It only sees premium bars - one (high, low, close) per contract per 5-minute
candle - and never knows whether they are real option candles (live) or
Black-Scholes estimates (backtest).

Conventions where the spec leaves room for interpretation (listed in
PROJECT_STATUS.md's Open Decisions until the owner confirms them):
  - Signal: a candle whose close falls in a half's window, with the falling
    ATM leg below its yesterday close and the bought OTM's candle close strictly
    above the entry square.
  - Owner's rule, 2026-09-29 (fill_at_square=True):
    SIGNAL = the OTM candle closes above the TRIGGER (first half: the falling
    ATM's yesterday close; second half: Sniper) - above the trigger is enough,
    no square needs to be crossed yet.
    ENTRY = the upcoming square number, as orders from the next candle:
      * signal close still below the plan square n^2 (e.g. 85-99 with n^2=100):
        buy STOP at n^2 - bought when price rises to it;
      * signal close already above a square k^2 (e.g. 101.90 > 100): buy LIMIT
        at k^2 (bought if price comes back) and buy STOP at (k+1)^2 (bought
        there if it runs up first), with SL/target from the square bought. If one candle touches both and its open doesn't say which came
    first, the worse price (N) is assumed. The order is cancelled if the
    half's window ends first. On the fill candle a low at/below the SL counts
    as stopped out (conservative); the target is only checked from the next
    candle. With fill_at_square=False the old behaviour applies: bought at
    the signal candle's close.
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
from typing import Literal, Optional

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
FILL_AT_SQUARE = True


@dataclass(frozen=True)
class Bar:
    """One contract's premium over one 5-minute candle."""

    high: float
    low: float
    close: float
    open: Optional[float] = None  # used to tell which of two levels a candle reached first; None = unknown


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
    atm_below_sniper: bool = False  # at the signal: the falling ATM was already below Sniper = extra confidence


@dataclass(frozen=True)
class Event:
    kind: Literal["ENTRY", "EXIT", "ORDER", "CANCEL"]
    trade: Optional[TradeResult] = None
    # ORDER / CANCEL only: the pending buy
    setup: Optional[TradeSetup] = None
    square: int = 0  # buy limit here
    next_square: int = 0  # or buy stop here
    signal_close: float = 0.0
    when: Optional[datetime] = None
    atm_below_sniper: bool = False


@dataclass
class _Pending:
    setup: TradeSetup
    k: int  # stop at (k+1)^2; limit at k^2 only if has_limit
    signal_close: float
    has_limit: bool = True
    atm_below_sniper: bool = False


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
        fill_at_square: bool = FILL_AT_SQUARE,
    ):
        self.day = day
        self.row = row
        self.require_cross = require_cross
        self.trailing = trailing
        self.keep_target = keep_target
        self.fill_at_square = fill_at_square
        self.pending: list[_Pending] = []
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

        half = entry_window_for(when)
        for pending in list(self.pending):
            self.pending.remove(pending)
            if closes_at_exit or half != pending.setup.half:
                events.append(self._order_event("CANCEL", pending, when))
                continue
            fill = self._pending_fill(pending, bars[_otm_key(pending.setup.buy_type)])
            if fill is None:
                self.pending.append(pending)
            else:
                k, price = fill
                events += self._open(pending.setup, k, when, price, bars[_otm_key(pending.setup.buy_type)], True,
                                     pending.atm_below_sniper)

        if closes_at_exit:
            self.done = True
            return events

        if half is None or half in self.halves_used or not self._next_trade_allowed():
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
            # Owner, 2026-09-29: ATM below Sniper = ATM sellers strong -> OTM profit-booking/panic = buying chance.
            # Recorded as extra confidence, not required.
            confident = current[falling_key] < self.row.sniper
            if self.fill_at_square:
                if buy_close <= setup.levels.trigger:
                    continue
                if k < setup.levels.n:  # between the trigger and the plan square: wait for it to rise to n^2
                    pending = _Pending(setup, setup.levels.n - 1, buy_close, has_limit=False, atm_below_sniper=confident)
                else:
                    pending = _Pending(setup, k, buy_close, atm_below_sniper=confident)
                self.halves_used.add(half)
                self.pending.append(pending)
                events.append(self._order_event("ORDER", pending, when))
                break
            if k < setup.levels.n:
                continue
            if self.require_cross and previous_otm_close[otm_key] > k * k:
                continue
            self.halves_used.add(half)
            events += self._open(setup, k, when, buy_close, bars[otm_key], False, confident)
            break

        return events

    def _next_trade_allowed(self) -> bool:
        """Owner, 2026-09-30: after the day's first trade, trade again only if it was stopped out.
        A target, trailing stop or time exit ends the day; an open trade blocks new entries."""
        if not self.trades:
            return True
        return not self.open_trades and self.trades[-1].exit_reason == "STOPLOSS"

    @staticmethod
    def _order_event(kind: str, pending: _Pending, when: datetime) -> Event:
        return Event(kind, setup=pending.setup, square=pending.k ** 2 if pending.has_limit else 0,
                     next_square=(pending.k + 1) ** 2, signal_close=pending.signal_close, when=when,
                     atm_below_sniper=pending.atm_below_sniper)

    @staticmethod
    def _pending_fill(pending: _Pending, bar: Bar) -> Optional[tuple[int, float]]:
        """(k, fill price) if this candle fills the pending buy, else None."""
        k = pending.k
        limit, stop = k * k, (k + 1) ** 2
        back, up = pending.has_limit and bar.low <= limit, bar.high >= stop
        if back and up:
            if bar.open is not None and bar.open <= limit:
                return k, bar.open  # opened at/below the limit: filled there first
            if bar.open is not None and bar.open >= stop:
                return k + 1, bar.open
            return k + 1, float(stop)  # order unknown - assume the worse price
        if back:
            return k, min(float(limit), bar.open) if bar.open is not None else float(limit)
        if up:
            return k + 1, max(float(stop), bar.open) if bar.open is not None else float(stop)
        return None

    def _open(self, setup: TradeSetup, k: int, when: datetime, price: float, bar: Bar, fill_candle: bool,
              atm_below_sniper: bool = False) -> list[Event]:
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
            entry_fill=round(price, 2),
            trail_stop=float((k - 1) ** 2),
            atm_below_sniper=atm_below_sniper,
        )
        self.trades.append(trade)
        events = [Event("ENTRY", trade)]
        if fill_candle and bar.low <= trade.stop_loss:  # filled and stopped in the same candle (conservative)
            events.append(self._close(trade, when, trade.stop_loss, "STOPLOSS"))
            return events
        if self.trailing:
            trade.trail_stop = trailed_stop(trade.trail_stop, bar.close)
        self.open_trades.append((setup, trade))
        return events

    def finish(self, when: datetime, bars: dict[str, Bar]) -> list[Event]:
        """Data ended before 15:00: close anything still open at the last bars."""
        events = [self._order_event("CANCEL", p, when) for p in self.pending]
        self.pending.clear()
        events += [
            self._close(trade, when, bars[_otm_key(setup.buy_type)].close, "DATA_END") for setup, trade in self.open_trades
        ]
        self.open_trades.clear()
        self.done = True
        return events
