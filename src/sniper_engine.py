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
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional

from hlc_signal import DIRECTIONLESS, bearish_pattern, bullish_pattern
from sizing import risk_left, size_qty
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
RIDE_NORMAL_DAYS = True  # owner, 2026-10-12: buyer's day - no target exit, TSL ladder only (09-10 had it on normal days); normal days book the target, max 2 trades
RIDE_EVERY_DAY = True  # owner, 2026-10-15: all Sniper trades, all days - no target exit; 2 squares locked, then the square TSL
NORMAL_DAY_MAX_TRADES = 2
BUYERS_DAY_MAX_TRADES = 4  # owner, 2026-10-09: buyer's-day re-entries stop at 4 trades a day
REENTRY_SL_POINTS = 25  # owner, 2026-10-13: re-entry SL = buy price - 25 (NIFTY and SENSEX)
REENTRY_FIB = 0.618
# Owner, 2026-10-13 (all bots): after the morning trade, ONE more entry, only from 12:30, only with a proper reversal
# (reversal candle + green confirmation), SL = the reversal low - 1. Every day, buyer's day too.
SECOND_ENTRY_PM_REVERSAL = True
# Owner, 2026-10-15: entries on a RETEST only - no buy stop at the next square (14-10 SENSEX 73100 PE bought 441 on a
# touch, the candle closed 416.40). Signal above the square -> buy when it comes back to it; signal below the plan
# square -> a candle must CLOSE above that square first, then a later candle coming back to it fills.
RETEST_ONLY = True
# Owner, 2026-10-15: until an index candle CLOSES beyond the first 5-minute candle (09:15-09:20) the market is sideways
# for us - no entry. A close above its high starts the market for CE (up) setups; a close below its low for PE (down).
FIRST_CANDLE_BREAK = True
# Owner, 2026-10-16: judge the start on the two ATM strikes, not the index (16-10: the index's 09:15 spike candle held
# the start until 10:10). Up (CE) starts when the ATM PE shows a bearish reversal (09:40 Evening Star) and a later RED
# candle closes below that pattern's low (09:50), or the ATM CE closes above its own first 5-minute high. Down (PE) is
# the mirror. One leg breaking while the other doesn't confirm = fake momentum.
ATM_LEG_GATE = True
# Owner, 2026-10-16: morning (first half) - the falling ATM must have travelled to the Sniper (close below it) while the
# OTM closes above the Sniper AND its own yesterday close; and the NEXT candle must close the same way. Only then a
# signal / entry at the square. Otherwise it is a fake breakout - wait (16-10 NIFTY: the 09:30 22800 PE signal with
# the ATM CE far above the Sniper held the morning and the 10:05 23000 CE entry was missed).
MORNING_SNIPER_HOLD = True
# Owner, 2026-10-16: the second entry is NOT a 0.618 pull-back bought at a candle's close (16-10 NIFTY 172.20). After the
# first move the market goes sideways (16-10 23000 CE: high 199.65 at 10:15, then 140-195); when a candle CLOSES above
# that high, buy at the next square when it trades there - SL one square down, target two up (square rules as always).
SNIPER_RANGE_BREAK_REENTRY = True
# Owner, 2026-10-16: at 2 squares (the target) - a candle CLOSING above it is a strong break: SL to the target (2 squares
# locked), then the square TSL; touched but no close above = no strong break -> exit at the target.
STRONG_BREAK_OR_TARGET = True
LOCKED_TARGET_ON_TOUCH = True  # owner 22-10: SL locked at/above the target exits on a touch
# Owner, 2026-10-19 (SENSEX: 09:50 ATM CE closed 404.75 below the Sniper 428.08; at 09:55 the 74500 PE ran from 390 through
# 441 to 529.95): the conditions are on the OTM only - the opposite ATM just has to CONFIRM (one close below the Sniper).
# From the next candle, the first square above the Sniper and the OTM's yesterday close (441) is the entry when the OTM
# trades there; SL one square down, target two up. First half.
ATM_CONFIRM_SQUARE_ENTRY = True
# Owner, 2026-10-15: the retest is one way in; the other is MOMENTUM - once the market has started (index beyond its
# first candle), with the falling ATM below its yesterday close and the Sniper: the OTM having CLOSED above a square
# (signal 527.80 > 484) -> buy at the next square (529) when it trades there, from 09:30; SL one square down (484),
# target two up (625). A later close above 529 moves it up to 576, and so on.
MOMENTUM_ENTRY = True
MOMENTUM_FROM = time(9, 30)
MOMENTUM_NEEDS_ATM_CLOSE = True  # owner 16-10 point 2 / 19-10: the OTM must be above the same-side ATM's yesterday close  # owner, 2026-10-13: re-entry at the 0.618 pull-back of the previous move's low -> high
UV_TRADE = True  # owner, 2026-10-09: sideways days - no OTM trade, but the ATM U/V trade (own SL/TSL/target)
UV_FIB = 0.618  # U/V trade entry: Fib 0.618 of the confirmation (retest) candle, from its high down (owner, 08-10)
TRAILING_SL = True
KEEP_FIXED_TARGET = True
FILL_AT_SQUARE = True
SL_ON_CLOSE = True
FIRST_TSL_ON_TOUCH = False  # owner, 2026-10-12: no cost-on-touch step (12-10 SENSEX 529 was knocked out at 0)
ALL_STOPS_ON_CLOSE = True  # owner, 2026-10-12: every Sniper SL/TSL needs a candle BODY close below it
TRAIL_BEFORE_TARGET = False  # (legacy close-based trailing switch)
SQUARE_LADDER_TSL = True  # owner, 2026-10-12: TSL = one square below the highest square TOUCHED (exit on a close)


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
    qty: int = 0  # owner, 2026-10-12: sized per trade (0 = the bot's fixed quantity)
    # Owner, 2026-10-13: "every entry and exit needs a reason" - plain words for the log and the history
    entry_reason: str = ""
    exit_detail: str = ""
    tsl_why: str = ""  # why the trailing SL sits where it is (the ladder step that set it)


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
    reason: str = ""  # owner 13-10: why this buy - becomes the trade's entry_reason
    armed_at: Optional[int] = None  # RETEST_ONLY, no-limit order: candle no. that closed above (k+1)^2
    momentum_k: Optional[int] = None  # MOMENTUM_ENTRY: buy stop at momentum_k^2 (armed on candle momentum_at)
    momentum_at: int = 0


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
        first_tsl_on_touch: Optional[bool] = None,
        index_close: Optional[float] = None,
        near_points: float = 0,
        buy_atm: bool = False,
        lot: int = 0,
        allocation: float = 0,
        max_loss: float = 0,
    ):
        self.day = day
        self.row = row
        self.require_cross = require_cross
        self.trailing = trailing
        self.keep_target = keep_target
        self.ride_normal_days = RIDE_NORMAL_DAYS
        self.fill_at_square = fill_at_square
        self.sl_on_close = sl_on_close
        self.first_tsl_on_touch = FIRST_TSL_ON_TOUCH if first_tsl_on_touch is None else first_tsl_on_touch
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
        self.buy_atm = buy_atm
        self.lot, self.allocation, self.max_loss = lot, allocation, max_loss  # owner 12-10: sizing / daily loss
        self.capital = None  # live bot: shared Rs 5 lakh ledger (SENSEX first); None = the fixed allotment
        self.trade_range: dict[int, list[float]] = {}  # id(trade) -> [low, high] of its contract since entry
        self.reentry: Optional[dict] = None  # owner 13-10: after an exit, re-enter at the Fib 0.618 of low -> high  # owner, 2026-10-12: gap-failed day - the setups buy the ATM, not the OTM
        self.setups = trade_setups(row, buy_atm)
        self.first_index: Optional[Bar] = None  # the index's first 5-minute candle (owner 15-10)
        self._cur_bars: Optional[dict] = None
        self._prev_bars: Optional[dict] = None  # the previous candle's bars (momentum is armed on a CLOSE)
        self.started: set[str] = set()  # "up" / "down": the index has closed beyond that candle on that side
        self.started_why: dict[str, str] = {}
        self.hold_streak: dict[str, int] = {"up": 0, "down": 0}  # MORNING_SNIPER_HOLD: consecutive closes meeting it
        self.leg_top: dict[str, tuple[int, float, str, float]] = {}  # ATM leg -> (idx, pattern low, name, high)
        self.prev = previous_closes(row)
        self.open_trades: list[tuple[TradeSetup, TradeResult]] = []
        self.trades: list[TradeResult] = []
        self.halves_used: set[str] = set()
        self.sideways_candles = 0
        self.done = False
        self.buyers_day = False  # owner, 2026-10-01: set by the live bot - keep riding the move after a target
        self.continuation: Optional[tuple[TradeSetup, float]] = None
        self.fixed_sl: set[int] = set()
        self.uv_trades: dict[int, dict] = {}  # id(trade) -> {"first": (k+1)^2, "touched_at": candle no or None}
        self.candle_no = 0
        self.ladder: dict[int, dict] = {}  # id(trade) -> TSL ladder state (owner, 12-10)  # id() of trades whose SL doesn't trail (Sniper body entry, owner 05-10)  # (setup, target booked) awaiting a close above
        # Each OTM's previous candle close, for the crossing check. Seeded with yesterday's close.
        self._last_otm_close = {"otm_ce": row.otm_ce_close, "otm_pe": row.otm_pe_close}

    def _close(self, trade: TradeResult, when: datetime, premium: float, reason: str) -> Event:
        trade.exit_time = when.isoformat()
        trade.exit_premium = round(premium, 2)
        trade.exit_reason = reason
        trade.exit_detail = self._exit_detail(trade, when, premium, reason)
        trade.pnl_points = round(premium - trade.entry_fill, 2)
        trade.pnl_pct = round((premium - trade.entry_fill) / trade.entry_fill * 100, 2)
        return Event("EXIT", trade)

    def _exit_detail(self, trade: TradeResult, when: datetime, premium: float, reason: str) -> str:
        if reason == "STOPLOSS":
            return f"candle {when:%H:%M} closed {premium:g}, below the SL {trade.stop_loss:g}"
        if reason == "TRAIL_STOP":
            why = f" ({trade.tsl_why})" if trade.tsl_why else ""
            if LOCKED_TARGET_ON_TOUCH and trade.trail_stop >= trade.target and premium >= trade.trail_stop - 0.01:
                return f"candle {when:%H:%M} touched the locked SL {trade.trail_stop:g} - exit there{why}"
            return f"candle {when:%H:%M} closed {premium:g}, below the trailing SL {trade.trail_stop:g}{why}"
        if reason == "TARGET":
            return (f"2 square numbers reached (target {trade.target:g}) in candle {when:%H:%M}, no strong break "
                    f"(no close above it) -> exit")
        if reason == "DAILY_LOSS_LIMIT":
            return f"candle {when:%H:%M} closed {premium:g} - today's loss limit Rs {self.max_loss:,.0f} reached"
        if reason == "TIME_EXIT_1500":
            return "15:00 - the day's trading ends, closed at the candle close"
        return reason

    def _stop_hit(self, bar: Bar, stop: float, trailed: bool) -> Optional[float]:
        """The exit price if this candle hits `stop`, else None. Owner, 2026-10-06: for the FIRST SL only a
        candle CLOSING below it counts (exit at that close); 06-10 SENSEX 72600 CE @ 484, SL 441: the 10:55
        low 440.65 was only a wick, the candle closed 460.85. A trailed stop still exits on a touch."""
        if self.sl_on_close and (ALL_STOPS_ON_CLOSE or not trailed):
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
                if ATM_LEG_GATE:
                    self._track_leg_gate(leg, history, when)
                found = bullish_pattern(history[-3:])
                if found and found[0] not in DIRECTIONLESS:
                    span = history[-found[1]:]
                    self.uv_pattern[leg] = (len(history) - 1, min(c.low for c in span), max(c.high for c in span),
                                            found[0])
        self._last_otm_close = {"otm_ce": bars["otm_ce"].close, "otm_pe": bars["otm_pe"].close}

        self.candle_no += 1
        for setup, trade in list(self.open_trades):
            bar = bars[_key(setup)]
            rng = self.trade_range.setdefault(id(trade), [bar.low, bar.high])
            rng[0], rng[1] = min(rng[0], bar.low), max(rng[1], bar.high)
            if trade.qty and self.max_loss and (trade.entry_fill - bar.close) * trade.qty >= risk_left(
                    self.max_loss, self.realized_rupees()):
                # Owner, 2026-10-12: losses under control - out at the close once today's loss limit is used up
                events.append(self._close(trade, when, bar.close, "DAILY_LOSS_LIMIT"))
                self.open_trades.remove((setup, trade))
                continue
            uv = self.uv_trades.get(id(trade))
            if uv is not None:
                # Owner, 2026-10-09 - sideways-day ATM trade: SL the square below the buy price; the first square above
                # touched and the NEXT candle closing above it -> TSL there; exit at the second square (the target).
                stop_exit = self._stop_hit(bar, trade.trail_stop, trade.trail_stop > trade.stop_loss)
                if stop_exit is not None:
                    events.append(self._close(trade, when, stop_exit,
                                              "TRAIL_STOP" if trade.trail_stop > trade.stop_loss else "STOPLOSS"))
                elif bar.high >= trade.target:
                    events.append(self._close(trade, when, trade.target, "TARGET"))
                elif closes_at_exit:
                    events.append(self._close(trade, when, bar.close, "TIME_EXIT_1500"))
                else:
                    if uv["touched_at"] is not None and self.candle_no > uv["touched_at"] and bar.close > uv["first"]:
                        if float(uv["first"]) > trade.trail_stop:
                            trade.trail_stop = float(uv["first"])
                            trade.tsl_why = f"a later candle closed above the first square {uv['first']}"
                    if uv["touched_at"] is None and bar.high >= uv["first"]:
                        uv["touched_at"] = self.candle_no
                    continue
                self.open_trades.remove((setup, trade))
                continue
            # Owner, 2026-10-09: on a normal (non-buyer's) day no target exit - ride with the trailing SL (fixed-SL
            # trades trail too then, or they'd never take profit). Buyer's day: targets as before.
            # owner 12-10: ride on a BUYER'S day; owner 15-10: EVERY day - 2 squares get locked by the ladder, then the
            # square TSL rides it (no target exit)
            ride = self.ride_normal_days and (self.buyers_day or RIDE_EVERY_DAY)
            trails = self.trailing and (id(trade) not in self.fixed_sl or ride)
            moved_now = False
            force_target = False
            locked_before = trade.trail_stop  # owner 22-10: the touch exit uses the SL as it stood BEFORE this candle
            if (trails and self.first_tsl_on_touch and trade.trail_stop <= trade.stop_loss
                    and bar.high >= (math.isqrt(trade.entry_square) + 1) ** 2):
                trade.trail_stop = float(trade.entry_square)  # owner, 07-10: first step on a touch -> cost
                trade.tsl_why = "next square touched - SL to cost"
                moved_now = True
            if trails and SQUARE_LADDER_TSL:
                # Owner, 2026-10-12/13: nothing moves until the price reaches 2 squares above the entry. Entry 529 (k=23),
                # SL 484: 625 touched -> SL 576 (1 square of profit); a LATER candle CLOSING above 625 -> SL 625 (2 squares);
                # then one square below each higher square touched (729 -> 676, ...). Exits need a body close below.
                k = math.isqrt(trade.entry_square)
                m = math.isqrt(int(bar.high))
                state = self.ladder.setdefault(id(trade), {"cost_at": None})
                if m >= k + 2 and state["cost_at"] is None and STRONG_BREAK_OR_TARGET:
                    if bar.close > (k + 2) ** 2:
                        state["cost_at"] = self.candle_no
                        trade.trail_stop = max(trade.trail_stop, float((k + 2) ** 2))
                        trade.tsl_why = (f"candle {when:%H:%M} closed {bar.close:g} above the target {(k + 2) ** 2} - strong "
                                         f"break, SL to the target (2 squares locked)")
                    else:
                        force_target = True
                elif m >= k + 2:
                    if state["cost_at"] is None:
                        state["cost_at"] = self.candle_no
                        # owner, 2026-10-13: at least one square of profit once 2 squares are reached (was cost)
                        if (k + 1) ** 2 > trade.trail_stop:
                            trade.trail_stop = float((k + 1) ** 2)
                            trade.tsl_why = f"2 squares up ({(k + 2) ** 2}) touched - SL to {(k + 1) ** 2}, 1 square of profit"
                    elif self.candle_no > state["cost_at"]:
                        # owner, 2026-10-13: a LATER candle CLOSING above the target -> SL at the target (2 squares
                        # locked); higher squares touched -> one square below them
                        locked = float((k + 2) ** 2) if bar.close > (k + 2) ** 2 else 0.0
                        higher = float((m - 1) ** 2) if m >= k + 3 else 0.0
                        if max(locked, higher) > trade.trail_stop:
                            trade.trail_stop = max(locked, higher)
                            trade.tsl_why = (f"square {m * m} touched - SL one square below it" if higher >= locked
                                             else f"a later candle closed {bar.close:g} above the target {(k + 2) ** 2} - SL to the target")
            trailed = trade.trail_stop > trade.stop_loss
            stop_exit = self._stop_hit(bar, trade.trail_stop, trailed)
            if LOCKED_TARGET_ON_TOUCH and locked_before >= trade.target and bar.low <= locked_before:
                # owner 22-10 (SENSEX 400 -> 484 locked, next candle 528 -> close 374.85): once the SL sits at the target or
                # higher, a TOUCH exits there - no waiting for the candle close
                trade.trail_stop = locked_before
                stop_exit = min(locked_before, bar.open) if bar.open is not None else locked_before
            target_hit = self.keep_target and not ride and bar.high >= trade.target
            if force_target:
                # owner 16-10: 2 squares reached without a close above - no strong break -> book the target
                events.append(self._close(trade, when, float(trade.target), "TARGET"))
            elif target_hit and (moved_now or (self.sl_on_close and (ALL_STOPS_ON_CLOSE or not trailed))):
                # target reached during the candle, before a stop that only counts on the close
                events.append(self._close(trade, when, trade.target, "TARGET"))
            elif stop_exit is not None:
                reason = "TRAIL_STOP" if trade.trail_stop > trade.stop_loss else "STOPLOSS"
                events.append(self._close(trade, when, stop_exit, reason))
            elif target_hit:
                events.append(self._close(trade, when, trade.target, "TARGET"))
            elif closes_at_exit:
                events.append(self._close(trade, when, bar.close, "TIME_EXIT_1500"))
            else:
                if trails and not SQUARE_LADDER_TSL and (TRAIL_BEFORE_TARGET or trade.trail_stop >= trade.target):
                    trade.trail_stop = trailed_stop(trade.trail_stop, bar.close)
                continue
            self.open_trades.remove((setup, trade))
            self._arm_reentry(setup, trade)
            if self.buyers_day and trade.exit_reason == "TARGET":
                # (re-entering after stops too was tried on 01-10 SENSEX: 11 trades, -Rs 23,700 - dropped)
                self.continuation = (setup, trade.target)

        self._prev_bars, self._cur_bars = self._cur_bars, bars
        idx = bars.get("index")
        if idx is not None:
            if self.first_index is None:
                self.first_index = idx
            else:
                if not ATM_LEG_GATE and idx.close > self.first_index.high:
                    self.started.add("up")
                if not ATM_LEG_GATE and idx.close < self.first_index.low:
                    self.started.add("down")
        if MORNING_SNIPER_HOLD:
            for direction, falling, otm in (("up", "atm_pe", "otm_ce"), ("down", "atm_ce", "otm_pe")):
                ok = (bars[falling].close < self.row.sniper and bars[otm].close > self.row.sniper
                      and bars[otm].close > self.prev[otm])
                self.hold_streak[direction] = self.hold_streak[direction] + 1 if ok else 0
        half = entry_window_for(when)
        for pending in list(self.pending):
            self.pending.remove(pending)
            if closes_at_exit or half != pending.setup.half:
                events.append(self._order_event("CANCEL", pending, when))
                continue
            fill = self._pending_fill(pending, bars[_key(pending.setup)])
            if fill is None:
                fill = self._momentum_fill(pending, bars, when)
            if fill is None:
                self.pending.append(pending)
            else:
                k, price = fill
                events += self._open(pending.setup, k, when, price, bars[_key(pending.setup)], True,
                                     pending.atm_below_sniper, fixed_sl=pending.limit_only,
                                     trigger=pending.atm_close_trigger or None, reason=pending.reason)

        if closes_at_exit:
            self.done = True
            return events

        if (self.continuation and not SECOND_ENTRY_PM_REVERSAL and not self.open_trades and not self.pending and half is not None
                and len(self.trades) < BUYERS_DAY_MAX_TRADES):  # owner, 2026-10-09: max 4 on a buyer's day
            # Owner, 2026-10-01 (buyer's day): after a target, a candle closing above it -> buy the next square again.
            setup, booked = self.continuation
            close = bars[_key(setup)].close
            if close > booked:
                self.continuation = None
                pending = _Pending(setup, highest_square_below(close), close,
                                   reason=f"buyer's day: after the target {booked}, candle {when:%H:%M} closed {close:g} above it")
                self.pending.append(pending)
                events.append(self._order_event("ORDER", pending, when))
                return events

        # Owner, 2026-10-12: an unfilled body-entry limit doesn't block the half - the normal signal can still come
        # and replaces it (12-10 SENSEX: body limit 441 never filled; the normal 72500 PE 529 trade was missed).
        body_waiting = [p for p in self.pending if p.limit_only and p.setup.half == half]
        event = self._atm_confirm_entry(half, bars, when)
        if event:
            return events + event
        event = self._reentry_entry(half, bars, when)
        if event:
            return events + event
        if SECOND_ENTRY_PM_REVERSAL and self.trades and self.ride_normal_days:
            return events  # owner 13-10: after the morning trade only the 12:30+ reversal re-entry

        # Owner, 2026-10-13: no re-entry without a fresh reason - the 12-10 "same half can trade again once flat"
        # re-bought on the same morning signal (13-10: three losing re-entries). A half trades once; the buyer's-day
        # cap of 4 still counts the other entries (second half, continuation after a target).
        reopen = False
        if half is None or not self._next_trade_allowed() or (half in self.halves_used and not body_waiting and not reopen):
            return events

        current = {key: bars[key].close for key in CONTRACT_KEYS}
        if is_sideways(current, self.prev):
            self.sideways_candles += 1
            # Owner, 2026-10-09: sideways day - no OTM trade; only the ATM U/V trade (UV_TRADE)
            event = self._uv_entry(half, when) if UV_TRADE else None
            return events + ([event] if event else [])

        event = self._sniper_body_entry(half, bars, when)
        if event:
            return events + [event]

        event = self._yesterday_high_entry(half, bars, when)
        if event:
            return events + [event]

        for setup in self._setups(half):
            falling_key = "atm_ce" if setup.falling_type == "CE" else "atm_pe"
            if current[falling_key] >= self.prev[falling_key]:
                continue
            otm_key = _key(setup)
            buy_close = current[otm_key]
            if self._otm_below_its_close(half, setup, bars):
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
                    sq = (f"the square {pending.k ** 2} or the upcoming square {(pending.k + 1) ** 2}" if pending.has_limit
                          else f"the upcoming square {(pending.k + 1) ** 2}")
                    pending.reason = ((f"ATM {setup.falling_type} went below the Sniper {self.row.sniper:g}, so " if confident
                                       else f"ATM {setup.falling_type} below its close, ")
                                      + f"OTM {setup.buy_type} closed {buy_close:g} "
                                      + (f"within {self.near_points} of" if pending.near else "above")
                                      + f" the ATM {setup.buy_type} close {pending.atm_close_trigger:g}"
                                      + (" (index below yesterday's close)" if pending.near else "")
                                      + f" (candle {when:%H:%M}) -> entry at {sq}")
                    for waiting in body_waiting:  # replaces an unfilled body-entry limit too
                        self.pending.remove(waiting)
                        events.append(self._order_event("CANCEL", waiting, when))
                    self.halves_used.add(half)
                    self.pending.append(pending)
                    events.append(self._order_event("ORDER", pending, when))
                    break
                if k < setup.levels.n:  # between the trigger and the plan square: wait for it to rise to n^2
                    pending = _Pending(setup, setup.levels.n - 1, buy_close, has_limit=False, atm_below_sniper=confident)
                else:
                    pending = _Pending(setup, k, buy_close, atm_below_sniper=confident)
                above = ("the Sniper" if abs(setup.levels.trigger - self.row.sniper) < 0.01
                         else "the trigger") + f" {setup.levels.trigger:g}"
                sq = (f"the square {pending.k ** 2} or the upcoming square {(pending.k + 1) ** 2}" if pending.has_limit
                      else f"the upcoming square {(pending.k + 1) ** 2}")
                pending.reason = (f"ATM {setup.falling_type} travelled from its close {self.prev[falling_key]:g} toward the "
                                  f"Sniper {self.row.sniper:g} (now {current[falling_key]:g}"
                                  + (", below the Sniper" if confident else "") + f"), so OTM {setup.buy_type} closed "
                                  f"{buy_close:g} above {above} (candle {when:%H:%M}) -> entry at {sq}")
                for waiting in body_waiting:  # the normal signal replaces an unfilled body-entry limit
                    self.pending.remove(waiting)
                    events.append(self._order_event("CANCEL", waiting, when))
                self.halves_used.add(half)
                self.pending.append(pending)
                events.append(self._order_event("ORDER", pending, when))
                break
            if k < setup.levels.n:
                continue
            if self.require_cross and previous_otm_close[otm_key] > k * k:
                continue
            self.halves_used.add(half)
            events += self._open(setup, k, when, buy_close, bars[otm_key], False, confident,
                                 reason=f"{setup.buy_type} closed {buy_close:g} above the square {k * k} (candle {when:%H:%M})")
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
            if RETEST_ONLY:
                # owner 19-10 (SENSEX 74500 PE 468.40, ATM PE close 474.60): below the ATM close -> the retest of the
                # square under the close (441); momentum waits for a close above the ATM close
                return _Pending(setup, highest_square_below(buy_close), buy_close, atm_below_sniper=atm_below_sniper,
                                atm_close_trigger=atm_close, near=True)
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
                pending = _Pending(setup, highest_square_below(entry), c.close, limit_price=entry,
                                   reason=f"sideways day: {name} reversal on the ATM {buy_type}, then a green candle retested "
                                          f"its low - limit at that candle's Fib 0.618 {entry:g}")
                self.halves_used.add(half)
                self.pending.append(pending)
                return self._order_event("ORDER", pending, when)
        return None

    def _otm_below_its_close(self, half: str, setup: TradeSetup, bars: dict[str, Bar]) -> bool:
        """Owner, 2026-10-08 (point 4): in the first half, an OTM still below its own yesterday close is no trade,
        even with the ATM below its close and the Sniper. (Second half: the Sniper trigger as usual.)"""
        key = _key(setup)
        return half == "first" and bars[key].close < self.prev[key]

    def _yesterday_high_entry(self, half: str, bars: dict[str, Bar], when: datetime) -> Optional[Event]:
        """Owner, 2026-10-08: an ATM leg opened below the Sniper (or closed below it by 09:30) -> when the opposite
        OTM closes above its yesterday's high, buy it at the upcoming square; SL one square down, target two up."""
        if half in self.halves_used:
            return None
        for setup in self._setups(half):
            falling = "atm_ce" if setup.falling_type == "CE" else "atm_pe"
            otm_key = _key(setup)
            high = self.otm_yesterday_high.get(otm_key)
            if falling not in self.early_below_sniper or high is None:
                continue
            close = bars[otm_key].close
            if close <= high:
                continue
            pending = _Pending(setup, highest_square_below(close), close, has_limit=False,
                               atm_below_sniper=bars[falling].close < self.row.sniper,
                               reason=f"ATM {setup.falling_type} went below the Sniper early; {setup.buy_type} closed "
                                      f"{close:g} above its yesterday high {high:g} (candle {when:%H:%M})")
            self.halves_used.add(half)
            self.pending.append(pending)
            return self._order_event("ORDER", pending, when)
        return None

    def _sniper_body_entry(self, half: str, bars: dict[str, Bar], when: datetime) -> Optional[Event]:
        """Owner, 2026-10-05: an ATM leg's candle BODY crosses above the Sniper (opens below, closes above) ->
        buy that side's OTM at the square it has crossed - a limit at k^2 only (the owner bought at 49),
        fixed SL (k-1)^2 (no trailing), target (k+2)^2. 05-10 NIFTY (ATM 22500, Sniper 83.30): 10:20 22500 PE 65.10 -> 84.00
        -> 22400 PE @ 49, SL 36, target 81. No retest needed."""
        if half in self.halves_used:  # one body order per half; a waiting one mustn't be duplicated
            return None
        sniper = self.row.sniper
        for atm_key, buy_type in (("atm_pe", "PE"), ("atm_ce", "CE")):
            bar = bars[atm_key]
            if bar.open is None or not (bar.open < sniper < bar.close):
                continue
            setup = next((s for s in self._setups(half) if s.buy_type == buy_type), None)
            if setup is None:  # (point 4's OTM-below-close filter doesn't apply here - 05-10 owner's trade)
                continue
            otm_close = bars[_key(setup)].close
            k = highest_square_below(otm_close)
            if k < 2:
                continue
            pending = _Pending(setup, k, otm_close, limit_only=True,
                               reason=f"ATM {buy_type} candle {when:%H:%M} body crossed the Sniper {sniper:g} "
                                      f"({bar.open:g} -> {bar.close:g}) - limit at {k * k}")
            self.halves_used.add(half)
            self.pending.append(pending)
            return self._order_event("ORDER", pending, when)
        return None

    def _momentum_fill(self, pending: _Pending, bars: dict[str, Bar], when: datetime) -> Optional[tuple[int, float]]:
        """Owner, 2026-10-15: momentum entry next to the retest - see MOMENTUM_ENTRY. Armed on the previous candle's
        close, filled when this candle trades at the square."""
        if not (RETEST_ONLY and MOMENTUM_ENTRY) or pending.limit_only or pending.limit_price is not None:
            return None
        if self._prev_bars is not None:
            self._arm_momentum(pending, self._prev_bars, when - timedelta(minutes=5))
        m = pending.momentum_k
        bar = bars[_key(pending.setup)]
        if m is not None and when.time() >= MOMENTUM_FROM and bar.high >= m * m:
            return m, max(float(m * m), bar.open) if bar.open is not None else float(m * m)
        return None

    def _arm_momentum(self, pending: _Pending, bars: dict[str, Bar], when: datetime) -> None:
        key = "atm_ce" if pending.setup.falling_type == "CE" else "atm_pe"
        bar, falling = bars[_key(pending.setup)], bars[key]
        if not (falling.close < self.row.sniper and falling.close < self.prev[key]):
            return
        same_atm = "atm_ce" if pending.setup.buy_type == "CE" else "atm_pe"
        if MOMENTUM_NEEDS_ATM_CLOSE and bar.close <= self.prev[same_atm]:
            # owner 16-10 point 2 (19-10 SENSEX 74500 PE 468.40 < ATM PE close 474.60 bought 484 and lost): momentum only
            # once the OTM is above the same side's ATM yesterday close - otherwise the retest square only
            return
        if FIRST_CANDLE_BREAK and self.first_index is not None and pending.setup.direction not in self.started:
            return
        k = highest_square_below(bar.close) + 1
        if k <= pending.k or (pending.momentum_k is not None and k <= pending.momentum_k):
            return
        pending.momentum_k, pending.momentum_at = k, self.candle_no
        pending.reason += (f"; momentum: candle {when:%H:%M} closed {bar.close:g} above {(k - 1) ** 2} with the ATM "
                           f"{pending.setup.falling_type} {falling.close:g} below its close {self.prev[key]:g} and the "
                           f"Sniper {self.row.sniper:g} -> entry at the next square {k * k}"
                           + (f" [market started: {self.started_why[pending.setup.direction]}]"
                              if pending.setup.direction in self.started_why else ""))

    def _track_leg_gate(self, leg: str, history: list, when: datetime) -> None:
        """Owner, 2026-10-16 - see ATM_LEG_GATE."""
        rises = "up" if leg == "atm_ce" else "down"  # this leg rising = that side's buy
        falls = "down" if leg == "atm_ce" else "up"  # this leg turning down (confirmed) = the other side's buy
        name = "CE" if leg == "atm_ce" else "PE"
        c, first = history[-1], history[0]
        if len(history) > 1 and c.close > first.high and rises not in self.started:
            self.started.add(rises)
            self.started_why[rises] = f"ATM {name} closed {c.close:g} above its first 5-minute high {first.high:g} at {when:%H:%M}"
        top = self.leg_top.get(leg)
        if (top is not None and len(history) - 1 > top[0] and c.close < c.open and c.close < top[1]
                and falls not in self.started):
            self.started.add(falls)
            self.started_why[falls] = (f"ATM {name} {top[2]} then a red confirmation candle {when:%H:%M} closed "
                                       f"{c.close:g} below {top[1]:g}")
        if top is not None and c.close > top[3]:
            top = self.leg_top.pop(leg)  # closed above the pattern's high - that reversal failed
            top = None
        found = bearish_pattern(history[-3:])
        if found and found[0] not in DIRECTIONLESS:  # the latest reversal is the one a red close must confirm
            span = history[-found[1]:]
            self.leg_top[leg] = (len(history) - 1, min(x.low for x in span), found[0], max(x.high for x in span))

    def _setups(self, half: Optional[str]) -> list[TradeSetup]:
        """This half's setups whose side has started - the index closed beyond its first 5-minute candle (owner 15-10)."""
        return [s for s in self.setups if s.half == half
                and (not FIRST_CANDLE_BREAK or self.first_index is None or s.direction in self.started)
                and (not MORNING_SNIPER_HOLD or half != "first" or self.first_index is None
                     or self.hold_streak[s.direction] >= 2)]

    def _arm_reentry(self, setup: TradeSetup, trade: TradeResult) -> None:
        """Owner, 2026-10-13: the reason for a re-entry - draw the Fib from the move's low to its high; a pull-back to
        0.618 is the re-entry (buy there). Normal day 2 entries, buyer's day 4."""
        rng = self.trade_range.get(id(trade))
        if rng and rng[1] > rng[0]:
            self.reentry = {"setup": setup, "low": rng[0], "high": rng[1], "at": self.candle_no}

    def _reentry_entry(self, half: Optional[str], bars: dict[str, Bar], when: datetime) -> Optional[list[Event]]:
        r = self.reentry
        pm = SECOND_ENTRY_PM_REVERSAL
        if (r is None or (half is None and not pm) or self.open_trades or self.pending or not self.ride_normal_days
                or self.candle_no <= r["at"]):  # not on the exit candle itself
            return None  # (the 2/4-trades-a-day rules live with ride_normal_days - old-rule tests run without them)
        limit = 2 if pm else BUYERS_DAY_MAX_TRADES if self.buyers_day else NORMAL_DAY_MAX_TRADES
        if pm and "second" in self.halves_used:
            self.reentry = None
            return None
        if not pm and not self.buyers_day and half in self.halves_used:
            return None  # owner 13-10: normal day - one entry 09:30-12:00 and one 12:30-15:00
        if len(self.trades) >= limit or (self.max_loss and self.allocation
                                         and risk_left(self.max_loss, self.realized_rupees()) <= 0):
            self.reentry = None
            return None
        bar = bars[_key(r["setup"])]
        level = r["low"] + REENTRY_FIB * (r["high"] - r["low"])  # owner 13-10 chart: 0 = low, 1 = high, 0.618 up from the low
        if bar.close < r["low"]:  # the move failed - no re-entry
            self.reentry = None
            return None
        if SNIPER_RANGE_BREAK_REENTRY:
            return self._range_break_entry(r, half, bar, when)
        if bar.open is not None:
            r.setdefault("candles", []).append(PatternCandle(bar.open, bar.high, bar.low, bar.close))
        if "tested_at" not in r:
            if bar.low > level:
                if bar.high > r["high"]:  # the move goes on before any pull-back - stretch the Fib
                    r["high"] = bar.high
                return None
            r["tested_at"] = self.candle_no  # 0.618 tested - now wait for a reversal candle
            r["tested_when"] = when
        # Owner, 2026-10-13: after the 0.618 test -> a REVERSAL candle -> then a CONFIRMATION candle closing green
        # (above the 0.618 level) -> buy at its close. No reversal + confirmation -> no entry.
        if "reversal_at" in r and self.candle_no > r["reversal_at"]:
            if bar.open is not None and bar.close > bar.open and bar.close > level:
                r["confirmed"] = True
            else:
                del r["reversal_at"]  # not confirmed - wait for a new reversal
        if not r.get("confirmed"):
            found = bullish_pattern(r["candles"]) if "reversal_at" not in r and r.get("candles") and bar.open is not None else None
            if found:
                r["reversal_at"], r["reversal"] = self.candle_no, f"{found[0]} at {when:%H:%M}"
                r["reversal_low"] = min(c.low for c in r["candles"][-found[1]:])
            return None
        if pm and half != "second":
            # owner 13-10: the second entry only from 12:30 - a confirmation before that doesn't count; wait for a new one
            r.pop("confirmed", None)
            r.pop("reversal_at", None)
            return None
        self.reentry = None
        fill = bar.close
        setup = TradeSetup(half, r["setup"].direction, r["setup"].falling_type, r["setup"].buy_strike,
                           r["setup"].buy_type, square_levels(fill), contract=r["setup"].contract)
        self.halves_used.add(half)
        stop = round(r["reversal_low"] - 1, 2) if pm else None
        why = (f"re-entry: Fib {r['low']:g} -> {r['high']:g}, 0.618 = {level:.2f} tested at {r['tested_when']:%H:%M}; "
               f"reversal {r['reversal']}; green confirmation candle {when:%H:%M} closed {fill:g} above 0.618"
               + (f"; SL = reversal low {r['reversal_low']:g} - 1" if pm else ""))
        return self._open(setup, highest_square_below(fill), when, round(fill, 2), bar, False, reentry=True, reason=why,
                          stop=stop)

    def _atm_confirm_entry(self, half: Optional[str], bars: dict[str, Bar], when: datetime) -> Optional[list[Event]]:
        """Owner, 2026-10-19 - see ATM_CONFIRM_SQUARE_ENTRY."""
        if (not ATM_CONFIRM_SQUARE_ENTRY or half != "first" or self._prev_bars is None or self.open_trades
                or self.pending or half in self.halves_used or not self._next_trade_allowed()):
            return None
        prev = self._prev_bars
        if (when - timedelta(minutes=5)).time() < time(9, 25):
            # owner 19-10: no confirmation before 09:30; owner 22-10: the candle CLOSING at 09:30 (09:25-09:30) counts
            return None
        for setup in (s for s in self.setups if s.half == half):
            falling = "atm_ce" if setup.falling_type == "CE" else "atm_pe"
            otm = _key(setup)
            if setup.contract or prev[falling].close >= self.row.sniper:
                continue  # the opposite ATM hasn't confirmed (closed below the Sniper) yet
            # owner 22-10 (replaces 19-10's "first square above, on a touch"): the confirmation candle's OTM CLOSE must
            # be above the Sniper, its own yesterday close and the same side's ATM yesterday close; then the entry is the
            # RETEST of the square below that close (22-10 SENSEX 73400 PE: 09:25 closed 415 -> 400 at 09:30)
            same_atm = "atm_ce" if setup.buy_type == "CE" else "atm_pe"
            otm_close = prev[otm].close
            if not (otm_close > self.row.sniper and otm_close > self.prev[otm] and otm_close > self.prev[same_atm]):
                continue
            k = highest_square_below(otm_close)
            bar = bars[otm]
            if k * k <= max(self.row.sniper, self.prev[otm]) or bar.low > k * k:
                continue
            fill = min(float(k * k), bar.open) if bar.open is not None else float(k * k)
            self.halves_used.add(half)
            why = (f"ATM {setup.falling_type} confirmed: closed {prev[falling].close:g} below the Sniper {self.row.sniper:g}; "
                   f"OTM {setup.buy_type} closed {otm_close:g} above the Sniper, its close {self.prev[otm]:g} and the ATM "
                   f"{setup.buy_type} close {self.prev[same_atm]:g} -> retest of the square {k * k} in candle {when:%H:%M}")
            events = self._open(setup, k, when, round(fill, 2), bar, True, prev[falling].close < self.row.sniper, reason=why)
            trade = events[0].trade if events else None
            if trade is not None and not trade.exit_reason and bar.high >= trade.target and bar.close <= trade.target:
                # 2 squares inside the entry candle without a close above - no strong break -> book it (owner 16-10)
                self.open_trades = [(st, t) for st, t in self.open_trades if t is not trade]
                events.append(self._close(trade, when, float(trade.target), "TARGET"))
            elif trade is not None and not trade.exit_reason and bar.close > trade.target:
                trade.trail_stop = float(trade.target)  # strong break in the entry candle - 2 squares locked
                trade.tsl_why = f"entry candle closed {bar.close:g} above the target - SL to the target"
                self.ladder[id(trade)] = {"cost_at": self.candle_no}
            return events
        return None

    def _range_break_entry(self, r: dict, half: Optional[str], bar: Bar, when: datetime) -> Optional[list[Event]]:
        """Owner, 2026-10-16 - see SNIPER_RANGE_BREAK_REENTRY."""
        k = r.get("break_k")
        if k is not None and self.candle_no > r["break_at"]:
            # owner 16-10: after the break close, a RETEST of the square below that close -> entry there
            if bar.low <= k * k and (not SECOND_ENTRY_PM_REVERSAL or half == "second"):
                self.reentry = None
                fill = min(float(k * k), bar.open) if bar.open is not None else float(k * k)
                setup = TradeSetup(half, r["setup"].direction, r["setup"].falling_type, r["setup"].buy_strike,
                                   r["setup"].buy_type, square_levels(fill), contract=r["setup"].contract)
                self.halves_used.add(half)
                return self._open(setup, k, when, round(fill, 2), bar, True, reason=r["break_why"])
            if bar.close > (k + 1) ** 2:  # closed above the next square too - retest that one
                r["break_k"], r["break_at"] = highest_square_below(bar.close), self.candle_no
            return None
        if bar.close > r["high"]:
            r["break_k"], r["break_at"] = highest_square_below(bar.close), self.candle_no
            r["break_why"] = (f"second entry: after the first move the market went sideways under its high {r['high']:g}; "
                              f"candle {when:%H:%M} closed {bar.close:g} above it -> entry on the retest of the "
                              f"square {r['break_k'] ** 2}")
            return None
        r["high"] = max(r["high"], bar.high)
        return None

    def sync_capital(self) -> None:
        """Live bot, after each candle: tell the shared ledger how much money this bot has in open trades."""
        if self.capital:
            self.capital.hold(sum(t.qty * t.entry_fill for _, t in self.open_trades if t.qty))

    def realized_rupees(self) -> float:
        return sum(t.pnl_points * t.qty for t in self.trades if t.exit_reason and t.qty)

    def _next_trade_allowed(self) -> bool:
        """Owner, 2026-09-30: after the day's first trade, trade again only if it was stopped out.
        A target, trailing stop or time exit ends the day; an open trade blocks new entries."""
        if self.max_loss and self.allocation and risk_left(self.max_loss, self.realized_rupees()) <= 0:
            return False  # owner, 2026-10-12: today's loss limit reached - no more trades
        if not self.trades:
            return True
        if self.ride_normal_days:
            # owner, 2026-10-09/12: whatever the last exit - normal day up to 2 trades, buyer's day up to 4
            limit = BUYERS_DAY_MAX_TRADES if self.buyers_day else NORMAL_DAY_MAX_TRADES
            return not self.open_trades and len(self.trades) < limit
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
        if RETEST_ONLY and not pending.limit_only:
            if pending.has_limit:
                return (k, min(float(limit), bar.open) if bar.open is not None else float(limit)) if bar.low <= limit else None
            if pending.armed_at is None:
                if bar.close > stop:
                    pending.armed_at = 1  # closed above the square - the next candle(s) may retest it
                return None
            return (k + 1, min(float(stop), bar.open) if bar.open is not None else float(stop)) if bar.low <= stop else None
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
              atm_below_sniper: bool = False, fixed_sl: bool = False, trigger: Optional[float] = None,
              reentry: bool = False, reason: str = "", stop: Optional[float] = None) -> list[Event]:
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
            entry_reason=reason,
        )
        if reentry:  # owner, 2026-10-13: a re-entry's SL is 25 points below the buy price (143.74 -> 118.74)
            trade.stop_loss = round(stop if stop is not None else price - REENTRY_SL_POINTS, 2)
            trade.trail_stop = float(trade.stop_loss)
        if setup.contract:  # the sideways-day ATM (U/V) trade: SL = the square below the buy price, target +2 squares
            k_low = math.isqrt(int(price))
            trade.stop_loss = k_low * k_low
            trade.trail_stop = float(trade.stop_loss)
            trade.target = (k_low + 2) ** 2
            self.uv_trades[id(trade)] = {"first": (k_low + 1) ** 2, "touched_at": self.candle_no if bar.high >= (k_low + 1) ** 2 else None}
        if self.allocation and self.lot:
            # Owner, 2026-10-12: as many lots as the allotment buys, cut so a stop-out stays within today's loss limit
            money = self.capital.available(self.allocation) if self.capital else self.allocation
            trade.qty = size_qty(money, risk_left(self.max_loss, self.realized_rupees()), self.lot,
                                 price, float(trade.stop_loss))
            if trade.qty == 0:
                return []  # not even one lot fits - no trade
        self.trades.append(trade)
        self.trade_range[id(trade)] = [bar.low, bar.high]  # the move's low includes the entry candle
        events = [Event("ENTRY", trade, body_entry=fixed_sl)]
        stop_exit = self._stop_hit(bar, trade.stop_loss, False) if fill_candle else None
        if stop_exit is not None:  # filled and stopped in the same candle
            events.append(self._close(trade, when, stop_exit, "STOPLOSS"))
            return events
        if fixed_sl:
            self.fixed_sl.add(id(trade))
        elif self.trailing and not SQUARE_LADDER_TSL:
            # (16-10: with the square ladder nothing moves until 2 squares - the old close-trail on the entry candle
            # had put SENSEX 74100 CE 841's SL at 841 the moment it was bought)
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
