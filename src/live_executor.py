"""
Real-money execution for one bot (Sniper NIFTY/SENSEX, HLC NIFTY/SENSEX).

The strategy engine still makes every decision, exactly as in paper mode.
This module carries the decisions out at Zerodha and keeps the real position
in line with them:

  * After every batch of 5-minute candles the bot calls sync() with what the
    engine holds (a Want) and the buys it is waiting for (Triggers, e.g.
    Sniper's "buy at 100 if it comes back, or at 121 if it runs up").
  * Every couple of seconds tick() watches the live price: a trigger level
    reached -> buy; a target reached -> sell. The stop-loss rests at Zerodha as
    an SL order, so the position is protected even if this program stops.
  * Engine holds, we don't -> buy now (only once per engine trade, never for a
    trade found while catching up after a restart, and only if the price is
    still between the stop and the target). Engine flat, we hold -> sell.
  * Lots come from the bot's share of the morning money (live_account); a
    bot without enough money for 1 lot doesn't trade and says so.
  * The day's max loss or a STOP file -> sell everything, no more buys.

The bot's own record (position, buys already tried, booked P&L) is saved to
.cache/live/<bot>_<date>.json after every change, so a restart picks up the
open position instead of buying again. Every sell is also appended to
history/live/trades.csv.
"""

from __future__ import annotations

import csv
import json
import os
import threading
import time as time_module
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Optional

from broker import OrderState
from live_account import SharedAccount
from live_money import lots_for

TICK_SECONDS = 2.0
FILL_POLL_SECONDS = 1.0
FILL_POLLS = 3  # status checks per price before re-pricing
FILL_REPRICES = 3  # limit order moved to the market this many times, then the rest is cancelled
SLIP, MIN_SLIP = 0.01, 0.5  # buy/sell limit this far through the last price
STOP_SLIP, MIN_STOP_SLIP = 0.03, 1.0  # SL order's limit this far below its trigger
LAST_BUY = time(15, 0)
FORCE_EXIT = time(15, 1)  # anything still open is sold - the engines exit at 15:00 already
SAME_TRADE_WINDOW = timedelta(minutes=5)  # a live buy and an engine entry one candle apart are the same trade
TRADE_LOG_FIELDS = ["date", "bot", "symbol", "qty", "buy_time", "buy_price", "sell_time", "sell_price", "reason",
                    "pnl_points", "pnl_rupees"]


@dataclass(frozen=True)
class Want:
    """The engine holds `symbol` (entry candle starting `entry`)."""
    symbol: str
    entry: datetime
    stop: Optional[float]  # premium stop; None = the engine exits on its own rule (e.g. HLC's index stop)
    target: Optional[float]  # premium target sold in real time; None = the engine exits at a candle close
    late: bool = False  # found while catching up after a restart - never bought


@dataclass(frozen=True)
class Trigger:
    """A buy the engine is waiting for: price back to `level` ("limit") or up to it ("stop")."""
    symbol: str
    kind: str
    level: float
    stop: Optional[float]
    target: Optional[float]


@dataclass
class Position:
    symbol: str
    qty: int
    avg: float
    stop: Optional[float]
    target: Optional[float]
    sl_order: Optional[str]
    bought_at: str
    candle: str  # start of the 5-minute candle it was bought in
    exiting: str = ""  # a sell that hasn't completed yet - retried every tick


def candle_start(when: datetime) -> datetime:
    return when.replace(minute=when.minute - when.minute % 5, second=0, microsecond=0)


def _slip(price: float) -> float:
    return max(MIN_SLIP, price * SLIP)


def _stop_limit(stop: float) -> float:
    return stop - max(MIN_STOP_SLIP, stop * STOP_SLIP)


class LiveExecutor:
    def __init__(self, bot: str, lot_size: int, max_lots: int, broker, account: SharedAccount,
                 notify: Callable[[str], None], ledger_dir: Path, trade_log: Path,
                 now: Callable[[], datetime] = datetime.now, sleep: Callable[[float], None] = time_module.sleep):
        self.bot = bot
        self.lot_size = lot_size
        self.max_lots = max_lots
        self.broker = broker
        self.account = account
        self.notify = notify
        self.trade_log = trade_log
        self.now = now
        self.sleep = sleep
        self.lock = threading.RLock()
        self.triggers: list[Trigger] = []
        self.fired: Optional[str] = None  # symbol bought on a trigger the engine hasn't caught up with yet
        self.halted: Optional[str] = None
        self.share_told = False
        self._stop_thread = threading.Event()
        self.ledger = ledger_dir / f"{bot}_{now().date().isoformat()}.json"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        saved = json.loads(self.ledger.read_text(encoding="utf-8")) if self.ledger.exists() else {}
        self.position: Optional[Position] = Position(**saved["position"]) if saved.get("position") else None
        self.tried: list[list[str]] = saved.get("tried", [])  # [symbol, entry candle] - each engine trade bought once
        self.booked: float = saved.get("booked", 0.0)
        if self.position:
            p = self.position
            self._say(f"restarted - holding {p.qty} x {p.symbol} bought at {p.avg:.2f}, SL order {p.sl_order or 'none'}")

    # --- helpers ---

    def _say(self, text: str) -> None:
        try:
            self.notify(f"REAL {self.bot}: {text}")
        except Exception:
            pass

    def _save(self) -> None:
        data = {"position": asdict(self.position) if self.position else None, "tried": self.tried,
                "booked": round(self.booked, 2)}
        tmp = self.ledger.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.ledger)

    def _prices(self, symbols: list[str]) -> dict[str, float]:
        if not symbols:
            return {}
        try:
            return self.broker.ltp(symbols)
        except Exception as error:
            print(f"  (live price fetch failed: {error})", flush=True)
            return {}

    def _ltp(self, symbol: str) -> Optional[float]:
        return self._prices([symbol]).get(symbol)

    def _tried(self, symbol: str, entry: datetime) -> bool:
        return any(s == symbol and abs(datetime.fromisoformat(t) - entry) <= SAME_TRADE_WINDOW for s, t in self.tried)

    def _mark_tried(self, symbol: str, entry: datetime) -> None:
        self.tried.append([symbol, entry.isoformat()])

    def _state(self, order_id: str) -> Optional[OrderState]:
        try:
            return self.broker.state(order_id)
        except Exception as error:
            print(f"  (order status {order_id} failed: {error})", flush=True)
            return None

    # --- called by the bot after each batch of candles ---

    def sync(self, want: Optional[Want], triggers: list[Trigger], through: Optional[datetime]) -> None:
        """`through`: start of the last candle the engine has processed."""
        with self.lock:
            if self.halted:
                return
            if self.fired and ((want and want.symbol == self.fired) or not triggers):
                self.fired = None  # the engine has caught up with the trigger buy
            pos = self.position
            if pos and (want is None or want.symbol != pos.symbol):
                if through is None or datetime.fromisoformat(pos.candle) > through:
                    self.triggers = []  # bought in a candle the engine hasn't seen yet - wait for it
                    return
                self._exit("the strategy exited")
                if self.position:
                    return
            if self.position and want:
                self._follow(want)
                return
            self.triggers = [t for t in triggers if t.symbol != self.fired]
            if want and not self._tried(want.symbol, want.entry):
                self._mark_tried(want.symbol, want.entry)
                self._save()
                if want.late:
                    self._say(f"{want.symbol} entry at {want.entry:%H:%M} happened while the bot was not running - "
                              "not bought (no real orders for catch-up trades)")
                else:
                    self._buy_now(want)

    def _follow(self, want: Want) -> None:
        """We hold what the engine holds: take over its stop (only ever up) and target."""
        pos = self.position
        if not self._tried(want.symbol, want.entry):
            self._mark_tried(want.symbol, want.entry)
        if want.stop is not None and (pos.stop is None or want.stop > pos.stop):
            self._move_stop(want.stop)
        if self.position:
            self.position.target = want.target
        self.triggers = []
        self._save()

    def _buy_now(self, want: Want) -> None:
        ltp = self._ltp(want.symbol)
        if ltp is None:
            self._say(f"no live price for {want.symbol} - entry at {want.entry:%H:%M} not bought")
        elif want.stop is not None and ltp <= want.stop:
            self._say(f"{want.symbol} is already at {ltp:.2f}, at/below the stop {want.stop:g} - not bought")
        elif want.target is not None and ltp >= want.target:
            self._say(f"{want.symbol} is already at {ltp:.2f}, at/above the target {want.target:g} - not bought")
        elif self.now().time() >= LAST_BUY:
            self._say(f"{want.symbol}: too late in the day to buy")
        else:
            self._enter(want.symbol, ltp, want.stop, want.target, f"strategy entry, candle {want.entry:%H:%M}", want.entry)

    # --- every couple of seconds ---

    def tick(self) -> None:
        with self.lock:
            now = self.now()
            self._check_money(now)
            reason = self.halted or self.account.halted()
            if reason:
                self._halt(reason)
                return
            if now.time() >= FORCE_EXIT:
                self.triggers = []
                if self.position:
                    self._exit(self.position.exiting or "15:00 - end of the trading day")
                return
            pos = self.position
            prices = self._prices(([pos.symbol] if pos else []) + [t.symbol for t in self.triggers])
            if pos:
                self._watch_position(prices.get(pos.symbol))
            elif self.triggers and now.time() < LAST_BUY:
                self._watch_triggers(prices, now)
            self._report(prices, now)

    def _watch_position(self, ltp: Optional[float]) -> None:
        pos = self.position
        if pos.exiting:
            self._exit(pos.exiting)
            return
        if pos.sl_order:
            state = self._state(pos.sl_order)
            if state and state.status == "COMPLETE":
                pos.sl_order = None
                self._book(state.filled, state.average, f"STOPLOSS {pos.stop:g} (Zerodha SL order)")
                return
            if state and state.status in ("REJECTED", "CANCELLED"):
                self._say(f"stop-loss order {state.status.lower()} by Zerodha ({state.message}) - the bot will sell at "
                          f"{pos.stop:g} itself")
                pos.sl_order = None
                self._save()
            elif state and state.status == "OPEN" and ltp is not None and ltp < _stop_limit(pos.stop):
                self._exit(f"STOPLOSS {pos.stop:g} (price fell through the SL order's limit)")
                return
        if ltp is None:
            return
        if pos.target is not None and ltp >= pos.target:
            self._exit(f"TARGET {pos.target:g}")
        elif pos.stop is not None and pos.sl_order is None and ltp <= pos.stop:
            self._exit(f"STOPLOSS {pos.stop:g}")

    def _watch_triggers(self, prices: dict[str, float], now: datetime) -> None:
        for trig in self.triggers:
            ltp = prices.get(trig.symbol)
            if ltp is None:
                continue
            if (trig.kind == "limit" and ltp <= trig.level) or (trig.kind == "stop" and ltp >= trig.level):
                self.triggers = []
                self.fired = trig.symbol
                self._mark_tried(trig.symbol, candle_start(now))
                self._save()
                if trig.stop is not None and ltp <= trig.stop:
                    self._say(f"{trig.symbol} reached {trig.level:g} but is already at/below the stop {trig.stop:g} - not bought")
                else:
                    self._enter(trig.symbol, ltp, trig.stop, trig.target,
                                f"price {ltp:.2f} reached the {trig.level:g} buy level", candle_start(now))
                return

    def _check_money(self, now: datetime) -> None:
        if self.share_told:
            return
        try:
            account = self.account.allocate_if_due(now, self.broker.funds)
        except Exception as error:
            print(f"  (reading Zerodha funds failed: {error})", flush=True)
            return
        if account is None:
            return
        self.share_told = True
        share = (account["allocation"] or {}).get(self.bot)
        if share is None and self.bot not in account["registered"]:
            self._say(f"started after the {account.get('allocated_at', '')} money split - not in today's split, "
                      "this bot will not trade today")
        elif share is None:
            self._say(f"not enough money today - this bot will not trade (Rs {account['capital']:,.0f} in the account, "
                      f"shared as {account['allocation'] or 'nothing'})")
        else:
            self._say(f"today's money for this bot: Rs {share:,.0f} of Rs {account['capital']:,.0f} - "
                      f"day stops if all bots together lose Rs {account['max_loss']:,.0f}")

    def _report(self, prices: dict[str, float], now: datetime) -> None:
        pos = self.position
        open_pnl = (prices[pos.symbol] - pos.avg) * pos.qty if pos and pos.symbol in prices else 0.0
        try:
            reason = self.account.report(self.bot, self.booked, open_pnl, now)
        except Exception as error:
            print(f"  (account update failed: {error})", flush=True)
            return
        if reason:
            self._halt(reason)

    def _halt(self, reason: str) -> None:
        if not self.halted:
            self.halted = reason
            self.triggers = []
            self._say(f"DAY STOPPED - {reason}. Selling anything held; no more trades today.")
            try:
                self.account.halt(reason)
            except Exception:
                pass
        if self.position:
            self._exit(self.position.exiting or "day stopped")

    # --- orders ---

    def _enter(self, symbol: str, price: float, stop: Optional[float], target: Optional[float], why: str,
               candle: datetime) -> None:
        share = self.account.share(self.bot)
        if share is None:
            self._say(f"signal for {symbol} at {price:.2f} ({why}) - no money for this bot today, not bought")
            return
        money = share + self.booked
        lots = lots_for(money, price, self.lot_size, self.max_lots)
        try:
            lots = min(lots, lots_for(self.broker.funds(), price, self.lot_size, self.max_lots))
        except Exception as error:
            print(f"  (reading Zerodha funds failed: {error})", flush=True)
        if lots == 0:
            self._say(f"signal for {symbol} at {price:.2f} ({why}) - not enough money for 1 lot "
                      f"({self.lot_size} qty, about Rs {price * self.lot_size:,.0f}; this bot has Rs {money:,.0f}) - not bought")
            return
        filled, average = self._fill("BUY", symbol, lots * self.lot_size, price)
        if filled == 0:
            self._say(f"BUY {symbol} was not filled - no trade")
            return
        now = self.now()
        self.position = Position(symbol, filled, average, None, target, None, now.isoformat(timespec="seconds"),
                                 candle.isoformat())
        self._save()
        stop_text = f"SL {stop:g}" if stop is not None else "SL by the strategy"
        self._say(f"BOUGHT {filled} x {symbol} at {average:.2f} ({why}) - {stop_text}"
                  + (f", target {target:g}" if target is not None else ""))
        if stop is not None:
            self._move_stop(stop)

    def _move_stop(self, stop: float) -> None:
        """Puts the stop-loss at `stop` (a new SL order, or the existing one moved up)."""
        pos = self.position
        pos.stop = stop
        ltp = self._ltp(pos.symbol)
        if ltp is not None and ltp <= stop:
            self._exit(f"STOPLOSS {stop:g} (price {ltp:.2f} already at/below it)")
            return
        try:
            if pos.sl_order:
                self.broker.modify(pos.sl_order, _stop_limit(stop), trigger=stop)
            else:
                pos.sl_order = self.broker.stop_sell(pos.symbol, pos.qty, stop, _stop_limit(stop))
        except Exception as error:
            state = self._state(pos.sl_order) if pos.sl_order else None
            if state and state.status == "COMPLETE":  # the old stop filled just before the move
                pos.sl_order = None
                self._book(state.filled, state.average, "STOPLOSS (Zerodha SL order)")
                return
            self._say(f"could not place/move the stop-loss order to {stop:g} ({error}) - the bot will sell at the stop itself")
            if pos.sl_order and (state is None or state.done):
                pos.sl_order = None
        self._save()

    def _exit(self, why: str) -> None:
        pos = self.position
        pos.exiting = why
        if pos.sl_order:
            try:
                self.broker.cancel(pos.sl_order)
            except Exception:
                pass  # already complete/cancelled - the state below tells
            state = self._state(pos.sl_order)
            if state is None or not state.done:
                self._save()
                return  # can't confirm the SL order is gone - selling now could sell twice; retry next tick
            pos.sl_order = None
            if state.filled:
                self._book(state.filled, state.average, f"STOPLOSS {pos.stop:g} (Zerodha SL order)")
                if self.position is None:
                    return
        ltp = self._ltp(pos.symbol)
        filled, average = self._fill("SELL", pos.symbol, pos.qty, ltp if ltp is not None else pos.avg)
        if filled:
            self._book(filled, average, why)
        if self.position:
            self._say(f"SELL {pos.symbol} not complete - {self.position.qty} still held, retrying")
            self._save()

    def _book(self, qty: int, price: float, why: str) -> None:
        pos = self.position
        points = price - pos.avg
        self.booked += points * qty
        pos.qty -= qty
        now = self.now()
        self._log_trade(pos, qty, price, why, now)
        self._say(f"SOLD {qty} x {pos.symbol} at {price:.2f} - {why} (bought {pos.avg:.2f}, {points:+.2f} points = "
                  f"Rs {points * qty:+,.0f}; today so far Rs {self.booked:+,.0f})")
        if pos.qty <= 0:
            self.position = None
        self._save()

    def _fill(self, side: str, symbol: str, qty: int, price: float) -> tuple[int, float]:
        """Places a limit order a little through `price`, re-prices it to the market a few times, then cancels
        whatever is left. Returns (filled qty, average price)."""
        limit = price + _slip(price) if side == "BUY" else price - _slip(price)
        try:
            order_id = self.broker.buy(symbol, qty, limit) if side == "BUY" else self.broker.sell(symbol, qty, limit)
        except Exception as error:
            self._say(f"{side} {qty} x {symbol} refused by Zerodha: {error}")
            return 0, 0.0
        state = None
        for attempt in range(FILL_REPRICES + 1):
            for _ in range(FILL_POLLS):
                self.sleep(FILL_POLL_SECONDS)
                state = self._state(order_id) or state
                if state and state.done:
                    break
            if state and state.done:
                break
            if attempt < FILL_REPRICES:
                ltp = self._ltp(symbol)
                if ltp is not None:
                    limit = ltp + _slip(ltp) if side == "BUY" else ltp - _slip(ltp)
                    try:
                        self.broker.modify(order_id, limit)
                    except Exception as error:
                        print(f"  (re-pricing {order_id} failed: {error})", flush=True)
        if state is None or not state.done:
            try:
                self.broker.cancel(order_id)
            except Exception:
                pass
            state = self._state(order_id) or state
        if state and state.status == "REJECTED":
            self._say(f"{side} {qty} x {symbol} rejected by Zerodha: {state.message}")
        return (state.filled, state.average) if state else (0, 0.0)

    def _log_trade(self, pos: Position, qty: int, price: float, why: str, now: datetime) -> None:
        try:
            self.trade_log.parent.mkdir(parents=True, exist_ok=True)
            new = not self.trade_log.exists()
            with self.trade_log.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=TRADE_LOG_FIELDS)
                if new:
                    writer.writeheader()
                points = round(price - pos.avg, 2)
                writer.writerow({"date": now.date().isoformat(), "bot": self.bot, "symbol": pos.symbol, "qty": qty,
                                 "buy_time": pos.bought_at[11:19], "buy_price": round(pos.avg, 2),
                                 "sell_time": now.strftime("%H:%M:%S"), "sell_price": round(price, 2), "reason": why,
                                 "pnl_points": points, "pnl_rupees": round(points * qty, 2)})
        except Exception as error:  # the record must never stop trading
            print(f"  (live trade log failed: {error})", flush=True)

    # --- lifecycle ---

    def start(self) -> None:
        def run():
            while not self._stop_thread.is_set():
                try:
                    self.tick()
                except Exception as error:  # never let the watcher die
                    print(f"  (live executor error: {type(error).__name__}: {error})", flush=True)
                self._stop_thread.wait(TICK_SECONDS)
        threading.Thread(target=run, name=f"live-{self.bot}", daemon=True).start()

    def finish(self) -> None:
        """End of the bot's day: nothing is left open."""
        with self.lock:
            self.triggers = []
            if self.position:
                self._exit(self.position.exiting or "bot finished for the day")
        self._stop_thread.set()


# --- setup used by sniper_live.py / hlc_live.py --real ---------------------------


def confirm_real_mode() -> None:
    """Second safety lock: --real alone is not enough, .env must also say LIVE_TRADING=YES."""
    if os.getenv("LIVE_TRADING", "").strip().upper() != "YES":
        raise SystemExit("--real places REAL orders with your money. To allow it, add this line to .env:\n"
                         "  LIVE_TRADING=YES")


def make_executor(kite, bot: str, exchange: str, lot_size: int, max_lots: int,
                  notify: Callable[[str], None]) -> LiveExecutor:
    from broker import KiteBroker
    from kite_auth import PROJECT_ROOT
    from live_account import LIVE_DIR

    return LiveExecutor(bot, lot_size, max_lots, KiteBroker(kite, exchange, bot.replace("_", ""), LIVE_DIR / "ltp"),
                        SharedAccount(date.today()), notify, LIVE_DIR, PROJECT_ROOT / "history" / "live" / "trades.csv")
