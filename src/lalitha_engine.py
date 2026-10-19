"""
Lalitha - strategy #4 (owner, 2026-10-19). PAPER MODE. Indicator based, on the INDEX's 5-minute candles (owner 19-10 afternoon; was 3).

  CE BUY when a 5-minute candle closes with ALL of:
      Supertrend(10, 2) up, RSI(14) > 70, close above yesterday's Traditional pivot R1, close above the
      Bollinger(20, 3) upper band.
  PE BUY: the mirror - Supertrend down, RSI < 30, close below S1, close below the lower band.
  Strike: the option of that side whose premium is nearest Rs 250 (ITM is fine).
  Exit: the candle on which the Supertrend changes direction - at its close. Everything closed by 15:15.
  Markets NIFTY (4 lots), SENSEX (10 lots), BANK NIFTY (6 lots); at most 10 trades a day; 09:15 - 15:15.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable, Optional

from lalitha_indicators import Bar, bollinger, pivots, rsi, supertrend

CANDLE = timedelta(minutes=5)  # owner 19-10 afternoon: 5 minutes (was 3)
FIRST_ENTRY_CLOSE = time(9, 20)
LAST_ENTRY_CLOSE = time(15, 10)
BB_PERIOD, BB_MULT = 20, 3.0  # owner 19-10 afternoon: Bollinger 20, 3 (was 20, 2)
SQUARE_OFF = time(15, 15)
MAX_TRADES = 10
TARGET_PREMIUM = 250.0
RSI_UP, RSI_DOWN = 70.0, 30.0


@dataclass
class LalithaTrade:
    date: str
    side: str
    strike: float
    qty: int
    entry_time: str
    entry_fill: float
    entry_index: float
    entry_reason: str = ""
    exit_time: str = ""
    exit_premium: float = 0.0
    exit_index: float = 0.0
    exit_reason: str = ""
    pnl_points: float = 0.0

    @property
    def pnl_rupees(self) -> float:
        return round(self.pnl_points * self.qty, 2)


# premium(strike, side) for the candle being processed; strikes(side) lists the strikes to consider
PremiumAt = Callable[[float, str], Optional[float]]


class LalithaDay:
    def __init__(self, day: date, qty: int, yesterday: tuple[float, float, float], warmup: list[Bar]):
        """`warmup`: earlier 3-minute index candles (previous days) so the indicators match a continuous chart."""
        self.day, self.qty = day, qty
        self.pivot = pivots(*yesterday)
        self.bars: list[Bar] = list(warmup)
        self.trades: list[LalithaTrade] = []
        self.open_trade: Optional[LalithaTrade] = None
        self.done = False

    def _exit(self, t: LalithaTrade, when: datetime, premium: float, index: float, reason: str) -> str:
        t.exit_time, t.exit_premium, t.exit_index, t.exit_reason = when.isoformat(), round(premium, 2), round(index, 2), reason
        t.pnl_points = round(premium - t.entry_fill, 2)
        self.open_trade = None
        return (f"EXIT {t.side} {t.strike:g} at {premium:.2f} - {reason} (bought {t.entry_fill:.2f}, "
                f"{t.pnl_points:+.2f} points = Rs {t.pnl_rupees:+,.0f})")

    def indicators(self) -> dict:
        closes = [b.close for b in self.bars]
        st = supertrend(self.bars, 10, 2.0)
        r = rsi(closes, 14)
        bb = bollinger(closes, BB_PERIOD, BB_MULT)
        return {"st": st[-1], "st_prev": st[-2] if len(st) > 1 else (None, 0), "rsi": r[-1], "bb": bb[-1]}

    def on_candle(self, when: datetime, bar: Bar, premium: PremiumAt, candidates: Callable[[str], list[float]]) -> list[str]:
        if self.done:
            return []
        self.bars.append(bar)
        closes = (when + CANDLE).time()
        if when.date() != self.day:
            return []
        ind = self.indicators()
        (line, direction), (_, prev_direction) = ind["st"], ind["st_prev"]
        events: list[str] = []
        t = self.open_trade
        if t is not None:
            p = premium(t.strike, t.side)
            flipped = (t.side == "CE" and direction == -1) or (t.side == "PE" and direction == 1)
            if p is not None and flipped:
                events.append(self._exit(t, when, p, bar.close,
                                         f"Supertrend turned {'down' if t.side == 'CE' else 'up'} - candle {when:%H:%M} closed "
                                         f"{bar.close:g} ({'below' if t.side == 'CE' else 'above'} {line:.2f})"))
            elif p is not None and closes >= SQUARE_OFF:
                events.append(self._exit(t, when, p, bar.close, "15:15 square-off"))
        if closes >= SQUARE_OFF:
            self.done = True
            return events
        if self.open_trade is not None or len(self.trades) >= MAX_TRADES or not (FIRST_ENTRY_CLOSE <= closes <= LAST_ENTRY_CLOSE):
            return events
        if ind["rsi"] is None or ind["bb"] is None or direction == 0:
            return events
        lower, _, upper = ind["bb"]
        side = None
        if direction == 1 and ind["rsi"] > RSI_UP and bar.close > self.pivot["R1"] and bar.close > upper:
            side = "CE"
        elif direction == -1 and ind["rsi"] < RSI_DOWN and bar.close < self.pivot["S1"] and bar.close < lower:
            side = "PE"
        if side is None:
            return events
        priced = [(abs(p - TARGET_PREMIUM), k, p) for k in candidates(side) if (p := premium(k, side)) is not None]
        if not priced:
            return events + [f"{side} signal at {when:%H:%M} but no option prices - skipped"]
        _, strike, fill = min(priced)
        why = (f"candle {when:%H:%M} closed {bar.close:g}: Supertrend {'up' if side == 'CE' else 'down'} ({line:.2f}), "
               f"RSI {ind['rsi']:.1f} {'>' if side == 'CE' else '<'} {RSI_UP if side == 'CE' else RSI_DOWN:g}, "
               f"{'above R1' if side == 'CE' else 'below S1'} {self.pivot['R1' if side == 'CE' else 'S1']:.2f}, "
               f"{'above the upper' if side == 'CE' else 'below the lower'} Bollinger band "
               f"{upper if side == 'CE' else lower:.2f} -> {strike:g} {side} (premium nearest 250)")
        trade = LalithaTrade(date=self.day.isoformat(), side=side, strike=strike, qty=self.qty, entry_time=when.isoformat(),
                             entry_fill=round(fill, 2), entry_index=round(bar.close, 2), entry_reason=why)
        self.trades.append(trade)
        self.open_trade = trade
        events.append(f"BUY {self.qty} x {side} {strike:g} at {fill:.2f} ({why})")
        return events

    def total(self) -> tuple[float, float]:
        closed = [t for t in self.trades if t.exit_reason]
        return round(sum(t.pnl_points for t in closed), 2), round(sum(t.pnl_rupees for t in closed), 2)
