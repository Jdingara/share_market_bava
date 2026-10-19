"""
Vengat ORB - Opening Range Breakout (owner, 2026-10-19). PAPER MODE.

  * Range: the index's first 5-minute candle (09:15-09:20) - its high and low.
  * Entry: a 5-minute candle CLOSING above the range high -> buy the ATM CE at that candle's close; closing below the
    range low -> the ATM PE. No other confirmation.
  * SL: the other end of the range on the index (CE: range low, PE: range high); but at most NIFTY 50 /
    SENSEX 100 index points from the entry (owner 19-10). Trades every day.
  * Target 1:2 on the index: CE target = entry index + 2 x (entry index - range low); PE mirrored.
  * Entries only on candles closing after 09:30 (09:35)-12:00 and 12:30-15:15, at most 10 trades a day; NIFTY 2 lots, SENSEX 6 lots.
  * Re-entry: any later candle closing outside the range. An opposite break closes the open trade and opens the new
    side. Everything is closed by 15:16 (at the close of the candle ending 15:15).

The premium exit is that candle's close (the moment the index touched the level inside the candle isn't known).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

from hlc_signal import Candle

CANDLE = timedelta(minutes=5)
WINDOWS = ((time(9, 35), time(12, 0)), (time(12, 30), time(15, 10)))  # candle CLOSE times; owner 19-10: after 09:30 (09:35)
SQUARE_OFF = time(15, 15)  # the candle closing 15:15 closes everything (owner: "all close 3.16pm")
MAX_TRADES = 10
REWARD = 2.0  # 1:2


@dataclass(frozen=True)
class OrbMarket:
    name: str
    strike_step: int
    lot: int  # quantity per trade (lots x lot size)
    max_sl: float  # owner 19-10: the SL is at most this many index points from the entry (NIFTY 50, SENSEX 100)


# owner 19-10: fixed size - NIFTY 2 lots (2 x 65), SENSEX 6 lots (6 x 20)
ORB_MARKETS = {"NIFTY": OrbMarket("NIFTY", 50, 2 * 65, 50), "SENSEX": OrbMarket("SENSEX", 100, 6 * 20, 100)}


@dataclass
class OrbTrade:
    date: str
    side: str  # CE | PE
    strike: float
    qty: int
    entry_time: str
    entry_fill: float
    entry_index: float
    sl_index: float
    target_index: float
    entry_reason: str = ""
    exit_time: str = ""
    exit_premium: float = 0.0
    exit_index: float = 0.0
    exit_reason: str = ""
    pnl_points: float = 0.0

    @property
    def pnl_rupees(self) -> float:
        return round(self.pnl_points * self.qty, 2)


def _closes_at(when: datetime) -> time:
    return (when + CANDLE).time()


class OrbDay:
    def __init__(self, day: date, market: OrbMarket):
        self.day, self.market = day, market
        self.high: Optional[float] = None
        self.low: Optional[float] = None
        self.trades: list[OrbTrade] = []
        self.open_trade: Optional[OrbTrade] = None
        self.done = False

    def _exit(self, trade: OrbTrade, when: datetime, premium: float, index: float, reason: str) -> str:
        trade.exit_time, trade.exit_premium, trade.exit_index = when.isoformat(), round(premium, 2), round(index, 2)
        trade.exit_reason = reason
        trade.pnl_points = round(premium - trade.entry_fill, 2)
        self.open_trade = None
        return (f"EXIT {trade.side} {trade.strike:g} at {premium:.2f} - {reason} (bought {trade.entry_fill:.2f}, "
                f"{trade.pnl_points:+.2f} points = Rs {trade.pnl_rupees:+,.0f})")

    def _premium(self, chain: dict[tuple[float, str], Candle], trade: OrbTrade) -> Optional[float]:
        c = chain.get((trade.strike, trade.side))
        return c.close if c else None

    def on_candle(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle]) -> list[str]:
        """One completed 5-minute candle (`when` = its start): the index candle and the option candles by
        (strike, "CE"/"PE")."""
        if self.done:
            return []
        if self.high is None:
            if when.time() != time(9, 15):
                return []  # the range is the 09:15 candle - started too late to know it
            self.high, self.low = index.high, index.low
            return [f"Opening range (09:15-09:20): high {self.high:g}, low {self.low:g}"]
        events: list[str] = []
        closes = _closes_at(when)
        t = self.open_trade
        if t is not None:
            premium = self._premium(chain, t)
            if premium is not None:
                ce = t.side == "CE"
                sl_hit = index.low <= t.sl_index if ce else index.high >= t.sl_index
                target_hit = index.high >= t.target_index if ce else index.low <= t.target_index
                if sl_hit:  # (both in one candle: the SL is assumed first)
                    events.append(self._exit(t, when, premium, index.close,
                                             f"SL - index reached {t.sl_index:g} "
                                             f"in candle {when:%H:%M}"))
                elif target_hit:
                    events.append(self._exit(t, when, premium, index.close,
                                             f"TARGET 1:2 - index reached {t.target_index:g} in candle {when:%H:%M}"))
                elif closes >= SQUARE_OFF:
                    events.append(self._exit(t, when, premium, index.close, "15:16 square-off"))
                elif (index.close < self.low) if ce else (index.close > self.high):
                    events.append(self._exit(t, when, premium, index.close,
                                             f"opposite break - index closed {index.close:g} "
                                             f"{'below the range low' if ce else 'above the range high'}"))
        if closes >= SQUARE_OFF:
            self.done = True
            return events
        if self.open_trade is not None or len(self.trades) >= MAX_TRADES:
            return events
        if not any(a <= closes <= b for a, b in WINDOWS):
            return events
        side = "CE" if index.close > self.high else "PE" if index.close < self.low else None
        if side is None:
            return events
        step = self.market.strike_step
        strike = float(round(index.close / step) * step)
        prem = chain.get((strike, side))
        if prem is None:
            return events + [f"No {strike:g} {side} candle - entry skipped"]
        sl = self.low if side == "CE" else self.high
        wide = abs(index.close - sl) > self.market.max_sl
        if wide:  # owner 19-10: trade every day, but the SL at most NIFTY 50 / SENSEX 100 index points away
            sl = index.close - self.market.max_sl if side == "CE" else index.close + self.market.max_sl
        risk = abs(index.close - sl)
        target = index.close + REWARD * risk if side == "CE" else index.close - REWARD * risk
        trade = OrbTrade(date=self.day.isoformat(), side=side, strike=strike, qty=self.market.lot,
                         entry_time=when.isoformat(), entry_fill=round(prem.close, 2), entry_index=round(index.close, 2),
                         sl_index=round(sl, 2), target_index=round(target, 2),
                         entry_reason=(f"candle {when:%H:%M} closed {index.close:g} "
                                       f"{'above the range high' if side == 'CE' else 'below the range low'} "
                                       f"{self.high if side == 'CE' else self.low:g} -> ATM {strike:g} {side}"))
        self.trades.append(trade)
        self.open_trade = trade
        events.append(f"BUY {trade.qty} x {side} {strike:g} at {trade.entry_fill:.2f} ({trade.entry_reason}) - "
                      f"SL index {trade.sl_index:g} ({risk:.2f} pts{', capped' if wide else ''}), "
                      f"target index {trade.target_index:g} (1:2)")
        return events

    def total(self) -> tuple[float, float]:
        closed = [t for t in self.trades if t.exit_reason]
        return round(sum(t.pnl_points for t in closed), 2), round(sum(t.pnl_rupees for t in closed), 2)
