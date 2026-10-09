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

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

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
            if hlc and candle and other not in self.blocked and leg_label(*hlc) == "PANIC" and candle.high > hlc[0]:
                self.blocked[other] = f"{side} PANIC yesterday and above its high {hlc[0]:g} today"
                events.append(f"No {other} trades today - {self.blocked[other]}")

        self._track_trend(when)
        self._track_trend_patterns(chain)

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

        trade = self.open_trade
        if trade is not None and trade.entry_time != when.isoformat():
            prem = chain.get((trade.strike, trade.side))
            if prem is not None:
                events += self._manage(trade, when, index, prem, closes)

        if closes >= EXIT_CLOSE:
            self.done = True
            return events
        if self.open_trade is not None or self.pending is not None:
            return events
        if len(self.trades) >= (MAX_TRADES if self.buyers_day() else NORMAL_DAY_MAX_TRADES):
            # Owner, 2026-10-09: buyer's day 4 (was unlimited); other days 2, riding with the trailing SL.
            return events
        if not (FIRST_ENTRY_CLOSE <= closes <= LAST_ENTRY_CLOSE):
            return events

        atm = self.levels.atm
        if self.big_gap:  # big gap: the round strike nearest the market now
            atm = float(round(index.close / self.market.strike_step) * self.market.strike_step)
        if (atm, "CE") not in chain or (atm, "PE") not in chain:
            return events

        event = (self._break_entry(when, index, chain) or self._pattern_trend_entry(when, index, chain)
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

    def _break_entry(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle]) -> Optional[str]:
        """Owner, 2026-10-09: on a CE day (PE day) the CE (PE) premium CLOSES strongly above its first 5-minute candle's
        high -> buy at that close. The day's first entry, once. 09-10 SENSEX: 71600 CE first candle high 859, the
        09:25 candle closed 882.45 -> 882 (owner's trade). SL -50/-25, targets the next index levels, trailing."""
        if self.break_done or self.trades:
            return None
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

    def buyers_day(self) -> bool:
        """One leg PROFIT BOOKING yesterday, the other PANIC."""
        ce, pe = self.yesterday.get("CE"), self.yesterday.get("PE")
        return bool(ce and pe) and leg_label(*ce) != leg_label(*pe)

    def _breakout_entry(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle], atm: float) -> Optional[str]:
        """Owner, 2026-10-01 (buyer's day): the last trade booked at a PANIC-side premium high; the premium
        then CLOSES above that high -> buy again, the next earlier high / next index level as targets."""
        if not self.buyers_day() or not self.trades:
            return None
        last = self.trades[-1]
        if last.strike != atm or not last.exit_reason.startswith("TARGET "):
            return None
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
        self.trades.append(trade)
        self.open_trade = trade
        names = " -> ".join(f"{n} {v:g}" for n, v in targets)
        return f"BUY {trade.side} {trade.strike:g} at {trade.entry_fill:.2f} (broke the confirmation high) - SL {trade.sl_premium:.2f}, targets {names}"

    def _with_premium_targets(self, event: str) -> str:
        trade = self.open_trade
        if trade is None or not trade.premium_targets or not event.startswith("BUY"):
            return event
        return event + " | PANIC side, premium targets " + " -> ".join(f"{h:g}" for h in trade.premium_targets)

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
        if trade.index_sl is not None:
            if (trade.side == "CE" and index.low <= trade.index_sl) or (trade.side == "PE" and index.high >= trade.index_sl):
                return [self._exit(trade, when, prem.close, f"SL ({trade.sl_rule})")]
        elif prem.low <= trade.sl_premium:
            return [self._exit(trade, when, trade.sl_premium, f"SL ({trade.sl_rule})")]
        pe = trade.side == "PE"
        # Owner, 2026-10-05 (big-gap days), 2026-10-07 (every HLC trade): once the premium is big_gap_trail points
        # up (SENSEX 100 / NIFTY 50), trail the SL that far below its high - first at cost, then following the high.
        trail = self.market.big_gap_trail
        if trade.premium_high >= trade.entry_fill + trail and prem.low <= trade.premium_high - trail:
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
        ride = not self.buyers_day()  # owner, 2026-10-09: normal days - no target exits, ride with the trailing SL
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
