"""
HLC strategy, candle by candle (rules in PROJECT_STATUS.md, "HLC strategy").

Per 5-minute candle the engine gets the index candle and the option candles of
the strikes around the index. Trades (max 2 a day, one at a time, entries on
candles closing 09:30-14:55):

  FIB trade   - (owner, 2026-09-30; replaced the 09:30 gap trade) the first
                5-minute index candle's range, reverse Fibonacci FIB_ENTRY
                (0.75 - owner, confirmed 2026-10-01). Side =
                where the last closed candle sits against yesterday's close
                (above -> CE, below -> PE; can change until the entry). The
                Fib is drawn along the first candle's swing (owner, 2026-10-01
                - not its colour): low first then high (up) -> level = high -
                0.75 x range, reached when the index dips to it; high first
                (down) -> level = low + 0.75 x range, reached when the index
                rises to it. Only candles from 09:30 on (the 09:25 one
                doesn't count, owner 01-10). SL on the INDEX: CE = first
                candle low, PE = first candle high. Targets R1 then R2 (CE) /
                S1 then S2 (PE) - never beyond R2/S2. One FIB trade a day.
  CONFIRM     - (owner, 2026-10-01, "double confirmation") side from yesterday's
                close as for FIB. The index comes back into the first candle's
                Fib 0.75-0.786 zone from outside (PE: from above, zone = low +
                0.75..0.786 x range; CE: from below, zone = high - 0.75..0.786 x
                range) AND the ATM premium of that side shows an up-reversal
                pattern on the same candle or one candle before/after -> buy at
                the close. SL = points (50 SENSEX / 25 NIFTY), targets S1 -> S2
                (PE) / R1 -> R2 (CE). 01-10 SENSEX: 10:40 PE Bullish Engulfing
                (owner's Morning Star) + 10:45 index low 72391.92 -> PE @ 235.05.
  BREAKOUT    - (owner, 2026-10-01, buyer's day) after a trade booked at a
                target: premium high -> the premium closes above it; index
                level -> the index closes beyond it => buy the same option again,
                targets the next premium high / index levels up to S3 / R3.
                On a buyer's day there is no 2-a-day limit and no "only after
                a stop-out" rule.
  REVERSAL    - index shows a support pattern at S1/S2/S3 AND the ATM CE premium
                shows an up-reversal pattern -> buy ATM CE. Index shows a
                resistance pattern at R1/R2/R3 AND the ATM PE premium shows an
                up-reversal pattern -> buy ATM PE.

  Strike = the morning ATM (owner, 2026-09-29: even if the balanced strike
  has moved by 09:30). Except on a BIG GAP day (opens above R2 or below S2 -
  owner, 2026-10-05; was |open - close| >= 150 NIFTY / 300 SENSEX): every trade uses the strike nearest the index at
  entry, and the trade has no level targets (owner, 2026-10-05): it exits on
  the next index reversal pattern against it (Doji/Spinning Top don't
  count). Fill = the option's candle close.
  Trailing SL on EVERY trade (owner, 2026-10-07; big-gap days only since
  05-10): once the premium is 100 (SENSEX) / 50 (NIFTY) points up, the SL
  trails that far below the premium's high - first at cost, then up with it.
  SL = entry premium - 25 points (NIFTY) / 50 (SENSEX) (owner, 2026-09-29).
  If the premium is too low for that (entry - points <= 0) (owner, 2026-09-29):
    * from 13:30 (about 4 hours of trading, so the day low means something):
      buy at the close, SL = the option's day low so far - 1 point;
    * before 13:30 (e.g. expiry-day morning): buy only if the NEXT candle
      trades above the confirmation candle's high (filled at that high, or
      the open if it gaps above), SL = below the lowest low of the last 2
      candles (confirmation candle and the one before). Not triggered on the
      next candle -> cancelled.
  PANIC side (owner, 2026-10-01): a trade on the side whose leg was PANIC
  yesterday also has PREMIUM targets - yesterday's high, then the earlier
  daily highs of the same option, each higher than the last (as many days
  back as the data goes). Whichever comes first, index level or premium
  high, counts: touched without closing above -> exit; a premium candle
  closing above the high -> the next earlier high becomes the target.
  Targets = levels. PE: the levels below the index, one by one; CE: the
  levels above. Final target: the last level (S3/R3) for a gap trade, the
  yesterday's Close for a reversal trade. When the index touches a target:
  if it's the final one, or the candle closes back on our side of it -> exit;
  if the candle closes beyond it -> the index SL moves to that level and the
  next level becomes the target. Exit also when a candle closes back across
  the trailed level, or at 15:00.

  PANIC side takes over (owner, 2026-09-29): if yesterday's ATM PE was PANIC
  (closed near its high) and today the ATM PE trades above yesterday's PE
  high, the PE side dominates - no CE trades for the rest of the day. Same
  for a PANIC CE breaking its high -> no PE trades.

  Exits are at the option's candle close (at the SL level for a premium SL).
  A premium SL is checked before the targets (conservative).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

from sizing import risk_left, size_qty
from hlc_signal import (DIRECTIONLESS, Candle, HlcLevels, HlcMarket, OptionType, bearish_pattern, bullish_pattern,
                        leg_label)

FIRST_ENTRY_CLOSE = time(9, 30)
DAY_LOW_SL_FROM = time(13, 30)
FIB_ENTRY = 0.75  # owner, 2026-10-01 (confirmed 0.75 after briefly choosing 0.618)
TREND_FIB = 0.618  # pattern TREND trade: entry at the confirmation candle's Fib 0.618 (owner, 2026-10-08)
CONFIRM_ZONE = (0.75, 0.786)  # owner, 2026-10-01: double-confirmation trade's index zone
FIB_FIRST_CANDLE = time(9, 30)  # owner, 2026-10-01: the level must be reached AFTER 09:30 - the 09:25 candle doesn't count
LAST_ENTRY_CLOSE = time(14, 55)
EXIT_CLOSE = time(15, 0)
REENTRY_POINTS_SL = True  # owner, 2026-10-13: re-entries use entry - 25 / 50 points
SWING_LOW_SL = True  # owner, 2026-10-12: SL = the candle before the entry candle's low - 1 (was -25 / -50 points)
PB_FIB = 0.786  # PROFIT BOOKING side exit: Fib 0.786 of yesterday's close -> high (owner, 2026-10-12)
PANIC_BLOCK = False  # owner, 2026-10-12: both sides (PROFIT BOOKING and PANIC) can trade - the index decides (29-09 block off)
SECOND_ENTRY_PM_REVERSAL = True  # owner 13-10 (all bots): after the morning trade one more, from 12:30, reversal + confirmation, SL reversal low - 1
R3_S3_FULL_PROFIT = True
# Owner, 2026-10-15: momentum - after an R3/S3 touch, and on a day that opened above R1 (CE) / below S1 (PE), the move
# usually runs on (some days it reverses at once): no level-target exit, ride with the profit lock TSL instead.
MOMENTUM_RIDE = True
# Owner, 2026-10-16: the retest decides, but when the market gives the OTHER confirmation, change sides. A losing trade
# whose index shows a reversal against it AND whose own premium shows a top (16-10 NIFTY PE: 09:40 index Morning Star +
# PE Evening Star) -> exit at that close; then the other side is taken when the index closes beyond yesterday's close
# (09:55, 23026.95 -> CE 136.65) - before 12:30 too, once.
FLIP_ON_CONFIRMATION = True
# Owner, 2026-10-16: index Fib from yesterday's close (0) to R2 (1) - 0.786 is the institutions' profit area: the first
# target (PE: close -> S2). A later candle CLOSING beyond 0.786 is a re-entry (targets R2 -> R3), once a day.
INDEX_FIB_TARGET = 0.786
# Owner, 2026-10-16 (SENSEX turned at the 0.618 golden ratio, NIFTY at 0.786): a Fib ladder - the first unreached level
# is the target; a close beyond it re-enters with the next level as the target (then R2 -> R3). Once per level.
INDEX_FIB_LEVELS = (0.618, 0.786)
# Owner, 2026-10-16 (later): replaces the 0.618/0.786 ladder + break re-entries. Non-momentum days: the target is R2 (PE:
# S2); if it doesn't get there - once the index has crossed the Fib 0.75 of close -> R2, a reversal candle on the index
# books it (at 0.786 if that was touched, else 0.75). Momentum days keep riding with the profit lock.
R2_OR_FIB_REVERSAL = True
# Owner, 2026-10-16: the side is decided by the index breaking its first 5-minute candle (close above its high -> CE,
# below its low -> PE) with that side's premium also closing above its own first 5-minute high; the NEXT candle must
# confirm (index on in the same direction, premium green) -> entry at that close.
FIRST_BREAK_CONFIRM = True
BOTH_PB_BUYERS_DAY = True  # owner 16-10: CE and PE both PROFIT BOOKING yesterday is a buyer's day too  # owner, 2026-10-13: the index touching R3 / S3 = full profit - close and no more trades today
NORMAL_DAY_MAX_TRADES = 2  # owner, 2026-10-09: non-buyer's days - 2 trades, no target exits (trailing only)
MAX_TRADES = 4  # owner 08-10: pattern + 15-min retest TREND entries both on -> 4 a day (was 2)
CANDLE = timedelta(minutes=5)
ATM_SEARCH_STEPS = 6


@dataclass
class HlcTrade:
    date: str
    kind: str  # GAP | REVERSAL
    side: OptionType
    strike: float
    pattern: str  # index pattern + premium pattern, or "gap"
    entry_time: str
    entry_fill: float
    entry_index: float
    sl_premium: float
    targets: list[tuple[str, float]] = field(default_factory=list)
    trail_level: Optional[tuple[str, float]] = None
    big_gap: bool = False  # big-gap day: strike near the index, exit when the index pattern turns
    sl_rule: str = ""
    index_sl: Optional[float] = None  # FIB trade: exit when the index crosses this
    premium_targets: list[float] = field(default_factory=list)  # PANIC side: earlier daily highs, next one first
    premium_high: float = 0.0  # highest premium since entry (for the trailing SL)
    premium_trail: Optional[float] = None  # PANIC side: last premium high closed above (information)
    qty: int = 0  # owner, 2026-10-12: sized per trade (0 = the bot's fixed quantity)
    lock_seen: Optional[tuple[float, int]] = None  # profit lock: (profit reached, candle no.) waiting for a confirming close
    lock_level: float = 0.0  # profit lock: premium SL locking +N x step (owner, 13-10)
    lock_why: str = ""
    pb_target: Optional[float] = None  # PROFIT BOOKING side: Fib 0.786 of yesterday's close -> high (owner, 12-10)
    pb_index: Optional[tuple[str, float]] = None  # ... or the index reaching S2 (PE) / R2 (CE)
    index_best: Optional[float] = None  # R2_OR_FIB_REVERSAL: the index's best level since entry
    fib_from: float = -1.0  # INDEX_FIB_LEVELS: the Fib ratio this re-entry broke (its target is the next one)
    uv: Optional[dict] = None  # expiry-day PANIC-side U/V trade (owner 13-10): {"first": (k+1)^2, "target": (k+2)^2, "touched_at"}
    exit_time: str = ""
    exit_premium: float = 0.0
    exit_reason: str = ""
    pnl_points: float = 0.0


def _closes_at(when: datetime) -> time:
    return (when + CANDLE).time()


class HlcDay:
    def __init__(self, day: date, levels: HlcLevels, market: HlcMarket,
                 yesterday: Optional[dict[str, tuple[float, float, float]]] = None):
        """`yesterday`: {"CE": (high, low, close), "PE": (...)} of the morning ATM's options."""
        self.day = day
        self.yesterday = yesterday or {}
        self.blocked: dict[str, str] = {}  # side -> why no trades on that side today
        self.levels = levels
        self.market = market
        self.trades: list[HlcTrade] = []
        self.open_trade: Optional[HlcTrade] = None
        self.day_open: Optional[float] = None
        self.gap_done = False  # the day's FIB trade has been taken
        self.daily_highs: dict[str, list[float]] = {}  # side -> morning ATM option's daily highs, yesterday first
        self.zone_touched_at: Optional[int] = None
        # Owner, 2026-10-08: day-side TREND trade on 15-minute closes vs the first 15-minute close
        self.first5_high: dict[str, float] = {}  # owner, 2026-10-09: day side's first 5-minute candle high (BREAK)
        self.break_done = False
        self.close_retest_done = False
        self.level_break_done = False  # owner, 2026-10-13: 15-minute R1/S1 break entry, once a day
        self.capital = None  # live bot: shared Rs 5 lakh ledger (SENSEX first); None = the fixed allotment  # owner, 2026-10-12: index close-retest entry, once a day
        self.first15_close: dict[str, float] = {}
        self.went_above: dict[str, int] = {}  # side -> candle no. when its premium closed above the first 15-min close
        # Owner, 2026-10-08: day-side pattern TREND trade - premium reversal pattern, retest, buy limit at the Fib 0.618
        self.trend_pattern: dict[str, tuple[int, float, float, str]] = {}  # side -> (candle no, low, high, name)
        self.trend_order: Optional[dict] = None  # side, strike, limit, pattern_low, at, why  # index_history position of the last CONFIRM zone touch
        self.first_swing: Optional[OptionType] = None  # set from 1-minute data: "CE" = low came first, "PE" = high first
        self.big_gap = False
        self.index_history: list[Candle] = []
        self.premium_history: dict[tuple[float, str], list[Candle]] = {}
        self.done = False
        self.pending: Optional[dict] = None  # low-premium buy stop above the confirmation candle
        # Owner, 2026-10-13: expiry day + PB/PANIC day - after the profit booking the PANIC side falls to a new low and
        # turns (U / V): a reversal candle there, then a green confirmation candle -> buy the PANIC side's ATM.
        self.expiry_day = False  # set by the live bot (today is the contract's expiry)
        self.expiry_uv: Optional[dict] = None  # {"side", "at", "low", "high", "name", "confirm"}
        self.expiry_uv_done = False
        self.second_rev: Optional[dict] = None  # owner 13-10: the 12:30+ reversal entry - {"at", "low", "name", "confirm"}
        self.fib_reentry: Optional[dict] = None  # INDEX_FIB_TARGET: {"side", "ratio", "level", "at", "done"}
        self.fib_used: set[float] = set()  # ratios already re-entered on
        self.flip: Optional[dict] = None  # FLIP_ON_CONFIRMATION: {"side", "at", "why"} - the side to take next
        self.full_profit: Optional[str] = None  # owner 13-10: the index touched R3 / S3 -> full profit, no more trades

    # --- helpers ---

    def live_atm(self, index_close: float, chain: dict[tuple[float, str], Candle]) -> Optional[float]:
        step = self.market.strike_step
        nearest = round(index_close / step) * step
        best, best_gap = None, None
        for i in range(-ATM_SEARCH_STEPS, ATM_SEARCH_STEPS + 1):
            strike = nearest + i * step
            ce, pe = chain.get((strike, "CE")), chain.get((strike, "PE"))
            if ce is None or pe is None:
                continue
            gap = abs(ce.close - pe.close)
            if best_gap is None or gap < best_gap:
                best, best_gap = strike, gap
        return best

    def _targets(self, side: OptionType, index_price: float, final: str) -> list[tuple[str, float]]:
        ladder = self.levels.ladder()
        if side == "PE":
            below = [lv for lv in reversed(ladder) if lv[1] < index_price]
            return below[: next((i + 1 for i, lv in enumerate(below) if lv[0] == final), len(below))]
        above = [lv for lv in ladder if lv[1] > index_price]
        return above[: next((i + 1 for i, lv in enumerate(above) if lv[0] == final), len(above))]

    def _level_near(self, price: float, names: tuple[str, ...]) -> Optional[str]:
        for name, value in self.levels.ladder():
            if name in names and abs(price - value) <= self.market.level_tolerance:
                return name
        return None

    def _exit(self, trade: HlcTrade, when: datetime, premium: float, reason: str) -> str:
        trade.exit_time = when.isoformat()
        trade.exit_premium = round(premium, 2)
        trade.exit_reason = reason
        trade.pnl_points = round(premium - trade.entry_fill, 2)
        self.open_trade = None
        return (f"EXIT {trade.side} {trade.strike:g} at {premium:.2f} - {reason} "
                f"(bought {trade.entry_fill:.2f}, {trade.pnl_points:+.2f} points)")

    def _enter(self, kind: str, side: OptionType, strike: float, when: datetime, prem: Candle, index: Candle,
               pattern: str, final: str, from_level: Optional[float] = None) -> Optional[str]:
        # A reversal AT a level targets the levels beyond it, never that level itself (05-10 NIFTY: a PE at R1
        # with the index just above R1 took R1 as its target and exited one candle later at +1.55).
        start = index.close if from_level is None else (min(index.close, from_level) if side == "PE" else max(index.close, from_level))
        if from_level is not None:
            start = start - 0.01 if side == "PE" else start + 0.01
        targets = self._targets(side, start, final)
        if not targets or side in self.blocked:
            return None
        if self.trades and REENTRY_POINTS_SL:
            # Owner, 2026-10-13: a re-entry (any trade after the day's first) - SL = entry - 25 (NIFTY) / 50 (SENSEX)
            sl, sl_rule = round(prem.close - self.market.sl_points, 2), f"re-entry {self.market.sl_points:g} points"
        elif SWING_LOW_SL:
            # Owner, 2026-10-12: HLC SL = the low of the candle BEFORE the entry candle - 1 point (was entry - 25 / 50
            # points, 29-09). Sniper keeps its square SL on a body close.
            history = self.premium_history.get((strike, side), [prem])
            before = history[-2] if len(history) >= 2 else history[-1]
            if before.low >= prem.close:  # a limit fill below the previous candle (13-10 TREND: SL came out above entry)
                before = Candle(before.open, before.high, min(before.low, prem.low), before.close)
            sl, sl_rule = round(before.low - 1, 2), "previous candle low - 1"
            if prem.close - before.low > self.market.far_sl_points:
                # owner, 2026-10-13: a far SL (SENSEX > 100 / NIFTY > 40 points) -> Fib 0.618 up from that low, 1 below
                # (13-10 SENSEX: entry 788, low 614.10 -> 614.10 + 0.618 x 173.9 = 721.6 -> SL 720.6)
                sl = round(before.low + 0.618 * (prem.close - before.low) - 1, 2)
                sl_rule = "Fib 0.618 of the previous low - 1"
        else:
            sl, sl_rule = prem.close - self.market.sl_points, f"{self.market.sl_points:g} points"
        if sl <= 0:  # premium too low for a points SL
            history = self.premium_history.get((strike, side), [prem])
            if _closes_at(when) >= DAY_LOW_SL_FROM:
                sl, sl_rule = max(min(c.low for c in history) - 1, 0.05), "day low - 1"
            else:  # wait for the next candle to break this candle's high
                self.pending = dict(kind=kind, side=side, strike=strike, stop=prem.high, pattern=pattern, final=final,
                                    sl=round(min(c.low for c in history[-2:]), 2))
                return (f"ORDER {side} {strike:g}: low premium {prem.close:.2f} - buy only above this candle's high "
                        f"{prem.high:.2f} on the next candle, SL {self.pending['sl']:.2f} (2-candle low)")
        trade = HlcTrade(date=self.day.isoformat(), kind=kind, side=side, strike=strike, pattern=pattern,
                         entry_time=when.isoformat(), entry_fill=round(prem.close, 2), entry_index=index.close,
                         sl_premium=round(sl, 2), sl_rule=sl_rule, targets=targets,
                         big_gap=self.big_gap)
        trade.premium_targets = self.premium_ladder(trade.side, trade.strike, trade.entry_fill)
        self._profit_booking_exits(trade)
        if not self._size(trade):
            return None  # owner 12-10: not even one lot fits the allotment / loss limit
        self.trades.append(trade)
        self.open_trade = trade
        names = " -> ".join(f"{n} {v:g}" for n, v in targets)
        return (f"BUY {side} {strike:g} at {prem.close:.2f} ({kind}, {pattern}; index {index.close:.2f}) - "
                f"SL {trade.sl_premium:.2f}, targets {names}")

    # --- per candle ---

    def on_candle(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle]) -> list[str]:
        if self.done:
            return []
        events: list[str] = []
        closes = _closes_at(when)
        if self.day_open is None:
            self.day_open = index.open
            # Owner, 2026-10-05: a big gap = the day OPENS above R2 or below S2 (was |open - close| >= 150/300)
            ladder = dict(self.levels.ladder())
            self.big_gap = index.open > ladder["R2"] or index.open < ladder["S2"]
        self.index_history.append(index)
        for key, candle in chain.items():
            self.premium_history.setdefault(key, []).append(candle)

        for side, other in (("PE", "CE"), ("CE", "PE")):
            hlc = self.yesterday.get(side)
            candle = chain.get((self.levels.atm, side))
            if PANIC_BLOCK and hlc and candle and other not in self.blocked and leg_label(*hlc) == "PANIC" and candle.close > hlc[0]:
                # owner, 2026-10-12: a body CLOSE above yesterday's high (a wick isn't enough - 12-10's 09:15 CE spike)
                self.blocked[other] = f"{side} PANIC yesterday and closed above its high {hlc[0]:g} today"
                events.append(f"No {other} trades today - {self.blocked[other]}")

        self._track_trend(when)
        self._track_trend_patterns(chain)
        self._track_expiry_uv()
        self._track_first_break(when)
        self._track_second_reversal()

        if len(self.index_history) >= 3 and self._zone_touch(index):
            self.zone_touched_at = len(self.index_history) - 1

        if self.pending is not None:
            order, self.pending = self.pending, None
            prem = chain.get((order["strike"], order["side"]))
            if prem is not None and prem.high >= order["stop"] and order["side"] not in self.blocked:
                fill = Candle(prem.open, prem.high, prem.low, max(order["stop"], prem.open))
                event = self._open_filled(order, when, fill, index)
                if event:
                    events.append(event)
            else:
                events.append(f"Order {order['side']} {order['strike']:g} above {order['stop']:.2f} cancelled - not triggered")

        if R3_S3_FULL_PROFIT and self.full_profit is None and not self.big_gap and (index.high >= self.levels.r3 or index.low <= self.levels.s3):
            # Owner, 2026-10-13 (NIFTY touched R3 22567 at 11:00): an R3 / S3 touch = the day's full profit - close what
            # is open and take no more trades today (NIFTY and SENSEX). (Big-gap days open beyond R2/S2 - not counted.)
            name, value = ("R3", self.levels.r3) if index.high >= self.levels.r3 else ("S3", self.levels.s3)
            if MOMENTUM_RIDE and self.market.profit_lock_step:
                # owner 15-10: no exit at R3/S3 - the open trade rides with the profit lock; no new trades today
                self.full_profit = (f"index touched {name} {value:g} in candle {when:%H:%M} - full profit: no new trades "
                                    f"today, an open trade rides with the profit lock")
                events.append(self.full_profit)
            else:
                self.full_profit = f"index touched {name} {value:g} in candle {when:%H:%M} - full profit, no more trades today"
                events.append(self.full_profit)
                events += self.close_now(when, chain, self.full_profit)
                self.done = True
                return events

        trade = self.open_trade
        if trade is not None and trade.entry_time != when.isoformat():
            prem = chain.get((trade.strike, trade.side))
            if prem is not None:
                events += self._manage(trade, when, index, prem, closes)

        if closes >= EXIT_CLOSE:
            self.done = True
            return events
        if self.full_profit is not None:
            return events  # owner 13-10 / 15-10: after R3/S3 no new trades
        if self.open_trade is not None or self.pending is not None:
            return events
        if self.market.max_loss and self.market.allocation and risk_left(self.market.max_loss, self.realized_rupees()) <= 0:
            return events  # owner, 2026-10-12: today's loss limit reached - no more trades
        if len(self.trades) >= (MAX_TRADES if self.buyers_day() else NORMAL_DAY_MAX_TRADES):
            # Owner, 2026-10-09: buyer's day 4 (was unlimited); other days 2, riding with the trailing SL.
            return events
        if not (FIRST_ENTRY_CLOSE <= closes <= LAST_ENTRY_CLOSE):
            return events
        if INDEX_FIB_TARGET and self.fib_reentry is not None and not self.fib_reentry.get("done") and len(self.trades) < MAX_TRADES:
            f = self.fib_reentry
            beyond = index.close > f["level"] if f["side"] == "CE" else index.close < f["level"]
            if len(self.index_history) > f["at"] and beyond and (self.levels.atm, f["side"]) in chain:
                f["done"] = True
                self.fib_used.add(f["ratio"])
                event = self._enter(f"FIB {f['ratio']:g} BREAK", f["side"], self.levels.atm, when,
                                    chain[(self.levels.atm, f["side"])], index,
                                    f"index closed {index.close:.2f} beyond the Fib {f['ratio']:g} {f['level']:g}",
                                    "R3" if f["side"] == "CE" else "S3")
                if event:
                    self.open_trade.fib_from = f["ratio"]
                    return events + [self._with_premium_targets(event)]
        if FLIP_ON_CONFIRMATION and self.flip is not None and not self.flip.get("done"):
            f = self.flip
            beyond = index.close > self.levels.close if f["side"] == "CE" else index.close < self.levels.close
            if len(self.index_history) > f["at"] and beyond and (self.levels.atm, f["side"]) in chain:
                f["done"] = True
                event = self._enter("FLIP", f["side"], self.levels.atm, when, chain[(self.levels.atm, f["side"])], index,
                                    f"after {f['why']}, index closed {index.close:.2f} "
                                    f"{'above' if f['side'] == 'CE' else 'below'} yesterday's close {self.levels.close:g}",
                                    "R3" if f["side"] == "CE" else "S3")
                if event:
                    return events + [self._with_premium_targets(event)]
        if SECOND_ENTRY_PM_REVERSAL and self.trades:
            event = self._second_reversal_entry(when, index, chain) if len(self.trades) < 2 else None
            return events + ([event] if event else [])
        if not self.buyers_day():
            # Owner, 2026-10-13: normal day - one entry 09:30-12:00 and one 12:30-15:00 (each with its own signal)
            window = "am" if closes <= time(12, 0) else "pm" if closes >= time(12, 30) else None
            if window is None or any(self._window_of(t) == window for t in self.trades):
                return events

        atm = self.levels.atm
        if self.big_gap:  # big gap: the round strike nearest the market now
            atm = float(round(index.close / self.market.strike_step) * self.market.strike_step)
        if (atm, "CE") not in chain or (atm, "PE") not in chain:
            return events

        event = self._expiry_uv_entry(when, index, chain)
        if event:
            return events + [event]

        event = (self._close_retest_entry(when, index, chain) or self._level_break_entry(when, index, chain)
                 or self._break_entry(when, index, chain) or self._pattern_trend_entry(when, index, chain)
                 or self._trend_entry(when, index, chain))
        if event:
            return events + [self._with_premium_targets(event)]

        if not self.gap_done and not self.trades and len(self.index_history) >= 2:
            # Owner, 2026-10-05: the FIB trade is only ever the day's FIRST entry (05-10 it fired as a second
            # trade at 12:10, far below the level, and lost)
            event = self._fib_entry(when, index, chain, atm)
            if event:
                return events + [self._with_premium_targets(event)]

        event = self._confirm_entry(when, index, chain, atm)
        if event:
            return events + [self._with_premium_targets(event)]

        event = self._breakout_entry(when, index, chain, atm)
        if event:
            return events + [self._with_premium_targets(event)]

        up = bullish_pattern(self.index_history[-3:])
        if up:
            span_low = min(c.low for c in self.index_history[-up[1]:])
            level = self._level_near(span_low, ("S1", "S2", "S3"))
            ce_history = self.premium_history.get((atm, "CE"), [])
            prem_pattern = bullish_pattern(ce_history[-3:])
            if level and prem_pattern and not self._against_the_day("CE", index, chain[(atm, "CE")]):
                event = self._enter("REVERSAL", "CE", atm, when, chain[(atm, "CE")], index,
                                    f"index {up[0]} at {level}, CE {prem_pattern[0]}", "Close",
                                    dict(self.levels.ladder())[level])
                if event:
                    return events + [event]

        down = bearish_pattern(self.index_history[-3:])
        if down:
            span_high = max(c.high for c in self.index_history[-down[1]:])
            level = self._level_near(span_high, ("R1", "R2", "R3"))
            pe_history = self.premium_history.get((atm, "PE"), [])
            prem_pattern = bullish_pattern(pe_history[-3:])
            if level and prem_pattern and not self._against_the_day("PE", index, chain[(atm, "PE")]):
                event = self._enter("REVERSAL", "PE", atm, when, chain[(atm, "PE")], index,
                                    f"index {down[0]} at {level}, PE {prem_pattern[0]}", "Close",
                                    dict(self.levels.ladder())[level])
                if event:
                    return events + [event]
        return events

    def day_side(self, index: Candle, chain: dict[tuple[float, str], Candle]) -> Optional[OptionType]:
        """PE day: index below yesterday's close and the ATM CE below its own close; CE day: the mirror."""
        atm = self.levels.atm
        ce, pe = chain.get((atm, "CE")), chain.get((atm, "PE"))
        y_ce, y_pe = self.yesterday.get("CE"), self.yesterday.get("PE")
        if ce and y_ce and index.close < self.levels.close and ce.close < y_ce[2]:
            return "PE"
        if pe and y_pe and index.close > self.levels.close and pe.close < y_pe[2]:
            return "CE"
        return None

    def _track_trend(self, when: datetime) -> None:
        """Owner, 2026-10-08: the morning ATM premium's first 15-minute candle (09:15-09:30) close per side, and
        whether the premium has since CLOSED above it (the move away that a retest comes back from)."""
        atm = self.levels.atm
        for side in ("CE", "PE"):
            history = self.premium_history.get((atm, side), [])
            if not history:
                continue
            if len(history) == 1:
                self.first5_high[side] = history[0].high
            if _closes_at(when) == time(9, 30):
                self.first15_close[side] = history[-1].close
            elif (side in self.first15_close and side not in self.went_above
                  and history[-1].close > self.first15_close[side]):
                self.went_above[side] = len(history) - 1

    def _level_break_entry(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle]) -> Optional[str]:
        """Owner, 2026-10-13: the index OPENED above yesterday's close and a 15-minute candle closes above R1 -> buy
        the ATM CE at that close (mirror: opened below the close, a 15-minute candle closes below S1 -> PE). E.g. CE
        PROFIT BOOKING: it can run to R2/R3, and our target comes before that. Once a day."""
        if self.level_break_done or self.day_open is None or _closes_at(when).minute % 15 or len(self.index_history) < 3:
            return None
        close15 = index.close  # the 15-minute candle closes with this 5-minute candle
        ladder = dict(self.levels.ladder())
        if self.day_open > self.levels.close and close15 > ladder["R1"]:
            side: OptionType = "CE"
        elif self.day_open < self.levels.close and close15 < ladder["S1"]:
            side = "PE"
        else:
            return None
        atm = self.levels.atm
        if (atm, side) not in chain or side in self.blocked:
            return None
        self.level_break_done = True
        name = "R1" if side == "CE" else "S1"
        return self._enter("LEVEL", side, atm, when, chain[(atm, side)], index,
                           f"opened {'above' if side == 'CE' else 'below'} the close, 15-min close {close15:g} beyond {name}",
                           "R3" if side == "CE" else "S3", ladder[name])

    def _close_retest_entry(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle]) -> Optional[str]:
        """Owner, 2026-10-12: the index has closed below yesterday's close (even before 09:30), a candle comes back to
        retest it (its high reaches the close, within the level tolerance), and the NEXT candle closes below the close
        again -> buy the ATM PE at that close. Mirror for CE. 12-10 SENSEX (close 72472.3): 09:20 closed 72423, 09:25
        retested (72589), 09:30 closed 72447 -> PE 72600 @ 529.30. Once a day; SL -50/-25, targets the next levels."""
        if self.close_retest_done or len(self.index_history) < 3 or when.time() < time(9, 30):
            return None  # owner: "our condition is after 09:30" - the 09:25 candle can be the retest, not the entry
        close, tol = self.levels.close, self.market.level_tolerance
        before, retest, now = self.index_history[-3], self.index_history[-2], index
        # the confirming candle must move the trade's way (owner, 12-10: NIFTY's 09:30 candle closed above the close
        # but was RED - 22584 -> 22535 - so it was no CE confirmation)
        if before.close < close and retest.high >= close - tol and now.close < close and now.red:
            side: OptionType = "PE"  # was below, came back up to the close, closed below again on a red candle
        elif before.close > close and retest.low <= close + tol and now.close > close and now.green:
            side = "CE"
        else:
            return None
        atm = self.levels.atm
        if (atm, side) not in chain or side in self.blocked:
            return None
        self.close_retest_done = True
        return self._enter("RETEST", side, atm, when, chain[(atm, side)], index,
                           f"index retested the close {close:g} and closed {'below' if side == 'PE' else 'above'} it again",
                           "S3" if side == "PE" else "R3")

    def _break_entry(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle]) -> Optional[str]:
        """Owner, 2026-10-09: on a CE day (PE day) the CE (PE) premium CLOSES strongly above its first 5-minute candle's
        high -> buy at that close. The day's first entry, once. 09-10 SENSEX: 71600 CE first candle high 859, the
        09:25 candle closed 882.45 -> 882 (owner's trade). SL -50/-25, targets the next index levels, trailing."""
        if self.break_done or self.trades:
            return None
        if FIRST_BREAK_CONFIRM:
            return self._first_break_confirm(when, index, chain)
        side = self.day_side(index, chain)
        atm = self.levels.atm
        history = self.premium_history.get((atm, side), []) if side else []
        if side is None or side not in self.first5_high or len(history) < 2:
            return None
        high, c = self.first5_high[side], history[-1]
        if c.close <= high or any(x.close > high for x in history[1:-1]):
            return None  # needs the FIRST close above the first candle's high
        self.break_done = True
        return self._enter("BREAK", side, atm, when, chain[(atm, side)], index,
                           f"{side} closed {c.close:g} above its first 5-min high {high:g}",
                           "S3" if side == "PE" else "R3")

    def _track_first_break(self, when: datetime) -> None:
        """Owner, 2026-10-16 - see FIRST_BREAK_CONFIRM. Runs every candle (the break can come before 09:30)."""
        if not FIRST_BREAK_CONFIRM or self.break_done or len(self.index_history) < 2:
            return
        atm, first, index = self.levels.atm, self.index_history[0], self.index_history[-1]
        n = len(self.index_history)
        st = getattr(self, "_fb", None)
        if st is not None and n == st["at"] + 1:
            side = st["side"]
            prem = (self.premium_history.get((atm, side)) or [None])[-1]
            prev = self.index_history[-2]
            on = index.close > prev.close if side == "CE" else index.close < prev.close
            self._fb = None
            if prem is not None and on and prem.close > prem.open:
                self._fb_ready = {"side": side, "at": n, "when": when}
                return
        if getattr(self, "_fb", None) is not None:
            return
        for side, broke in (("CE", index.close > first.high), ("PE", index.close < first.low)):
            hist = self.premium_history.get((atm, side), [])
            if broke and side in self.first5_high and len(hist) > 1 and hist[-1].close > self.first5_high[side]:
                self._fb = {"side": side, "at": n}  # broken together - the next candle must confirm

    def _first_break_confirm(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle]) -> Optional[str]:
        ready = getattr(self, "_fb_ready", None)
        if ready is None or ready["at"] != len(self.index_history):
            return None
        side, atm, first = ready["side"], self.levels.atm, self.index_history[0]
        if (atm, side) not in chain:
            return None
        self.break_done = True
        return self._enter("FIRST BREAK", side, atm, when, chain[(atm, side)], index,
                           f"index closed beyond its first 5-min {'high' if side == 'CE' else 'low'} "
                           f"{first.high if side == 'CE' else first.low:g} with the {side} above its first 5-min high "
                           f"{self.first5_high.get(side, 0):g}; confirmation candle {when:%H:%M}",
                           "S3" if side == "PE" else "R3")

    def _trend_entry(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle]) -> Optional[str]:
        """Owner, 2026-10-08 - TREND trade for a direct bullish/bearish move (no pattern needed): on a PE day (CE day)
        the PE (CE) premium closes above its first 15-minute candle's close, then comes back to retest that close ->
        buy there (limit at the first 15-minute close). SL -50/-25, targets the next index levels to S3/R3 (HLC
        trailing SL and PANIC premium targets apply). After a trade it must close above again before the next one."""
        side = self.day_side(index, chain)
        if side is None or side not in self.went_above:
            return None
        atm = self.levels.atm
        prem = chain.get((atm, side))
        level = self.first15_close[side]
        now = len(self.premium_history.get((atm, side), [])) - 1
        if prem is None or self.went_above[side] >= now or prem.low > level:
            return None  # the close above must be on an EARLIER candle than the retest
        del self.went_above[side]
        fill = min(level, prem.open)
        return self._enter("TREND", side, atm, when, Candle(prem.open, prem.high, prem.low, fill), index,
                           f"{side} retest of its first 15-min close {level:g}", "S3" if side == "PE" else "R3")

    def _track_trend_patterns(self, chain: dict[tuple[float, str], Candle]) -> None:
        """Each candle: the morning ATM premium's latest bullish reversal pattern per side; a green candle retesting
        its low (within a quarter of the pattern's range, not closing below) = confirmation -> limit order at that
        candle's Fib 0.618."""
        atm = self.levels.atm
        for side in ("CE", "PE"):
            history = self.premium_history.get((atm, side), [])
            if not history or (atm, side) not in chain:
                continue
            c = history[-1]
            pattern = self.trend_pattern.get(side)
            if pattern and len(history) - 1 > pattern[0]:
                _, low, high, name = pattern
                if c.close < low:
                    del self.trend_pattern[side]
                    if self.trend_order and self.trend_order["side"] == side:
                        self.trend_order = None
                elif c.green and c.low <= low + 0.25 * (high - low) and self.trend_order is None:
                    limit = round(c.high - TREND_FIB * (c.high - c.low), 2)
                    self.trend_order = dict(side=side, strike=atm, limit=limit, pattern_low=low, at=len(history) - 1,
                                            why=f"{side} {name}, retest {c.low:g}, Fib {TREND_FIB:g} {limit:g}")
                    del self.trend_pattern[side]
                    continue
            found = bullish_pattern(history[-3:])
            if found and found[0] not in DIRECTIONLESS:
                span = history[-found[1]:]
                self.trend_pattern[side] = (len(history) - 1, min(x.low for x in span), max(x.high for x in span),
                                            found[0])

    def _pattern_trend_entry(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle]) -> Optional[str]:
        """Owner, 2026-10-08: on a PE day (CE day) the pending PE (CE) limit fills when the premium comes back to it.
        SL -50/-25, targets the next index levels to S3/R3. 08-10 SENSEX: 10:30 PE Bullish Engulfing, 10:50 retest,
        Fib 350.94, filled 11:00, S2 at 11:25."""
        order = self.trend_order
        if order is None:
            return None
        prem = chain.get((order["strike"], order["side"]))
        placed_now = len(self.premium_history.get((order["strike"], order["side"]), [])) - 1 <= order["at"]
        if prem is None or placed_now or self.day_side(index, chain) != order["side"] or prem.low > order["limit"]:
            return None
        self.trend_order = None
        fill = min(order["limit"], prem.open)
        return self._enter("TREND", order["side"], order["strike"], when, Candle(prem.open, prem.high, prem.low, fill),
                           index, order["why"], "S3" if order["side"] == "PE" else "R3")

    def _against_the_day(self, side: OptionType, index: Candle, premium: Candle) -> bool:
        """Owner, 2026-10-08: no CE reversal while the index is below yesterday's close AND the CE premium is below
        its own yesterday close - that's a PE day (08-10 SENSEX: CE 72500 87.45 vs close 262.90, index below 72638.7
        -> the 09:55 CE was wrong). Mirror for PE on an up day."""
        yesterday = self.yesterday.get(side)
        if yesterday is None:
            return False
        index_against = index.close < self.levels.close if side == "CE" else index.close > self.levels.close
        return index_against and premium.close < yesterday[2]

    def index_fib(self, side: OptionType, ratio: float = INDEX_FIB_TARGET) -> float:
        lv = self.levels
        if side == "CE":
            return round(lv.close + ratio * (lv.r2 - lv.close), 2)
        return round(lv.close - ratio * (lv.close - lv.s2), 2)

    def _momentum_ride(self, trade: HlcTrade) -> bool:
        if not (MOMENTUM_RIDE and self.market.profit_lock_step) or trade.uv is not None:
            return False
        if self.full_profit is not None:
            return True
        ladder = dict(self.levels.ladder())
        if self.day_open is None:
            return False
        return (trade.side == "CE" and self.day_open > ladder["R1"]) or (trade.side == "PE" and self.day_open < ladder["S1"])

    def close_now(self, when: datetime, chain: dict[tuple[float, str], Candle], reason: str) -> list[str]:
        """Close the open trade at this candle's premium close (R3/S3 full profit, or the owner's own call)."""
        trade = self.open_trade
        if trade is None:
            return []
        prem = chain.get((trade.strike, trade.side))
        price = prem.close if prem is not None else (self.premium_history.get((trade.strike, trade.side)) or [None])[-1]
        if price is None:
            return []
        price = price if isinstance(price, (int, float)) else price.close
        return [self._exit(trade, when, price, reason)]

    def _track_second_reversal(self) -> None:
        """Owner, 2026-10-13: after the morning trade, the next (last) entry needs a proper reversal on the same option:
        a reversal candle (not a Doji / Spinning Top), then the NEXT candle closing green without breaking its low."""
        if not (SECOND_ENTRY_PM_REVERSAL and self.trades and self.open_trade is None and len(self.trades) < 2):
            return
        first = self.trades[0]
        hist = self.premium_history.get((first.strike, first.side))
        if not hist:
            return
        n, c = len(self.index_history), hist[-1]
        st = self.second_rev
        if st is not None and not st.get("confirm"):
            if n == st["at"] + 1 and c.close > c.open and c.low >= st["low"]:
                st["confirm"] = n
                return
            self.second_rev = None
        if self.second_rev is not None and self.second_rev.get("confirm") != n:
            self.second_rev = None  # a confirmation that wasn't used (before 12:30) - look again
        if self.second_rev is not None:
            return
        found = bullish_pattern(hist[-3:])
        if found and found[0] not in DIRECTIONLESS:
            self.second_rev = dict(at=n, low=min(x.low for x in hist[-found[1]:]), name=found[0])

    def _second_reversal_entry(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle]) -> Optional[str]:
        st = self.second_rev
        if st is None or st.get("confirm") != len(self.index_history) or _closes_at(when) < time(12, 30):
            return None
        first = self.trades[0]
        prem = chain.get((first.strike, first.side))
        if prem is None:
            return None
        self.second_rev = None
        targets = self._targets(first.side, index.close, "S3" if first.side == "PE" else "R3")
        if not targets:
            return None
        price = round(prem.close, 2)
        trade = HlcTrade(date=self.day.isoformat(), kind="PM REVERSAL", side=first.side, strike=first.strike,
                         pattern=f"12:30+ entry: {st['name']} reversal, green confirmation closed {price:g}",
                         entry_time=when.isoformat(), entry_fill=price, entry_index=index.close,
                         sl_premium=round(st["low"] - 1, 2), sl_rule=f"reversal low {st['low']:g} - 1", targets=targets)
        if trade.sl_premium >= price or not self._size(trade):
            return None
        self.trades.append(trade)
        self.open_trade = trade
        names = " -> ".join(f"{n} {v:g}" for n, v in targets)
        return (f"BUY {trade.side} {trade.strike:g} at {price:.2f} (PM REVERSAL, {trade.pattern}; index {index.close:.2f}) - "
                f"SL {trade.sl_premium:.2f} ({trade.sl_rule}), targets {names}")

    def panic_side(self) -> Optional[OptionType]:
        return next((s for s in ("CE", "PE") if self.yesterday.get(s) and leg_label(*self.yesterday[s]) == "PANIC"), None)

    def _track_expiry_uv(self) -> None:
        """Owner, 2026-10-13: expiry day with one leg PROFIT BOOKING and the other PANIC yesterday. In the first half,
        once the profit booking has played out the PANIC side falls; at its new low it turns U / V. A reversal candle
        AT the day's low (the leg below its yesterday close) -> the NEXT candle must close green (and not below that
        low) = confirmation -> entry (in _expiry_uv_entry). No confirmation -> wait for the next reversal."""
        if not (self.expiry_day and self.buyers_day()) or self.expiry_uv_done:
            return
        side = self.panic_side()
        hist = self.premium_history.get((self.levels.atm, side)) if side else None
        if not hist:
            return
        n, c = len(self.index_history), hist[-1]
        st = self.expiry_uv
        if st is not None and not st.get("confirm"):
            if n == st["at"] + 1 and c.green and c.close > c.open and c.low >= st["low"]:
                st["confirm"] = n
                return
            self.expiry_uv = None  # not confirmed - look for a new reversal (this candle may be one)
        if self.expiry_uv is not None:
            return
        found = bullish_pattern(hist[-3:])
        if not found or found[0] in DIRECTIONLESS:  # a proper reversal candle, not a Doji / Spinning Top
            return
        span = hist[-found[1]:]
        low = min(x.low for x in span)
        if low <= min(x.low for x in hist) and low < self.yesterday[side][2]:
            self.expiry_uv = dict(side=side, at=n, low=low, high=max(x.high for x in span), name=found[0])

    def _expiry_uv_entry(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle]) -> Optional[str]:
        st = self.expiry_uv
        if st is None or st.get("confirm") != len(self.index_history) or _closes_at(when) > time(12, 0):
            return None  # first half only
        side, strike = st["side"], self.levels.atm
        prem = chain.get((strike, side))
        if prem is None:
            return None
        self.expiry_uv, self.expiry_uv_done = None, True
        price = round(prem.close, 2)
        k = math.isqrt(int(price))
        if k < 2:
            return None
        # Like the Sniper's sideways U/V trade: SL the square below the buy price, TSL to the first square once a
        # later candle closes above it, exit at the second square (the target).
        trade = HlcTrade(date=self.day.isoformat(), kind="EXPIRY U/V", side=side, strike=strike,
                         pattern=(f"expiry day, PB/PANIC: PANIC {side} new low {st['low']:g}, {st['name']} reversal, "
                                  f"green confirmation closed {price:g}"),
                         entry_time=when.isoformat(), entry_fill=price, entry_index=index.close,
                         sl_premium=float(k * k), sl_rule=f"square below the buy price ({k * k})")
        trade.uv = {"first": (k + 1) ** 2, "target": (k + 2) ** 2, "touched_at": None}
        if not self._size(trade):
            return None
        self.trades.append(trade)
        self.open_trade = trade
        return (f"BUY {side} {strike:g} at {price:.2f} (EXPIRY U/V, {trade.pattern}; index {index.close:.2f}) - "
                f"SL {k * k} (on a candle close), TSL {(k + 1) ** 2}, target {(k + 2) ** 2} (2 squares)")

    def _manage_uv(self, trade: HlcTrade, when: datetime, prem: Candle, closes: time) -> list[str]:
        uv = trade.uv
        trailed = trade.sl_premium >= uv["first"]
        if prem.close < trade.sl_premium:
            what = "the trailing SL" if trailed else "the SL"
            return [self._exit(trade, when, prem.close, f"{'TSL' if trailed else 'SL'} - candle {when:%H:%M} closed "
                                                        f"{prem.close:g}, below {what} {trade.sl_premium:g}")]
        if prem.high >= uv["target"]:
            return [self._exit(trade, when, uv["target"], f"2 square numbers reached (target {uv['target']}) -> exit")]
        if closes >= EXIT_CLOSE:
            return [self._exit(trade, when, prem.close, "15:00 exit")]
        n = len(self.index_history)
        if uv["touched_at"] is not None and n > uv["touched_at"] and prem.close > uv["first"] and not trailed:
            trade.sl_premium = float(uv["first"])
            trade.sl_rule = f"TSL - a later candle closed above the first square {uv['first']}"
            return [f"{trade.side} {trade.strike:g}: candle closed {prem.close:g} above {uv['first']} - TSL moves to {uv['first']}"]
        if uv["touched_at"] is None and prem.high >= uv["first"]:
            uv["touched_at"] = n
        return []

    def buyers_day(self) -> bool:
        """One leg PROFIT BOOKING yesterday, the other PANIC - or (owner, 16-10) BOTH PROFIT BOOKING: first one side
        books profit, then the other."""
        ce, pe = self.yesterday.get("CE"), self.yesterday.get("PE")
        if not (ce and pe):
            return False
        a, b = leg_label(*ce), leg_label(*pe)
        return a != b or (BOTH_PB_BUYERS_DAY and a == b == "PROFIT BOOKING")

    def _breakout_entry(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle], atm: float) -> Optional[str]:
        """Owner, 2026-10-01 (buyer's day): the last trade booked at a PANIC-side premium high; the premium
        then CLOSES above that high -> buy again, the next earlier high / next index level as targets."""
        if not self.buyers_day() or not self.trades:
            return None
        last = self.trades[-1]
        if last.strike != atm or not last.exit_reason.startswith("TARGET ") or last.pb_target is not None:
            return None  # (owner 12-10: a PROFIT BOOKING side trade's Fib/S2/R2 exit is final - no re-entry)
        prem = chain.get((last.strike, last.side))
        if prem is None:
            return None
        parts = last.exit_reason.split()
        final = "S3" if last.side == "PE" else "R3"
        if parts[1] == "premium":  # booked at a premium high -> the premium closes above it
            high = float(parts[3])
            if prem.close <= high:
                return None
            why = f"{last.side} closed above the high {high:g}"
        else:  # booked at an index level -> the index closes beyond it
            name, value = parts[1], float(parts[2])
            if name == final or (index.close >= value if last.side == "PE" else index.close <= value):
                return None
            why = f"index closed beyond {name} {value:g}"
        return self._enter("BREAKOUT", last.side, atm, when, prem, index, why, final)

    def _side_now(self) -> OptionType:
        return "CE" if self.index_history[-2].close > self.levels.close else "PE"

    def confirm_zone(self, side: OptionType) -> tuple[float, float]:
        first = self.index_history[0]
        rng = first.high - first.low
        if side == "PE":
            return first.low + CONFIRM_ZONE[0] * rng, first.low + CONFIRM_ZONE[1] * rng
        return first.high - CONFIRM_ZONE[1] * rng, first.high - CONFIRM_ZONE[0] * rng

    def _zone_touch(self, index: Candle) -> bool:
        """The index came into the zone from outside: PE - previous close above it, this low at/below its top;
        CE - previous close below it, this high at/above its bottom."""
        side = "CE" if self.index_history[-2].close > self.levels.close else "PE"
        low, high = self.confirm_zone(side)
        prev = self.index_history[-2].close
        return (prev > high and index.low <= high) if side == "PE" else (prev < low and index.high >= low)

    def _confirm_entry(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle], atm: float) -> Optional[str]:
        now = len(self.index_history) - 1
        if self.zone_touched_at is None or now - self.zone_touched_at > 1:
            return None
        side = self._side_now()
        history = self.premium_history.get((atm, side), [])
        found = bullish_pattern(history[-3:]) or (bullish_pattern(history[-4:-1]) if self.zone_touched_at == now else None)
        if not found:
            return None
        lo, hi = self.confirm_zone(side)
        event = self._enter("CONFIRM", side, atm, when, chain[(atm, side)], index,
                            f"index in Fib {CONFIRM_ZONE[0]:g}-{CONFIRM_ZONE[1]:g} zone {lo:.2f}-{hi:.2f}, {side} {found[0]}",
                            "S2" if side == "PE" else "R2")
        if event:
            self.zone_touched_at = None
        return event

    def fib_swing(self) -> OptionType:
        """Owner, 2026-10-01: the Fib follows the first candle's swing - "CE" = low first then high (up move),
        "PE" = high first. Without 1-minute data (first_swing unset), guess from the 5-minute candle: an open
        nearer the low means the low came first."""
        if self.first_swing:
            return self.first_swing
        first = self.index_history[0]
        return "CE" if first.open - first.low <= first.high - first.open else "PE"

    def fib_level(self) -> tuple[float, float, float]:
        """(entry level, first low, first high). Up swing: high - FIB_ENTRY x range; down swing: low + FIB_ENTRY x range."""
        first = self.index_history[0]
        rng = first.high - first.low
        level = first.high - FIB_ENTRY * rng if self.fib_swing() == "CE" else first.low + FIB_ENTRY * rng
        return level, first.low, first.high

    def _fib_entry(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle], atm: float) -> Optional[str]:
        if when.time() < FIB_FIRST_CANDLE:
            return None
        fib, first_low, first_high = self.fib_level()
        side: OptionType = "CE" if self.index_history[-2].close > self.levels.close else "PE"
        if side in self.blocked:
            return None
        reached = index.low <= fib if self.fib_swing() == "CE" else index.high >= fib
        if not reached:
            return None
        if side == "CE" and index.close > first_low:
            names, sl = ("R1", "R2"), first_low
        elif side == "PE" and index.close < first_high:
            names, sl = ("S1", "S2"), first_high
        else:
            return None
        targets = [(n, v) for n, v in self.levels.ladder() if n in names and (v > index.close if side == "CE" else v < index.close)]
        if side == "PE":
            targets.reverse()
        if not targets:
            return None
        prem = chain[(atm, side)]
        self.gap_done = True
        trade = HlcTrade(date=self.day.isoformat(), kind="FIB", side=side, strike=atm,
                         pattern=f"first candle {FIB_ENTRY:g} at {fib:.2f}", entry_time=when.isoformat(),
                         entry_fill=round(prem.close, 2), entry_index=index.close, sl_premium=0.0,
                         sl_rule=f"index {'below first low' if side == 'CE' else 'above first high'} {sl:g}",
                         index_sl=sl, targets=targets, big_gap=self.big_gap)
        trade.premium_targets = self.premium_ladder(trade.side, trade.strike, trade.entry_fill)
        self._profit_booking_exits(trade)
        if not self._size(trade):
            return None  # owner 12-10: not even one lot fits the allotment / loss limit
        self.trades.append(trade)
        self.open_trade = trade
        return (f"BUY {side} {atm:g} at {prem.close:.2f} (FIB {FIB_ENTRY:g} of the first candle at {fib:.2f}; index {index.close:.2f}) - "
                f"SL index {sl:g}, targets " + " -> ".join(f"{n} {v:g}" for n, v in targets))

    def _open_filled(self, order: dict, when: datetime, fill: Candle, index: Candle) -> Optional[str]:
        """A low-premium buy stop filled at fill.close; managed from the next candle."""
        targets = self._targets(order["side"], index.close, order["final"])
        if not targets:
            return None
        trade = HlcTrade(date=self.day.isoformat(), kind=order["kind"], side=order["side"], strike=order["strike"],
                         pattern=order["pattern"], entry_time=when.isoformat(), entry_fill=round(fill.close, 2),
                         entry_index=index.close, sl_premium=order["sl"], sl_rule="2-candle low", targets=targets,
                         big_gap=self.big_gap)
        trade.premium_targets = self.premium_ladder(trade.side, trade.strike, trade.entry_fill)
        self._profit_booking_exits(trade)
        if not self._size(trade):
            return None  # owner 12-10: not even one lot fits the allotment / loss limit
        self.trades.append(trade)
        self.open_trade = trade
        names = " -> ".join(f"{n} {v:g}" for n, v in targets)
        return f"BUY {trade.side} {trade.strike:g} at {trade.entry_fill:.2f} (broke the confirmation high) - SL {trade.sl_premium:.2f}, targets {names}"

    def _with_premium_targets(self, event: str) -> str:
        trade = self.open_trade
        if trade is None or not trade.premium_targets or not event.startswith("BUY"):
            return event
        return event + " | PANIC side, premium targets " + " -> ".join(f"{h:g}" for h in trade.premium_targets)

    def sync_capital(self) -> None:
        """Live bot, after each candle: tell the shared ledger how much money this bot has in its open trade."""
        if self.capital:
            t = self.open_trade
            self.capital.hold(t.qty * t.entry_fill if t is not None and not t.exit_reason and t.qty else 0.0)

    @staticmethod
    def _window_of(trade: HlcTrade) -> str:
        closes = _closes_at(datetime.fromisoformat(trade.entry_time))
        return "am" if closes <= time(12, 0) else "pm"

    def realized_rupees(self) -> float:
        return sum(t.pnl_points * t.qty for t in self.trades if t.exit_reason and t.qty)

    def _size(self, trade: HlcTrade) -> bool:
        """Owner, 2026-10-12: as many lots as the allotment buys, cut so a stop-out stays within today's loss limit."""
        m = self.market
        if not (m.allocation and m.lot):
            return True
        stop = trade.sl_premium
        if stop <= 0:  # index-SL trades (FIB): the premium exit isn't known - size on twice the points SL
            stop = trade.entry_fill - 2 * m.sl_points
        money = self.capital.available(m.allocation) if self.capital else m.allocation
        trade.qty = size_qty(money, risk_left(m.max_loss, self.realized_rupees()), m.lot, trade.entry_fill, stop)
        return trade.qty > 0

    def _profit_booking_exits(self, trade: HlcTrade) -> None:
        """Owner, 2026-10-12: a trade on the PROFIT BOOKING side (morning ATM) exits only at the Fib 0.786 of that
        strike's yesterday close -> high (12-10 NIFTY 22550 PE: 95.95 -> 272.77 => 234.93; the owner's 101.50 entry was
        booked there), or when the index reaches S2 (PE) / R2 (CE) - plus the SL."""
        hlc = self.yesterday.get(trade.side)
        if not hlc or trade.strike != self.levels.atm or leg_label(*hlc) != "PROFIT BOOKING":
            return
        high, _, close = hlc
        if high <= close:
            return
        target = round(close + PB_FIB * (high - close), 2)
        name = "S2" if trade.side == "PE" else "R2"
        level = dict(self.levels.ladder())[name]
        # 15-10 SENSEX: CE bought 610 with the Fib target 589.61 below it -> "TARGET" exit at +0. A target already
        # behind the entry is no target - keep only what is still ahead (else the trade's normal targets apply).
        if target > trade.entry_fill:
            trade.pb_target = target
        index_ahead = trade.entry_index > level if trade.side == "PE" else trade.entry_index < level
        if index_ahead:
            trade.pb_index = (name, level)

    def premium_ladder(self, side: OptionType, strike: float, above: float) -> list[float]:
        """PANIC side, morning ATM only: the staircase of daily highs going back from yesterday, above `above`."""
        hlc = self.yesterday.get(side)
        if strike != self.levels.atm or not hlc or leg_label(*hlc) != "PANIC":
            return []
        ladder, top = [], 0.0
        for high in self.daily_highs.get(side) or [hlc[0]]:
            if high > top:
                top = high
                if high > above:
                    ladder.append(high)
        return ladder

    def _manage(self, trade: HlcTrade, when: datetime, index: Candle, prem: Candle, closes: time) -> list[str]:
        if trade.qty and self.market.max_loss:
            # Owner, 2026-10-12: losses under control - out when this trade's loss reaches what's left of today's limit
            left = risk_left(self.market.max_loss, self.realized_rupees())
            if (trade.entry_fill - prem.close) * trade.qty >= left:
                return [self._exit(trade, when, prem.close, f"daily loss limit (Rs {self.market.max_loss:,.0f}) - candle {when:%H:%M} closed {prem.close:g}")]
        if trade.uv is not None:
            return self._manage_uv(trade, when, prem, closes)
        if FLIP_ON_CONFIRMATION and self.flip is None and prem.close < trade.entry_fill:
            against = (bullish_pattern if trade.side == "PE" else bearish_pattern)(self.index_history[-3:])
            top = bearish_pattern(self.premium_history.get((trade.strike, trade.side), [])[-3:])
            strong = ("Morning Star", "Evening Star", "Bullish Engulfing", "Bearish Engulfing")  # not Harami / single candles
            if against and top and against[0] in strong and top[0] in strong:
                other = "CE" if trade.side == "PE" else "PE"
                why = f"index {against[0]} + {trade.side} {top[0]} at {when:%H:%M}"
                self.flip = {"side": other, "at": len(self.index_history), "why": why}
                return [self._exit(trade, when, prem.close, f"opposite confirmation ({why}) - exit, watch {other}")]
        if trade.index_sl is not None:
            if (trade.side == "CE" and index.low <= trade.index_sl) or (trade.side == "PE" and index.high >= trade.index_sl):
                return [self._exit(trade, when, prem.close, f"SL ({trade.sl_rule}) - index reached the SL {trade.index_sl:g} in candle {when:%H:%M}")]
        elif prem.low <= trade.sl_premium:
            return [self._exit(trade, when, trade.sl_premium, f"SL ({trade.sl_rule}) - premium low {prem.low:g} touched the SL {trade.sl_premium:g} in candle {when:%H:%M}")]
        pe = trade.side == "PE"
        if INDEX_FIB_TARGET and not R2_OR_FIB_REVERSAL and self.full_profit is None:
            for ratio in (r for r in INDEX_FIB_LEVELS if r > trade.fib_from):
                level = self.index_fib(trade.side, ratio)
                if (trade.entry_index >= level) if not pe else (trade.entry_index <= level):
                    continue  # already beyond this one at entry
                if (index.high >= level) if not pe else (index.low <= level):
                    if ratio not in self.fib_used:
                        self.fib_reentry = {"side": trade.side, "ratio": ratio, "level": level, "at": len(self.index_history)}
                    return [self._exit(trade, when, prem.close,
                                       f"TARGET index Fib {ratio:g} (close -> {'S2' if pe else 'R2'}) {level:g} - "
                                       f"{'golden ratio' if ratio == 0.618 else 'institutions profit area'}, "
                                       f"touched in candle {when:%H:%M}")]
                break  # only the first level ahead is the target
        step = self.market.profit_lock_step
        if step:
            # Owner, 2026-10-13 (SENSEX): ride to the target; once the premium is +100 and a LATER candle closes there
            # too, the SL locks that profit (entry + 100); then the same for every further +50 (150, 200, ...).
            # Exit on a touch of the locked level.
            if trade.lock_level and prem.low <= trade.lock_level:
                return [self._exit(trade, when, trade.lock_level,
                                   f"profit lock {trade.lock_level - trade.entry_fill:+g} - {trade.lock_why}; candle {when:%H:%M} came back to it")]
            now = len(self.index_history)
            add = self.market.profit_lock_add or step
            if trade.lock_seen and now > trade.lock_seen[1]:
                level = trade.entry_fill + trade.lock_seen[0]
                if prem.close >= level and level > trade.lock_level:
                    trade.lock_level = level
                    trade.lock_why = f"a later candle had closed above {level:g}, so the SL was locked there"
                    trade.lock_seen = None
            gain = prem.high - trade.entry_fill  # profit reached: +100, then +150, +200, ... (owner 13-10)
            reached = 0.0 if gain < step else step + ((gain - step) // add) * add
            if reached and trade.entry_fill + reached > trade.lock_level and (
                    not trade.lock_seen or reached > trade.lock_seen[0]):
                trade.lock_seen = (reached, now)
            if reached >= 2 * step:
                # Owner, 2026-10-16 (NIFTY CE 136.65 touched +100 at 10:15, closed back and gave only +50): from +100
                # (SENSEX +200) a TOUCH moves the SL to one step below it (+75 / +150), no confirming close needed
                touch_lock = round(trade.entry_fill + reached - add, 2)
                if touch_lock > trade.lock_level:
                    trade.lock_level = touch_lock
                    trade.lock_why = f"+{reached:g} touched ({trade.entry_fill + reached:g}), so the SL moved to +{reached - add:g}"
        if self._momentum_ride(trade):
            # owner 15-10: momentum - no level / Fib targets; the profit lock above (and the SL) take it out
            if closes >= EXIT_CLOSE:
                return [self._exit(trade, when, prem.close, "15:00 exit")]
            return []
        if R2_OR_FIB_REVERSAL and not trade.big_gap:
            name, value = ("S2", self.levels.s2) if pe else ("R2", self.levels.r2)
            trade.index_best = (min if pe else max)(trade.index_best if trade.index_best is not None else trade.entry_index,
                                                    index.low if pe else index.high)
            if (trade.entry_index > value) if pe else (trade.entry_index < value):  # R2 / S2 still ahead at entry
                if (index.low <= value) if pe else (index.high >= value):
                    return [self._exit(trade, when, prem.close, f"TARGET {name} {value:g} reached in candle {when:%H:%M}")]
                f75, f786 = self.index_fib(trade.side, 0.75), self.index_fib(trade.side, 0.786)
                crossed = trade.index_best <= f75 if pe else trade.index_best >= f75
                # 19-10: a trade entered already beyond the 0.75 (12:40 PM reversals) aims straight at S2 / R2 - the Fib
                # booking only applies to a move that crosses the 0.75 after the entry
                entered_before = trade.entry_index > f75 if pe else trade.entry_index < f75
                turn = (bullish_pattern if pe else bearish_pattern)(self.index_history[-3:])
                if entered_before and crossed and turn and turn[0] not in DIRECTIONLESS:
                    hit786 = trade.index_best <= f786 if pe else trade.index_best >= f786
                    ratio, level = (0.786, f786) if hit786 else (0.75, f75)
                    return [self._exit(trade, when, prem.close,
                                       f"TARGET booked at the Fib {ratio:g} {level:g} (close -> {name}): {name} not reached, "
                                       f"index {turn[0]} in candle {when:%H:%M}")]
            if closes >= EXIT_CLOSE:
                return [self._exit(trade, when, prem.close, "15:00 exit")]
            return []
        if trade.pb_target is not None or trade.pb_index is not None:
            # Owner, 2026-10-12: PROFIT BOOKING side - exit only at the Fib 0.786 target or the index at S2 / R2
            if trade.pb_target is not None and prem.high >= trade.pb_target:
                return [self._exit(trade, when, max(trade.pb_target, prem.open) if prem.open > trade.pb_target else trade.pb_target,
                                   f"TARGET Fib {PB_FIB:g} of yesterday's close-high {trade.pb_target:g}")]
            if trade.pb_index is not None:
                name, value = trade.pb_index
                if (pe and index.low <= value) or (not pe and index.high >= value):
                    return [self._exit(trade, when, prem.close, f"TARGET {name} {value:g}")]
            if closes >= EXIT_CLOSE:
                return [self._exit(trade, when, prem.close, "15:00 exit")]
            return []
        # Owner, 2026-10-05 (big-gap days), 2026-10-07 (every HLC trade): once the premium is big_gap_trail points
        # up (SENSEX 100 / NIFTY 50), trail the SL that far below its high - first at cost, then following the high.
        trail = self.market.big_gap_trail
        if not step and trade.premium_high >= trade.entry_fill + trail and prem.low <= trade.premium_high - trail:
            return [self._exit(trade, when, trade.premium_high - trail,
                               f"trailing SL {trade.premium_high - trail:.2f} ({trail:g} below the high {trade.premium_high:g})")]
        trade.premium_high = max(trade.premium_high, prem.high)
        if trade.big_gap:
            # Owner, 2026-10-05: on a big-gap day ride the move - exit on the next reversal candle. No level targets.
            turned = bullish_pattern(self.index_history[-3:]) if pe else bearish_pattern(self.index_history[-3:])
            if turned and turned[0] not in DIRECTIONLESS:
                return [self._exit(trade, when, prem.close, f"pattern turned: index {turned[0]}")]
            if closes >= EXIT_CLOSE:
                return [self._exit(trade, when, prem.close, "15:00 exit")]
            return []
        if trade.trail_level is not None:
            name, value = trade.trail_level
            if (pe and index.close > value) or (not pe and index.close < value):
                return [self._exit(trade, when, prem.close, f"closed back across {name} {value:g}")]
        events = []
        ride = self.buyers_day()  # owner, 2026-10-12: buyer's day - no target exits, ride with the trailing SL; other days book
        while trade.premium_targets and prem.high >= trade.premium_targets[0]:
            high = trade.premium_targets[0]
            if prem.close <= high and ride:
                break  # touched, didn't close above: keep riding, look at it again next candle
            if prem.close <= high:
                return events + [self._exit(trade, when, prem.close, f"TARGET premium high {high:g}")]
            trade.premium_trail = trade.premium_targets.pop(0)
            nxt = f"next premium target {trade.premium_targets[0]:g}" if trade.premium_targets else "no earlier high left"
            events.append(f"premium closed above the earlier high {high:g} ({prem.close:.2f}) - {nxt}")
        while trade.targets:
            name, value = trade.targets[0]
            touched = index.low <= value if pe else index.high >= value
            if not touched:
                break
            broke = index.close < value if pe else index.close > value
            if ride:
                if not broke:
                    break  # touched, not broken: no exit on a normal day
                trade.trail_level = trade.targets.pop(0)
                events.append(f"{name} {value:g} broken (index {index.close:.2f}) - SL moves to {name}"
                              + (f", next level {trade.targets[0][0]} {trade.targets[0][1]:g}" if trade.targets else ""))
                continue
            if len(trade.targets) == 1 or not broke:
                return events + [self._exit(trade, when, prem.close, f"TARGET {name} {value:g}")]
            trade.trail_level = trade.targets.pop(0)  # broke through: SL to this level, next level is the target
            events.append(f"{name} {value:g} broken (index {index.close:.2f}) - SL moves to {name}, "
                          f"next target {trade.targets[0][0]} {trade.targets[0][1]:g}")
        if closes >= EXIT_CLOSE:
            return events + [self._exit(trade, when, prem.close, "15:00 exit")]
        return events
