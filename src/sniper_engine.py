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
    as stopped out (with SL on the close: a close below the SL); the target is only checked from the next
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
  - Target is checked against each bar's high from the candle after entry and
    fills at its level.
  - First SL on the CLOSE (owner decision 2026-10-06): the trade's first stop
    (SL (k-1)^2, also the body entry's fixed SL) is hit only when a candle
    CLOSES below it - a wick through it doesn't count - and the trade exits at
    that candle's close, however far below (SL 441, close 420 -> out at 420).
    A candle that touches the target exits at the target first (the close comes
    last). A RAISED (trailing) stop keeps the wick rule: low at/below it exits
    at the stop, checked before the target. With sl_on_close=False the wick
    rule applies to the first SL too.
  - Trailing SL (owner decision 2026-09-28): each time the bought option's
    candle closes above a square k^2 (k > n), the stop moves up to (k-1)^2 -
    one square behind - and never moves down. Entry 100 (10^2): close above
    121 -> SL 100, above 144 -> SL 121, above 169 -> SL 144. Applied from the
    entry candle's own close; a raised stop that is hit exits as TRAIL_STOP.
    FIRST step on a TOUCH (owner decision 2026-10-07): from the candle after
    entry, the high reaching the next square (k+1)^2 already moves the stop to
    the entry square k^2 (cost); later steps still need a close. If that
    candle also comes back to k^2 it exits there (0) - unless it reached the
    target, which it passed on the way up. 07-10 NIFTY 22600 PE @ 144: 09:40
    high 170 >= 169 -> SL 144, low 143.75 -> out at 144.
    Whether the fixed (n+2)^2 target stays alongside it is still open
    (keep_target).
  - First-half ATM-close trigger (owner decision 2026-10-06, widened 07-10),
    alongside the normal first-half trigger - whichever signals first: the OTM
    being bought only has to close above the SAME-side ATM's yesterday close
    (buying the OTM CE -> ATM CE close). The falling ATM being below the
    Sniper is NOT required (07-10) - it only adds the HIGH tag. 07-10 NIFTY:
    22600 PE closed 147.05 at 09:30 > ATM PE close 132.30 (ATM CE 118.95, still
    above Sniper 110.33) -> limit 144 -> 09:30 low 139.15 -> bought 144. Entry
    at the square above it, SL/target as usual. While the index is below its
    yesterday close, the OTM only has to be NEAR that close (within
    near_points: NIFTY 20, SENSEX 30) -> buy stop at the square above it.
    06-10 SENSEX (ATM 72400, 72500 CE, Sniper 404.70): ATM PE below Sniper,
    72500 CE closed 417.20 at 09:30, 11.60 under the ATM CE close 428.80, index
    below 72382.47 -> bought 441 at 09:30, SL 400, target 529 hit 09:55.
    Needs the index: bars["index"] plus index_close; without them only the
    "close above" form applies.
  - Anything still open is exited at the close of the candle ending 15:00.
  - Up to one trade per half; a second-half trade may open while a first-half
    trade is still running.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal, Optional

from hlc_signal import DIRECTIONLESS, bullish_pattern
from hlc_signal import Candle as PatternCandle
from sniper_signal import (
    EXIT_BY,
    OptionType,
    StrikeRow,
    TradeSetup,
    candle_close_time,
    entry_window_for,
    is_sideways,
    square_levels,
    previous_closes,
    trade_setups,
)

CONTRACT_KEYS = ("atm_ce", "atm_pe", "otm_ce", "otm_pe")
BUYERS_DAY_MAX_TRADES = 4  # owner, 2026-10-09: buyer's-day re-entries stop at 4 trades a day
UV_FIB = 0.618  # U/V trade entry: Fib 0.618 of the confirmation (retest) candle, from its high down (owner, 08-10)
TRAILING_SL = True
KEEP_FIXED_TARGET = True
FILL_AT_SQUARE = True
SL_ON_CLOSE = True
FIRST_TSL_ON_TOUCH = True


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
    body_entry: bool = False  # ORDER from the Sniper body entry (limit at `square` only, fixed SL)
    atm_close_trigger: float = 0.0  # ORDER from the first-half ATM-close trigger (owner, 06-10): that ATM close
    near: bool = False  # ... signalled while the OTM was only near it (index below yesterday's close)


@dataclass
class _Pending:
    setup: TradeSetup
    k: int  # stop at (k+1)^2; limit at k^2 only if has_limit
    signal_close: float
    has_limit: bool = True
    atm_below_sniper: bool = False
    limit_only: bool = False  # Sniper body entry (owner, 05-10): buy at k^2 only, never chase the next square
    atm_close_trigger: float = 0.0  # first-half ATM-close trigger (owner, 06-10) - becomes the trade's trigger
    near: bool = False
    limit_price: Optional[float] = None  # U/V trade (owner, 08-10): buy limit at the confirmation candle's Fib 0.618


def _key(setup: TradeSetup) -> str:
    """The bars key of the contract a setup buys (the OTM, or the ATM for the U/V trade)."""
    return setup.contract or _otm_key(setup.buy_type)


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
        sl_on_close: bool = SL_ON_CLOSE,
        first_tsl_on_touch: bool = FIRST_TSL_ON_TOUCH,
        index_close: Optional[float] = None,
        near_points: float = 0,
    ):
        self.day = day
        self.row = row
        self.require_cross = require_cross
        self.trailing = trailing
        self.keep_target = keep_target
        self.fill_at_square = fill_at_square
        self.sl_on_close = sl_on_close
        self.first_tsl_on_touch = first_tsl_on_touch
        self.index_close = index_close  # yesterday's index close, for the ATM-close trigger's "near" form
        # Owner, 2026-10-08: ATM leg opened below the Sniper, or closed below it on a candle ending by 09:30 ->
        # the opposite OTM closing above ITS yesterday high is a signal (buy at the upcoming square).
        self.otm_yesterday_high: dict[str, float] = {}  # "otm_ce"/"otm_pe" -> yesterday's high (set by the live bot)
        self.early_below_sniper: set[str] = set()  # "atm_ce"/"atm_pe" legs that went below the Sniper early
        # Owner, 2026-10-08: U/V trade on sideways days - each ATM leg's candles and its last bullish reversal
        self.atm_history: dict[str, list] = {"atm_ce": [], "atm_pe": []}
        self.uv_pattern: dict[str, tuple[int, float, float, str]] = {}  # leg -> (candle index, low, high, name)
        self.near_points = near_points
        self.pending: list[_Pending] = []
        self.setups = trade_setups(row)
        self.prev = previous_closes(row)
        self.open_trades: list[tuple[TradeSetup, TradeResult]] = []
        self.trades: list[TradeResult] = []
        self.halves_used: set[str] = set()
        self.sideways_candles = 0
        self.done = False
        self.buyers_day = False  # owner, 2026-10-01: set by the live bot - keep riding the move after a target
        self.continuation: Optional[tuple[TradeSetup, float]] = None
        self.fixed_sl: set[int] = set()  # id() of trades whose SL doesn't trail (Sniper body entry, owner 05-10)  # (setup, target booked) awaiting a close above
        # Each OTM's previous candle close, for the crossing check. Seeded with yesterday's close.
        self._last_otm_close = {"otm_ce": row.otm_ce_close, "otm_pe": row.otm_pe_close}

    def _close(self, trade: TradeResult, when: datetime, premium: float, reason: str) -> Event:
        trade.exit_time = when.isoformat()
        trade.exit_premium = round(premium, 2)
        trade.exit_reason = reason
        trade.pnl_points = round(premium - trade.entry_fill, 2)
        trade.pnl_pct = round((premium - trade.entry_fill) / trade.entry_fill * 100, 2)
        return Event("EXIT", trade)

    def _stop_hit(self, bar: Bar, stop: float, trailed: bool) -> Optional[float]:
        """The exit price if this candle hits `stop`, else None. Owner, 2026-10-06: for the FIRST SL only a
        candle CLOSING below it counts (exit at that close); 06-10 SENSEX 72600 CE @ 484, SL 441: the 10:55
        low 440.65 was only a wick, the candle closed 460.85. A trailed stop still exits on a touch."""
        if self.sl_on_close and not trailed:
            return bar.close if bar.close < stop else None
        return stop if bar.low <= stop else None

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
        for leg in ("atm_ce", "atm_pe"):
            bar = bars[leg]
            opened_below = when.time() == time(9, 15) and bar.open is not None and bar.open < self.row.sniper
            closed_below_early = candle_close_time(when) <= time(9, 30) and bar.close < self.row.sniper
            if opened_below or closed_below_early:
                self.early_below_sniper.add(leg)
            if bar.open is not None:
                history = self.atm_history[leg]
                history.append(PatternCandle(bar.open, bar.high, bar.low, bar.close))
                found = bullish_pattern(history[-3:])
                if found and found[0] not in DIRECTIONLESS:
                    span = history[-found[1]:]
                    self.uv_pattern[leg] = (len(history) - 1, min(c.low for c in span), max(c.high for c in span),
                                            found[0])
        self._last_otm_close = {"otm_ce": bars["otm_ce"].close, "otm_pe": bars["otm_pe"].close}

        for setup, trade in list(self.open_trades):
            bar = bars[_key(setup)]
            trails = self.trailing and id(trade) not in self.fixed_sl
            moved_now = False
            if (trails and self.first_tsl_on_touch and trade.trail_stop <= trade.stop_loss
                    and bar.high >= (math.isqrt(trade.entry_square) + 1) ** 2):
                trade.trail_stop = float(trade.entry_square)  # owner, 07-10: first step on a touch -> cost
                moved_now = True
            trailed = trade.trail_stop > trade.stop_loss
            stop_exit = self._stop_hit(bar, trade.trail_stop, trailed)
            target_hit = self.keep_target and bar.high >= trade.target
            if target_hit and (moved_now or (self.sl_on_close and not trailed)):  # target reached before the close / the drop
                events.append(self._close(trade, when, trade.target, "TARGET"))
            elif stop_exit is not None:
                reason = "TRAIL_STOP" if trade.trail_stop > trade.stop_loss else "STOPLOSS"
                events.append(self._close(trade, when, stop_exit, reason))
            elif target_hit:
                events.append(self._close(trade, when, trade.target, "TARGET"))
            elif closes_at_exit:
                events.append(self._close(trade, when, bar.close, "TIME_EXIT_1500"))
            else:
                if trails:
                    trade.trail_stop = trailed_stop(trade.trail_stop, bar.close)
                continue
            self.open_trades.remove((setup, trade))
            if self.buyers_day and trade.exit_reason == "TARGET":
                # (re-entering after stops too was tried on 01-10 SENSEX: 11 trades, -Rs 23,700 - dropped)
                self.continuation = (setup, trade.target)

        half = entry_window_for(when)
        for pending in list(self.pending):
            self.pending.remove(pending)
            if closes_at_exit or half != pending.setup.half:
                events.append(self._order_event("CANCEL", pending, when))
                continue
            fill = self._pending_fill(pending, bars[_key(pending.setup)])
            if fill is None:
                self.pending.append(pending)
            else:
                k, price = fill
                events += self._open(pending.setup, k, when, price, bars[_key(pending.setup)], True,
                                     pending.atm_below_sniper, fixed_sl=pending.limit_only,
                                     trigger=pending.atm_close_trigger or None)

        if closes_at_exit:
            self.done = True
            return events

        if (self.continuation and not self.open_trades and not self.pending and half is not None
                and len(self.trades) < BUYERS_DAY_MAX_TRADES):  # owner, 2026-10-09: max 4 on a buyer's day
            # Owner, 2026-10-01 (buyer's day): after a target, a candle closing above it -> buy the next square again.
            setup, booked = self.continuation
            close = bars[_key(setup)].close
            if close > booked:
                self.continuation = None
                pending = _Pending(setup, highest_square_below(close), close)
                self.pending.append(pending)
                events.append(self._order_event("ORDER", pending, when))
                return events

        if half is None or half in self.halves_used or not self._next_trade_allowed():
            return events

        current = {key: bars[key].close for key in CONTRACT_KEYS}
        if is_sideways(current, self.prev):
            self.sideways_candles += 1
            event = self._uv_entry(half, when)
            return events + ([event] if event else [])

        event = self._sniper_body_entry(half, bars, when)
        if event:
            return events + [event]

        event = self._yesterday_high_entry(half, bars, when)
        if event:
            return events + [event]

        for setup in (s for s in self.setups if s.half == half):
            falling_key = "atm_ce" if setup.falling_type == "CE" else "atm_pe"
            if current[falling_key] >= self.prev[falling_key]:
                continue
            otm_key = _otm_key(setup.buy_type)
            buy_close = current[otm_key]
            if self._otm_below_its_close(half, setup.buy_type, bars):
                continue
            k = highest_square_below(buy_close)  # the highest square this close is above
            # Owner, 2026-09-29: ATM below Sniper = ATM sellers strong -> OTM profit-booking/panic = buying chance.
            # Recorded as extra confidence, not required.
            confident = current[falling_key] < self.row.sniper
            if self.fill_at_square:
                if buy_close <= setup.levels.trigger:
                    pending = self._atm_close_signal(setup, buy_close, confident, bars) if half == "first" else None
                    if pending is None:
                        continue
                    self.halves_used.add(half)
                    self.pending.append(pending)
                    events.append(self._order_event("ORDER", pending, when))
                    break
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

    def _atm_close_signal(self, setup: TradeSetup, buy_close: float, atm_below_sniper: bool,
                          bars: dict[str, Bar]) -> Optional[_Pending]:
        """Owner, 2026-10-06/07: first half - the OTM closing above the same-side ATM's yesterday close (or, with the
        index below its yesterday close, within near_points of it) is a signal. ATM below the Sniper only adds the
        HIGH tag (07-10: "below the Sniper is good; if not, fine")."""
        atm_close = self.prev["atm_ce" if setup.buy_type == "CE" else "atm_pe"]
        n = square_levels(atm_close).n
        if buy_close > atm_close:
            k = highest_square_below(buy_close)
            if k < n:
                return _Pending(setup, n - 1, buy_close, has_limit=False, atm_below_sniper=atm_below_sniper,
                                atm_close_trigger=atm_close)
            return _Pending(setup, k, buy_close, atm_below_sniper=atm_below_sniper, atm_close_trigger=atm_close)
        index = bars.get("index")
        if (index is not None and self.index_close is not None and index.close < self.index_close
                and atm_close - buy_close <= self.near_points):
            return _Pending(setup, n - 1, buy_close, has_limit=False, atm_below_sniper=atm_below_sniper,
                            atm_close_trigger=atm_close, near=True)
        return None

    def _uv_entry(self, half: str, when: datetime) -> Optional[Event]:
        """Owner, 2026-10-08: on a sideways day (all 4 below their closes) trade the ATM only, U/V style - an ATM
        leg shows a bullish reversal pattern, then a later green candle retests the pattern's low (comes within a
        quarter of the pattern's range of it, doesn't close below it) = the confirmation candle -> buy limit at its
        Fib 0.618 (high - 0.618 x range); SL one square below that price's square, target two squares up. A close below the pattern low cancels it."""
        for leg, buy_type in (("atm_ce", "CE"), ("atm_pe", "PE")):
            pattern = self.uv_pattern.get(leg)
            history = self.atm_history[leg]
            if pattern is None or not history:
                continue
            at, low, high, name = pattern
            c = history[-1]
            if len(history) - 1 <= at:
                continue
            if c.close < low:
                del self.uv_pattern[leg]
                continue
            if c.low <= low + 0.25 * (high - low) and c.green:
                del self.uv_pattern[leg]
                # Owner, 08-10: "Fib on the confirmation candle, entry at 0.618" - a buy limit at high - 0.618 x range
                entry = round(c.high - UV_FIB * (c.high - c.low), 2)
                setup = TradeSetup(half, "up" if buy_type == "CE" else "down", "PE" if buy_type == "CE" else "CE",
                                   self.row.atm_strike, buy_type, square_levels(entry), contract=leg)
                pending = _Pending(setup, highest_square_below(entry), c.close, limit_price=entry)
                self.halves_used.add(half)
                self.pending.append(pending)
                return self._order_event("ORDER", pending, when)
        return None

    def _otm_below_its_close(self, half: str, buy_type: str, bars: dict[str, Bar]) -> bool:
        """Owner, 2026-10-08 (point 4): in the first half, an OTM still below its own yesterday close is no trade,
        even with the ATM below its close and the Sniper. (Second half: the Sniper trigger as usual.)"""
        key = _otm_key(buy_type)
        return half == "first" and bars[key].close < self.prev[key]

    def _yesterday_high_entry(self, half: str, bars: dict[str, Bar], when: datetime) -> Optional[Event]:
        """Owner, 2026-10-08: an ATM leg opened below the Sniper (or closed below it by 09:30) -> when the opposite
        OTM closes above its yesterday's high, buy it at the upcoming square; SL one square down, target two up."""
        for setup in (s for s in self.setups if s.half == half):
            falling = "atm_ce" if setup.falling_type == "CE" else "atm_pe"
            otm_key = _otm_key(setup.buy_type)
            high = self.otm_yesterday_high.get(otm_key)
            if falling not in self.early_below_sniper or high is None:
                continue
            close = bars[otm_key].close
            if close <= high:
                continue
            pending = _Pending(setup, highest_square_below(close), close, has_limit=False,
                               atm_below_sniper=bars[falling].close < self.row.sniper)
            self.halves_used.add(half)
            self.pending.append(pending)
            return self._order_event("ORDER", pending, when)
        return None

    def _sniper_body_entry(self, half: str, bars: dict[str, Bar], when: datetime) -> Optional[Event]:
        """Owner, 2026-10-05: an ATM leg's candle BODY crosses above the Sniper (opens below, closes above) ->
        buy that side's OTM at the square it has crossed - a limit at k^2 only (the owner bought at 49),
        fixed SL (k-1)^2 (no trailing), target (k+2)^2. 05-10 NIFTY (ATM 22500, Sniper 83.30): 10:20 22500 PE 65.10 -> 84.00
        -> 22400 PE @ 49, SL 36, target 81. No retest needed."""
        sniper = self.row.sniper
        for atm_key, buy_type in (("atm_pe", "PE"), ("atm_ce", "CE")):
            bar = bars[atm_key]
            if bar.open is None or not (bar.open < sniper < bar.close):
                continue
            setup = next((s for s in self.setups if s.half == half and s.buy_type == buy_type), None)
            if setup is None:  # (point 4's OTM-below-close filter doesn't apply here - 05-10 owner's trade)
                continue
            otm_close = bars[_otm_key(buy_type)].close
            k = highest_square_below(otm_close)
            if k < 2:
                continue
            pending = _Pending(setup, k, otm_close, limit_only=True)
            self.halves_used.add(half)
            self.pending.append(pending)
            return self._order_event("ORDER", pending, when)
        return None

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
                     atm_below_sniper=pending.atm_below_sniper, body_entry=pending.limit_only,
                     atm_close_trigger=pending.atm_close_trigger, near=pending.near)

    @staticmethod
    def _pending_fill(pending: _Pending, bar: Bar) -> Optional[tuple[int, float]]:
        """(k, fill price) if this candle fills the pending buy, else None."""
        k = pending.k
        if pending.limit_price is not None:  # U/V trade: a plain limit at the Fib 0.618 level; SL/target by k
            if bar.low <= pending.limit_price:
                return k, min(pending.limit_price, bar.open) if bar.open is not None else pending.limit_price
            return None
        limit, stop = k * k, (k + 1) ** 2
        back, up = pending.has_limit and bar.low <= limit, bar.high >= stop and not pending.limit_only
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
              atm_below_sniper: bool = False, fixed_sl: bool = False, trigger: Optional[float] = None) -> list[Event]:
        trade = TradeResult(
            date=self.day.isoformat(),
            half=setup.half,
            direction=setup.direction,
            buy_strike=setup.buy_strike,
            buy_type=setup.buy_type,
            trigger=round(trigger or setup.levels.trigger, 2),
            entry_square=k * k,
            stop_loss=(k - 1) ** 2,
            target=(k + 2) ** 2,
            entry_time=when.isoformat(),
            entry_fill=round(price, 2),
            trail_stop=float((k - 1) ** 2),
            atm_below_sniper=atm_below_sniper,
        )
        self.trades.append(trade)
        events = [Event("ENTRY", trade, body_entry=fixed_sl)]
        stop_exit = self._stop_hit(bar, trade.stop_loss, False) if fill_candle else None
        if stop_exit is not None:  # filled and stopped in the same candle
            events.append(self._close(trade, when, stop_exit, "STOPLOSS"))
            return events
        if fixed_sl:
            self.fixed_sl.add(id(trade))
        elif self.trailing:
            trade.trail_stop = trailed_stop(trade.trail_stop, bar.close)
        self.open_trades.append((setup, trade))
        return events

    def finish(self, when: datetime, bars: dict[str, Bar]) -> list[Event]:
        """Data ended before 15:00: close anything still open at the last bars."""
        events = [self._order_event("CANCEL", p, when) for p in self.pending]
        self.pending.clear()
        events += [
            self._close(trade, when, bars[_key(setup)].close, "DATA_END") for setup, trade in self.open_trades
        ]
        self.open_trades.clear()
        self.done = True
        return events
