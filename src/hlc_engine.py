"""
HLC strategy, candle by candle (rules in PROJECT_STATUS.md, "HLC strategy").

Per 5-minute candle the engine gets the index candle and the option candles of
the strikes around the index. Trades (max 2 a day, one at a time, entries on
candles closing 09:30-14:55):

  FIB trade   - (owner, 2026-09-30; replaced the 09:30 gap trade) the first
                5-minute index candle's range, reverse Fibonacci FIB_ENTRY
                (0.75 - changed from 0.618 the same day for a smaller SL). Side =
                where the last closed candle sits against yesterday's close
                (above -> CE, below -> PE; can change until the entry, e.g. a
                gap-down open whose 2nd/3rd candles close above -> CE). From
                09:30: CE when the index dips to high - 0.75 x range, PE when
                it rises to low + 0.75 x range. SL on the INDEX: CE = first
                candle low, PE = first candle high. Targets R1 then R2 (CE) /
                S1 then S2 (PE) - never beyond R2/S2. One FIB trade a day.
  REVERSAL    - index shows a support pattern at S1/S2/S3 AND the ATM CE premium
                shows an up-reversal pattern -> buy ATM CE. Index shows a
                resistance pattern at R1/R2/R3 AND the ATM PE premium shows an
                up-reversal pattern -> buy ATM PE.

  Strike = the morning ATM (owner, 2026-09-29: even if the balanced strike
  has moved by 09:30). Except on a BIG GAP day (|open - yesterday's close| >=
  150 NIFTY / 300 SENSEX): every trade uses the strike nearest the index at
  entry, the levels stay the same, and the trade also exits when the index
  pattern turns against it (a directional reversal pattern - Doji/Spinning
  Top don't count). Fill = the option's candle close.
  SL = entry premium - 25 points (NIFTY) / 50 (SENSEX) (owner, 2026-09-29).
  If the premium is too low for that (entry - points <= 0) (owner, 2026-09-29):
    * from 13:30 (about 4 hours of trading, so the day low means something):
      buy at the close, SL = the option's day low so far - 1 point;
    * before 13:30 (e.g. expiry-day morning): buy only if the NEXT candle
      trades above the confirmation candle's high (filled at that high, or
      the open if it gaps above), SL = below the lowest low of the last 2
      candles (confirmation candle and the one before). Not triggered on the
      next candle -> cancelled.
  Targets = levels only. PE: the levels below the index, one by one; CE: the
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
FIB_ENTRY = 0.75  # owner, 2026-09-30: 0.75 of the first candle (was 0.618) - entry nearer its low/high, smaller SL
LAST_ENTRY_CLOSE = time(14, 55)
EXIT_CLOSE = time(15, 0)
MAX_TRADES = 2
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
            if final == "Close":
                below = below[: next((i + 1 for i, lv in enumerate(below) if lv[0] == "Close"), len(below))]
            return below
        above = [lv for lv in ladder if lv[1] > index_price]
        if final == "Close":
            above = above[: next((i + 1 for i, lv in enumerate(above) if lv[0] == "Close"), len(above))]
        return above

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
               pattern: str, final: str) -> Optional[str]:
        targets = self._targets(side, index.close, final)
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
            self.big_gap = abs(index.open - self.levels.close) >= self.market.big_gap
        self.index_history.append(index)
        for key, candle in chain.items():
            self.premium_history.setdefault(key, []).append(candle)

        for side, other in (("PE", "CE"), ("CE", "PE")):
            hlc = self.yesterday.get(side)
            candle = chain.get((self.levels.atm, side))
            if hlc and candle and other not in self.blocked and leg_label(*hlc) == "PANIC" and candle.high > hlc[0]:
                self.blocked[other] = f"{side} PANIC yesterday and above its high {hlc[0]:g} today"
                events.append(f"No {other} trades today - {self.blocked[other]}")

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
        if (self.open_trade is not None or self.pending is not None or len(self.trades) >= MAX_TRADES
                or (self.trades and not self.trades[-1].exit_reason.startswith("SL"))):
            # owner, 2026-09-30: after the first trade, trade again only if it was stopped out
            return events
        if not (FIRST_ENTRY_CLOSE <= closes <= LAST_ENTRY_CLOSE):
            return events

        atm = self.levels.atm
        if self.big_gap:  # big gap: the round strike nearest the market now
            atm = float(round(index.close / self.market.strike_step) * self.market.strike_step)
        if (atm, "CE") not in chain or (atm, "PE") not in chain:
            return events

        if not self.gap_done and len(self.index_history) >= 2:
            event = self._fib_entry(when, index, chain, atm)
            if event:
                return events + [event]

        up = bullish_pattern(self.index_history[-3:])
        if up:
            span_low = min(c.low for c in self.index_history[-up[1]:])
            level = self._level_near(span_low, ("S1", "S2", "S3"))
            ce_history = self.premium_history.get((atm, "CE"), [])
            prem_pattern = bullish_pattern(ce_history[-3:])
            if level and prem_pattern:
                event = self._enter("REVERSAL", "CE", atm, when, chain[(atm, "CE")], index,
                                    f"index {up[0]} at {level}, CE {prem_pattern[0]}", "Close")
                if event:
                    return events + [event]

        down = bearish_pattern(self.index_history[-3:])
        if down:
            span_high = max(c.high for c in self.index_history[-down[1]:])
            level = self._level_near(span_high, ("R1", "R2", "R3"))
            pe_history = self.premium_history.get((atm, "PE"), [])
            prem_pattern = bullish_pattern(pe_history[-3:])
            if level and prem_pattern:
                event = self._enter("REVERSAL", "PE", atm, when, chain[(atm, "PE")], index,
                                    f"index {down[0]} at {level}, PE {prem_pattern[0]}", "Close")
                if event:
                    return events + [event]
        return events

    def fib_levels(self) -> Optional[tuple[float, float, float, float]]:
        """(CE entry, PE entry, first low, first high) from the first 5-minute candle."""
        if not self.index_history:
            return None
        first = self.index_history[0]
        rng = first.high - first.low
        return first.high - FIB_ENTRY * rng, first.low + FIB_ENTRY * rng, first.low, first.high

    def _fib_entry(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle], atm: float) -> Optional[str]:
        ce_entry, pe_entry, first_low, first_high = self.fib_levels()
        side: OptionType = "CE" if self.index_history[-2].close > self.levels.close else "PE"
        if side in self.blocked:
            return None
        if side == "CE" and index.low <= ce_entry and index.close > first_low:
            names = ("R1", "R2")
            fib, sl = ce_entry, first_low
        elif side == "PE" and index.high >= pe_entry and index.close < first_high:
            names = ("S1", "S2")
            fib, sl = pe_entry, first_high
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
        self.trades.append(trade)
        self.open_trade = trade
        names = " -> ".join(f"{n} {v:g}" for n, v in targets)
        return f"BUY {trade.side} {trade.strike:g} at {trade.entry_fill:.2f} (broke the confirmation high) - SL {trade.sl_premium:.2f}, targets {names}"

    def _manage(self, trade: HlcTrade, when: datetime, index: Candle, prem: Candle, closes: time) -> list[str]:
        if trade.index_sl is not None:
            if (trade.side == "CE" and index.low <= trade.index_sl) or (trade.side == "PE" and index.high >= trade.index_sl):
                return [self._exit(trade, when, prem.close, f"SL ({trade.sl_rule})")]
        elif prem.low <= trade.sl_premium:
            return [self._exit(trade, when, trade.sl_premium, f"SL ({trade.sl_rule})")]
        pe = trade.side == "PE"
        if trade.big_gap:
            turned = bullish_pattern(self.index_history[-3:]) if pe else bearish_pattern(self.index_history[-3:])
            if turned and turned[0] not in DIRECTIONLESS:
                return [self._exit(trade, when, prem.close, f"pattern turned: index {turned[0]}")]
        if trade.trail_level is not None:
            name, value = trade.trail_level
            if (pe and index.close > value) or (not pe and index.close < value):
                return [self._exit(trade, when, prem.close, f"closed back across {name} {value:g}")]
        events = []
        while trade.targets:
            name, value = trade.targets[0]
            touched = index.low <= value if pe else index.high >= value
            if not touched:
                break
            broke = index.close < value if pe else index.close > value
            if len(trade.targets) == 1 or not broke:
                return events + [self._exit(trade, when, prem.close, f"TARGET {name} {value:g}")]
            trade.trail_level = trade.targets.pop(0)  # broke through: SL to this level, next level is the target
            events.append(f"{name} {value:g} broken (index {index.close:.2f}) - SL moves to {name}, "
                          f"next target {trade.targets[0][0]} {trade.targets[0][1]:g}")
        if closes >= EXIT_CLOSE:
            return events + [self._exit(trade, when, prem.close, "15:00 exit")]
        return events
