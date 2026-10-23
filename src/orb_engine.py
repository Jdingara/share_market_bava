"""
Vengat ORB - Opening Range Breakout (owner, 2026-10-19). PAPER MODE.

  * Range: the index's first 5-minute candle (09:15-09:20) - its high and low.
  * Entry: a 5-minute candle CLOSING above the range high -> buy the ATM CE at that candle's close; closing below the
    range low -> the ATM PE. No other confirmation.
  * Owner 22-10 (RETEST_075, the new rule): a NEW close beyond the range only ARMS the side; the entry is the retest
    of the first candle's 0.75 (PE: low + 0.75 x range, CE: high - 0.75 x range), SL = that candle's high + 1 / low - 1,
    target 1:2 from the 0.75. Each new break (below, then later above) arms its own retest.
  * SL: the other end of the range on the index (CE: range low, PE: range high); but at most NIFTY 50 /
    SENSEX 100 index points from the entry (owner 19-10). Trades every day.
  * Target 1:2 on the index: CE target = entry index + 2 x (entry index - range low); PE mirrored.
  * Entries only on candles closing after 09:30 (09:35)-12:00 and 12:30-15:15, at most 5 trades a day (owner 22-10, was 10), no new entry once the day's LOSS is Rs 10,000 (profit unlimited); NIFTY 2 lots, SENSEX 6 lots.
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
NO_MIDDAY_GAP = True  # owner 22-10: no 12:00-12:30 break - entries 09:35-15:10 straight (False = the 19-10 two windows)
if NO_MIDDAY_GAP:
    WINDOWS = ((time(9, 35), time(15, 10)),)
SQUARE_OFF = time(15, 15)  # the candle closing 15:15 closes everything (owner: "all close 3.16pm")
MAX_TRADES = 5  # owner 22-10: 5 trades a day (was 10 - kept in tag orb-rules-2026-10-21)
PROFIT_STOP = 0  # owner 22-10 night: "sorry - loss 10k, target unlimited" - no profit stop (was Rs 10,000 earlier on 22-10)
LOSS_STOP = 10_000  # owner 22-10 night: once the day's booked loss reaches Rs 10,000 - no new entry
REWARD = 2.0  # 1:2
# owner 22-10: after the break, enter on the RETEST of the first 5-min candle's 0.75 (Fib on that candle):
#   PE (break below): Fib from the low up -> 0.75 = low + 0.75 x range;  CE (break above): high - 0.75 x range.
#   SL = that candle's high + 1 (PE) / low - 1 (CE) - a small SL. False = the old entry at the breakout close.
RETEST_075 = True
# owner 23-10 ('now'): the retest is the 0.5 - 0.618 ZONE of the first candle (same Fib direction as the 0.75) and the
# entry needs a CONFIRMATION: after the index reaches the zone, a candle closing in the break's direction (PE: red,
# CE: green) -> buy at that close. SL unchanged (first candle high + 1 / low - 1). False = the 22-10 0.75 touch entry.
RETEST_ZONE = (0.5, 0.618)
ZONE_CONFIRM = True
# owner 22-10: target = NIFTY 50 / SENSEX 100 index points from the entry; reaching it does NOT close the trade -
# a trailing SL follows the index's best price by NIFTY 20 / SENSEX 50 points. False = the old 1:2 target exit.
TARGET_TSL = True
ROUND_STRIKE = 100  # owner 22-10 evening: the retest buys the round-100 strike nearest the 0.75 (22664 -> 22700); 0 = strike step
TARGET_POINTS = {"NIFTY": 40, "SENSEX": 80}  # owner 22-10 evening: NIFTY 40 (was 50), SENSEX 80 (was 100)
TSL_POINTS = {"NIFTY": 25, "SENSEX": 50}  # owner 22-10 evening: 25 / 50 (was 20 / 50)
TARGET_SLACK = 2  # owner 22-10: the target counts as reached within 2 points of it
# owner 22-10 evening: after the target the SL moves in STEPS ("25, 50 enkira vikithathil"): each further full step
# beyond the target lifts the SL by one step - +1 step -> SL at the target, +2 -> target + 1 step, ...
# False = the earlier continuous trail (best price - TSL points).
STEP_TSL = True
# owner 22-10 night: "target eppavume option premium" - the target (40 / 80 +-2) and the TSL steps (25 / 50) are
# OPTION PREMIUM points from the entry fill; the SL stays on the index (first candle high + 1 / low - 1). Fills at the
# moment of the touch (estimated inside the 5-min candle), not at the candle close. False = index-point target.
PREMIUM_TARGET = True
# owner 22-10 night: SENSEX - a wick to +80 is not enough; the target counts only when a 5-min option candle CLOSES at it
# (until then the SL stays on the index, first candle high / low). NIFTY: the touch counts.
TARGET_ON_CLOSE = {"NIFTY": True, "SENSEX": True}  # NIFTY too (owner 22-10 night: "niftykkum same")


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
    riding: bool = False  # TARGET_TSL: the target was reached, the trailing SL rides it
    best_index: float = 0.0
    target_premium: float = 0.0  # PREMIUM_TARGET: entry fill + 40 / 80
    trail_premium: float = 0.0  # PREMIUM_TARGET: the premium SL once the steps start (0 = none yet)
    best_premium: float = 0.0
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
        self.armed: Optional[dict] = None  # RETEST_075: {"side", "level", "when"} after a NEW close beyond the range
        self.last_pos: Optional[str] = None  # where the previous candle closed: "CE" above, "PE" below, None inside

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
        if t is not None and PREMIUM_TARGET and TARGET_TSL:
            events += self._premium_exits(t, when, index, chain, closes)
        elif t is not None:
            premium = self._premium(chain, t)
            if premium is not None:
                ce = t.side == "CE"
                sl_hit = index.low <= t.sl_index if ce else index.high >= t.sl_index
                slack = TARGET_SLACK if TARGET_TSL else 0
                target_hit = index.high >= t.target_index - slack if ce else index.low <= t.target_index + slack
                if sl_hit:  # (both in one candle: the SL is assumed first)
                    events.append(self._exit(t, when, premium, index.close,
                                             f"{'TSL' if t.riding else 'SL'} - index reached {t.sl_index:g} "
                                             f"in candle {when:%H:%M}"))
                elif TARGET_TSL and (target_hit or t.riding):
                    tsl = TSL_POINTS[self.market.name]
                    if not t.riding:
                        t.riding, t.best_index = True, t.target_index
                    t.best_index = max(t.best_index, index.high) if ce else min(t.best_index, index.low)
                    trail = t.best_index - tsl if ce else t.best_index + tsl
                    if STEP_TSL:
                        steps = int(abs(t.best_index - t.target_index) // tsl) if (
                            t.best_index > t.target_index if ce else t.best_index < t.target_index) else 0
                        trail = (t.target_index + (steps - 1) * tsl * (1 if ce else -1)) if steps else t.sl_index
                    if (trail > t.sl_index) if ce else (trail < t.sl_index):
                        t.sl_index = round(trail, 2)
                        events.append(f"TSL {t.side} {t.strike:g}: index best {t.best_index:g} -> SL index {t.sl_index:g} "
                                      f"({f'steps of {tsl} pts beyond the target' if STEP_TSL else f'{tsl} pts behind'})")
                    if closes >= SQUARE_OFF:
                        events.append(self._exit(t, when, premium, index.close, "15:16 square-off"))
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
        if RETEST_075:
            return events + self._retest_entry(when, index, chain, closes)
        if self.open_trade is not None or len(self.trades) >= MAX_TRADES:
            return events
        if PROFIT_STOP and sum(t.pnl_rupees for t in self.trades) >= PROFIT_STOP:
            return events
        if LOSS_STOP and sum(t.pnl_rupees for t in self.trades) <= -LOSS_STOP:
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
        if TARGET_TSL:
            target = index.close + TARGET_POINTS[self.market.name] * (1 if side == "CE" else -1)
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
                      f"target index {trade.target_index:g} ({self._target_note()})")
        return events

    def _retest_entry(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle], closes: time) -> list[str]:
        # owner 22-10: once a break below, another time a break above - each NEW break (a close beyond the range after
        # a close inside it or beyond the other side) arms its own retest; only that retest is an entry
        side = "CE" if index.close > self.high else "PE" if index.close < self.low else None
        fresh = side is not None and side != self.last_pos
        self.last_pos = side
        if self.open_trade is not None:
            self.armed = None
            return []
        events: list[str] = []
        rng = self.high - self.low
        a = self.armed
        if a is not None and (len(self.trades) < MAX_TRADES
                              and not (PROFIT_STOP and sum(t.pnl_rupees for t in self.trades) >= PROFIT_STOP)
                              and not (LOSS_STOP and sum(t.pnl_rupees for t in self.trades) <= -LOSS_STOP)
                              and any(x <= closes <= y for x, y in WINDOWS)):
            if ZONE_CONFIRM:
                ce = a["side"] == "CE"
                if (index.low <= a["zone"][0]) if ce else (index.high >= a["zone"][0]):
                    a["in_zone"] = True
                # the confirmation candle closes in the break's direction while still inside the range (a close beyond
                # the range is a new break, not the retest's confirmation)
                confirmed = (a.get("in_zone") and ((index.close > index.open) if ce else (index.close < index.open))
                             and self.low <= index.close <= self.high)
                event = self._open_retest(when, index, chain, a, confirm=True) if confirmed else None
                if event:
                    self.armed = None
                    return [event]
                touched = False
            else:
                touched = index.low <= a["level"] if a["side"] == "CE" else index.high >= a["level"]
            if touched:
                event = self._open_retest(when, index, chain, a)
                if event:
                    self.armed = None
                    return [event]
        if fresh:
            level = self.high - 0.75 * rng if side == "CE" else self.low + 0.75 * rng
            z = [round(self.high - r * rng if side == "CE" else self.low + r * rng, 2) for r in RETEST_ZONE]
            self.armed = {"side": side, "level": round(level, 2), "when": when, "zone": z}
            wait = (f"the {RETEST_ZONE[0]:g}-{RETEST_ZONE[1]:g} zone {z[0]:.2f}-{z[1]:.2f} + a confirmation candle"
                    if ZONE_CONFIRM else f"the retest of 0.75 {level:.2f}")
            events.append(f"Break {'above' if side == 'CE' else 'below'} the range at {when:%H:%M} (close {index.close:g}) "
                          f"- waiting for {wait} for a {side}")
        return events

    def _open_retest(self, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle], a: dict,
                     confirm: bool = False) -> Optional[str]:
        side, level = a["side"], (index.close if confirm else a["level"])
        step = max(self.market.strike_step, ROUND_STRIKE)
        strike = float(round(level / step) * step)
        prem = chain.get((strike, side))
        if prem is None:
            return None
        sl = self.low - 1 if side == "CE" else self.high + 1
        wide = abs(level - sl) > self.market.max_sl
        if wide:
            sl = level - self.market.max_sl if side == "CE" else level + self.market.max_sl
        risk = abs(level - sl)
        target = level + REWARD * risk if side == "CE" else level - REWARD * risk
        if TARGET_TSL:
            target = level + TARGET_POINTS[self.market.name] * (1 if side == "CE" else -1)
        fill = round(prem.close, 2) if confirm or not PREMIUM_TARGET else self._premium_at(level, index, prem, side)
        trade = OrbTrade(date=self.day.isoformat(), side=side, strike=strike, qty=self.market.lot,
                         entry_time=when.isoformat(), entry_fill=fill, entry_index=round(level, 2),
                         sl_index=round(sl, 2), target_index=round(target, 2),
                         entry_reason=(f"break {'above' if side == 'CE' else 'below'} the range at {a['when']:%H:%M}, "
                                       + (f"retest of the {RETEST_ZONE[0]:g}-{RETEST_ZONE[1]:g} zone {a['zone'][0]:g}-{a['zone'][1]:g}, "
                                          f"confirmation candle {when:%H:%M} closed {index.close:g}" if confirm else
                                          f"retest of the first candle's 0.75 {level:g} in candle {when:%H:%M}")
                                       + f" -> ATM {strike:g} {side}"))
        if PREMIUM_TARGET and TARGET_TSL:
            trade.target_premium = round(fill + TARGET_POINTS[self.market.name], 2)
            trade.target_index = 0.0
        self.trades.append(trade)
        self.open_trade = trade
        if PREMIUM_TARGET and TARGET_TSL:
            return (f"BUY {trade.qty} x {side} {strike:g} at {trade.entry_fill:.2f} ({trade.entry_reason}) - "
                    f"SL index {trade.sl_index:g} ({risk:.2f} pts{', capped' if wide else ''}), target premium "
                    f"{trade.target_premium:g} (+{TARGET_POINTS[self.market.name]} +-{TARGET_SLACK}), then the SL in "
                    f"premium steps of {TSL_POINTS[self.market.name]} - no exit at the target")
        return (f"BUY {trade.qty} x {side} {strike:g} at {trade.entry_fill:.2f} ({trade.entry_reason}) - "
                f"SL index {trade.sl_index:g} ({risk:.2f} pts{', capped' if wide else ''}), target index {trade.target_index:g} "
                f"({self._target_note()})")

    @staticmethod
    def _premium_at(level: float, index: Candle, opt: Candle, side: str) -> float:
        """The option price when the index stood at `level` inside this 5-min candle - placed between the option's
        low and high in proportion (CE rises with the index, PE falls)."""
        span = index.high - index.low
        f = min(1.0, max(0.0, (level - index.low) / span)) if span > 0 else 0.5
        if side == "PE":
            f = 1 - f
        return round(opt.low + f * (opt.high - opt.low), 2)

    def _premium_exits(self, t: OrbTrade, when: datetime, index: Candle, chain: dict[tuple[float, str], Candle],
                       closes: time) -> list[str]:
        opt = chain.get((t.strike, t.side))
        if opt is None:
            return []
        ce = t.side == "CE"
        if index.low <= t.sl_index if ce else index.high >= t.sl_index:  # the index SL (first candle +-1)
            fill = self._premium_at(t.sl_index, index, opt, t.side)
            return [self._exit(t, when, fill, t.sl_index, f"SL - index reached {t.sl_index:g} in candle {when:%H:%M}")]
        if t.trail_premium and opt.low <= t.trail_premium:
            fill = min(t.trail_premium, opt.open)
            return [self._exit(t, when, fill, index.close,
                               f"TSL - premium came back to {t.trail_premium:g} in candle {when:%H:%M}")]
        events: list[str] = []
        step = TSL_POINTS[self.market.name]
        reached = opt.close if TARGET_ON_CLOSE.get(self.market.name) else opt.high
        if not t.riding and reached >= t.target_premium - TARGET_SLACK:
            t.riding, t.best_premium = True, t.target_premium
            events.append(f"TARGET {t.side} {t.strike:g}: premium reached {t.target_premium:g} - no exit, "
                          f"SL locked at the target, then up in steps of {step}")
        if t.riding:
            t.best_premium = max(t.best_premium, opt.high)
            # owner 22-10 night ("muthal entry 40 kidaikkum, 2vathu 100"): the target touch locks the SL AT the
            # target (+40 kept), each further full step lifts it by one step
            steps = max(0, int((t.best_premium - t.target_premium) // step))
            trail = round(t.target_premium + steps * step, 2)
            if True:
                if trail > t.trail_premium:
                    t.trail_premium = trail
                    events.append(f"TSL {t.side} {t.strike:g}: premium best {t.best_premium:g} -> SL premium {trail:g}")
        if closes >= SQUARE_OFF:
            events.append(self._exit(t, when, opt.close, index.close, "15:16 square-off"))
        elif not t.riding and ((index.close < self.low) if ce else (index.close > self.high)):
            events.append(self._exit(t, when, opt.close, index.close,
                                     f"opposite break - index closed {index.close:g} "
                                     f"{'below the range low' if ce else 'above the range high'}"))
        return events

    def _target_note(self) -> str:
        if TARGET_TSL:
            return (f"{TARGET_POINTS[self.market.name]} pts (+-{TARGET_SLACK}), then TSL "
                    f"{'in steps of ' if STEP_TSL else ''}{TSL_POINTS[self.market.name]} pts - no exit at the target")
        return "1:2"

    def total(self) -> tuple[float, float]:
        closed = [t for t in self.trades if t.exit_reason]
        return round(sum(t.pnl_points for t in closed), 2), round(sum(t.pnl_rupees for t in closed), 2)
