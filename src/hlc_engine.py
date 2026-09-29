"""
HLC strategy, candle by candle (rules in PROJECT_STATUS.md, "HLC strategy").

Per 5-minute candle the engine gets the index candle and the option candles of
the strikes around the index. Trades (max 2 a day, one at a time, entries on
candles closing 09:30-14:55):

  GAP trade   - on the candle closing 09:30: day opened below yesterday's close
                -> buy ATM PE; above -> ATM CE. No pattern needed (owner's
                29-09 example; to be confirmed).
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
  If the premium is too low for that (entry - points <= 0): SL = that
  option's day low so far - 1 point (owner, 2026-09-29; replaced "the
  pattern's low", which sat 0.35 under a 10.00 entry).
  Targets = levels only. PE: the levels below the index, one by one; CE: the
  levels above. Final target: the last level (S3/R3) for a gap trade, the
  yesterday's Close for a reversal trade. When the index touches a target:
  if it's the final one, or the candle closes back on our side of it -> exit;
  if the candle closes beyond it -> the index SL moves to that level and the
  next level becomes the target. Exit also when a candle closes back across
  the trailed level, or at 15:00.

  Exits are at the option's candle close (at the SL level for a premium SL).
  A premium SL is checked before the targets (conservative).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

from hlc_signal import DIRECTIONLESS, Candle, HlcLevels, HlcMarket, OptionType, bearish_pattern, bullish_pattern

FIRST_ENTRY_CLOSE = time(9, 30)
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
    exit_time: str = ""
    exit_premium: float = 0.0
    exit_reason: str = ""
    pnl_points: float = 0.0


def _closes_at(when: datetime) -> time:
    return (when + CANDLE).time()


class HlcDay:
    def __init__(self, day: date, levels: HlcLevels, market: HlcMarket):
        self.day = day
        self.levels = levels
        self.market = market
        self.trades: list[HlcTrade] = []
        self.open_trade: Optional[HlcTrade] = None
        self.day_open: Optional[float] = None
        self.gap_done = False
        self.big_gap = False
        self.index_history: list[Candle] = []
        self.premium_history: dict[tuple[float, str], list[Candle]] = {}
        self.done = False

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
        if not targets:
            return None
        sl, sl_rule = prem.close - self.market.sl_points, f"{self.market.sl_points:g} points"
        if sl <= 0:  # premium too low for a points SL: 1 point under the option's day low
            day_low = min(c.low for c in self.premium_history.get((strike, side), [prem]))
            sl, sl_rule = max(day_low - 1, 0.05), "day low - 1"
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

        trade = self.open_trade
        if trade is not None:
            prem = chain.get((trade.strike, trade.side))
            if prem is not None:
                events += self._manage(trade, when, index, prem, closes)

        if closes >= EXIT_CLOSE:
            self.done = True
            return events
        if self.open_trade is not None or len(self.trades) >= MAX_TRADES:
            return events
        if not (FIRST_ENTRY_CLOSE <= closes <= LAST_ENTRY_CLOSE):
            return events

        atm = self.levels.atm
        if self.big_gap:  # big gap: the round strike nearest the market now
            atm = float(round(index.close / self.market.strike_step) * self.market.strike_step)
        if (atm, "CE") not in chain or (atm, "PE") not in chain:
            return events

        if not self.gap_done and closes == FIRST_ENTRY_CLOSE:
            self.gap_done = True
            if self.day_open != self.levels.close:
                side: OptionType = "PE" if self.day_open < self.levels.close else "CE"
                final = self.levels.ladder()[0][0] if side == "PE" else self.levels.ladder()[-1][0]
                size = "BIG gap" if self.big_gap else "gap"
                event = self._enter("GAP", side, atm, when, chain[(atm, side)], index,
                                    f"{size} {'down' if side == 'PE' else 'up'} open {self.day_open:.2f}", final)
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

    def _manage(self, trade: HlcTrade, when: datetime, index: Candle, prem: Candle, closes: time) -> list[str]:
        if prem.low <= trade.sl_premium:
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
