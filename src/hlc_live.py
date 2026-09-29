"""
HLC strategy on Zerodha data - PAPER ONLY, never places orders.

    py src\\hlc_live.py --market NIFTY           (live: start before 09:15, runs to 15:00)
    py src\\hlc_live.py --market SENSEX
    py src\\hlc_live.py --replay 2026-09-29 --market NIFTY    (text replay of a recent day)

Live: builds the morning plan (ATM, levels, labels), then after every 5-minute
candle fetches the index and option candles and feeds them to hlc_engine.HlcDay.
Dashboard: http://127.0.0.1:8052 (NIFTY) / 8053 (SENSEX). Logs to
data/paper_trades/, permanent record in history/hlc/.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from datetime import date, datetime, time, timedelta
from typing import Optional

from dotenv import load_dotenv

from dashboard import start_dashboard
from hlc_engine import HlcDay, HlcTrade
from hlc_history import HLC_HISTORY_DIR, record_hlc_day
from hlc_signal import HLC_MARKETS, Candle, HlcLevels, choose_atm, hlc_levels, leg_label
from kite_auth import PROJECT_ROOT, connected_client
from sniper_live import (CANDLE_MINUTES, MARKET_OPEN, Notifier, OptionChain, _historical, _keep_dashboard_open,
                         _naive, _next_poll, _sleep_until, wait_for_closing_prices)
from sniper_signal import MARKETS

DASHBOARD_PORTS = {"NIFTY": 8052, "SENSEX": 8053}
PAGE = PROJECT_ROOT / "src" / "hlc_dashboard.html"
EXIT_AFTER = time(15, 5)
NO_DATA_GIVE_UP = time(9, 45)


# --- Morning plan -------------------------------------------------------------


def previous_day_candle(kite, token: int, day: date) -> tuple[date, dict]:
    start = datetime.combine(day - timedelta(days=14), time(0, 0))
    end = datetime.combine(day - timedelta(days=1), time(23, 59))
    candles = [c for c in _historical(kite, token, start, end, "day") if _naive(c["date"]).date() < day]
    if not candles:
        raise SystemExit(f"No daily candles before {day} for instrument {token}")
    return _naive(candles[-1]["date"]).date(), candles[-1]


def morning_plan(kite, day: date, market_name: str):
    market = HLC_MARKETS[market_name]
    chain = OptionChain(kite, day, MARKETS[market_name])
    prev_day, idx = previous_day_candle(kite, MARKETS[market_name].index_token, day)
    cache: dict[tuple[float, str], Optional[dict]] = {}

    def daily(strike, option_type):
        if (strike, option_type) not in cache:
            contract = chain.by_key.get((float(strike), option_type))
            cache[(strike, option_type)] = previous_day_candle(kite, contract["instrument_token"], day)[1] if contract else None
        return cache[(strike, option_type)]

    atm = choose_atm(idx["close"], market.strike_step, lambda k, t: (daily(k, t) or {}).get("close"))
    if atm is None:
        raise SystemExit("Could not find an ATM strike with both CE and PE listed near yesterday's close")
    ce, pe = daily(atm, "CE"), daily(atm, "PE")
    levels = hlc_levels(idx["close"], atm, ce["close"], pe["close"])
    return chain, prev_day, idx, levels, ce, pe


def info_lines(levels: HlcLevels, yesterday: dict[str, tuple[float, float, float]]) -> list[str]:
    """Owner's reading of the labels - information only (PROJECT_STATUS.md)."""
    lines = []
    for side in ("CE", "PE"):
        high, low, close = yesterday[side]
        label = leg_label(high, low, close)
        if label == "PROFIT BOOKING":
            lines.append(f"{side} {levels.atm:g} = PROFIT BOOKING (H {high:g}, L {low:g}, C {close:g}) - a trade on this side "
                         f"tends to head back towards yesterday's high {high:g}")
        else:
            lines.append(f"{side} {levels.atm:g} = PANIC (H {high:g}, L {low:g}, C {close:g}) - fast moves on this side; "
                         f"above {high:g} today blocks the other side")
    if leg_label(*yesterday["CE"]) != leg_label(*yesterday["PE"]):
        lines.append("★ Buyer's day: one side PROFIT BOOKING, the other PANIC")
    return lines


# --- Dashboard state ----------------------------------------------------------


class HlcState:
    def __init__(self, market: str, mode: str, day: str, quantity: int):
        self._lock = threading.Lock()
        self._data = {"strategy": "HLC", "market": market, "mode": mode, "day": day, "quantity": quantity,
                      "status": "Starting...", "plan": None, "info": [], "blocked": {}, "candles": [], "trades": [],
                      "log": [], "updated": ""}

    def _set(self, **values) -> None:
        with self._lock:
            self._data.update(values)
            self._data["updated"] = datetime.now().strftime("%H:%M:%S")

    def set_status(self, status: str) -> None:
        self._set(status=status)

    def log(self, message: str) -> None:
        with self._lock:
            self._data["log"].append({"time": datetime.now().strftime("%H:%M:%S"), "text": message})

    def set_plan(self, levels: HlcLevels, prev_day: str, expiry: str, yesterday: dict, symbols: dict[str, str]) -> None:
        self._set(plan={"close": levels.close, "atm": levels.atm, "prev_day": prev_day, "expiry": expiry,
                        "levels": [{"name": n, "value": v} for n, v in reversed(levels.ladder())],
                        "yesterday": {s: {"high": h, "low": l, "close": c, "label": leg_label(h, l, c)}
                                      for s, (h, l, c) in yesterday.items()},
                        "symbols": symbols},
                  info=info_lines(levels, yesterday))

    def add_candle(self, when: datetime, index: Candle, ce: Optional[Candle], pe: Optional[Candle]) -> None:
        with self._lock:
            self._data["candles"].append({"time": when.strftime("%H:%M"), "index": index.close,
                                          "ce": ce.close if ce else None, "pe": pe.close if pe else None})

    def set_engine(self, engine: HlcDay) -> None:
        trades = [{**t.__dict__, "targets": [list(x) for x in t.targets],
                   "trail_level": list(t.trail_level) if t.trail_level else None} for t in engine.trades]
        self._set(trades=trades, blocked=dict(engine.blocked), big_gap=engine.big_gap)

    def to_json(self) -> bytes:
        with self._lock:
            return json.dumps(self._data).encode("utf-8")


# --- Candle feeding -----------------------------------------------------------


def _series(rows: list[dict]) -> dict[datetime, Candle]:
    return {_naive(r["date"]): Candle(r["open"], r["high"], r["low"], r["close"]) for r in rows}


def _strikes_to_watch(levels: HlcLevels, step: int, index_price: float) -> set[float]:
    """The morning ATM, plus the round strikes around the market (needed on a big-gap day)."""
    nearest = round(index_price / step) * step
    return {float(levels.atm)} | {float(nearest + i * step) for i in (-1, 0, 1)}


def feed(engine: HlcDay, index_rows: list[dict], premiums: dict[tuple[float, str], dict[datetime, Candle]],
         processed: set[datetime], now: datetime, state: Optional[HlcState], notify: Optional[Notifier],
         late_before: Optional[datetime] = None) -> list[str]:
    """Feeds every fully closed, unprocessed index candle to the engine, in order."""
    all_events = []
    for row in index_rows:
        when = _naive(row["date"])
        if when in processed or when + timedelta(minutes=CANDLE_MINUTES) > now:
            continue
        processed.add(when)
        index = Candle(row["open"], row["high"], row["low"], row["close"])
        chain_now = {key: series[when] for key, series in premiums.items() if when in series}
        events = engine.on_candle(when, index, chain_now)
        if state:
            state.add_candle(when, index, chain_now.get((engine.levels.atm, "CE")), chain_now.get((engine.levels.atm, "PE")))
        late = late_before is not None and when + timedelta(minutes=CANDLE_MINUTES) < late_before
        for event in events:
            text = f"[{when:%H:%M} candle] {event}" + ("  (catch-up)" if late else "")
            all_events.append(text)
            if notify:
                notify.send(text)
        if engine.done:
            break
    return all_events


def _fetch(kite, chain: OptionChain, market_name: str, levels: HlcLevels, start: datetime, end: datetime):
    index_rows = _historical(kite, MARKETS[market_name].index_token, start, end, f"{CANDLE_MINUTES}minute")
    if not index_rows:
        return index_rows, {}
    step = HLC_MARKETS[market_name].strike_step
    premiums = {}
    for strike in _strikes_to_watch(levels, step, index_rows[-1]["close"]):
        for option_type in ("CE", "PE"):
            contract = chain.by_key.get((strike, option_type))
            if contract:
                premiums[(strike, option_type)] = _series(
                    _historical(kite, contract["instrument_token"], start, end, f"{CANDLE_MINUTES}minute"))
    return index_rows, premiums


# --- Live ---------------------------------------------------------------------


def live(market_name: str, open_browser: bool) -> None:
    market = HLC_MARKETS[market_name]
    day = date.today()
    if day.weekday() >= 5:
        raise SystemExit("Today is a weekend - no market.")
    kite = connected_client()
    state = HlcState(market_name, "LIVE", day.isoformat(), market.quantity)
    url = start_dashboard(state, DASHBOARD_PORTS[market_name], PAGE, HLC_HISTORY_DIR)
    print(f"HLC dashboard: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    notify = Notifier(day, state, prefix=f"HLC_{market_name}_log")
    notify.send(f"HLC bot started ({market_name}, {market.quantity} qty) - PAPER MODE, no real orders.", phone=False)

    wait_for_closing_prices(market_name, state.set_status)
    state.set_status("Building the morning plan from yesterday's closing prices...")
    chain, prev_day, idx, levels, ce, pe = morning_plan(kite, day, market_name)
    yesterday = {"CE": (ce["high"], ce["low"], ce["close"]), "PE": (pe["high"], pe["low"], pe["close"])}
    symbols = {s: chain.by_key[(float(levels.atm), s)]["tradingsymbol"] for s in ("CE", "PE")}
    state.set_plan(levels, prev_day.isoformat(), chain.expiry.isoformat(), yesterday, symbols)
    notify.send(f"HLC PLAN {market_name} - close {levels.close:g} on {prev_day}, ATM {levels.atm:g}, expiry {chain.expiry}\n  "
                + "  ".join(f"{n} {v:g}" for n, v in reversed(levels.ladder())) + "\n  " + "\n  ".join(info_lines(levels, yesterday)))

    engine = HlcDay(day, levels, market, yesterday)

    def record(status: str) -> None:
        try:
            record_hlc_day(day, market_name, levels, yesterday, engine.big_gap, engine.trades, market.quantity, status)
        except Exception as error:  # history must never stop the bot
            print(f"  (history update failed: {error})", flush=True)

    record("watching")
    processed: set[datetime] = set()
    started = datetime.now()
    session_start = datetime.combine(day, MARKET_OPEN)
    status = "finished"
    try:
        while not engine.done:
            if datetime.now().time() >= EXIT_AFTER:
                break
            next_poll = _next_poll(datetime.now())
            state.set_status(f"Waiting for the next candle - checking at {next_poll:%H:%M:%S}")
            _sleep_until(next_poll)
            now = datetime.now()
            try:
                index_rows, premiums = _fetch(kite, chain, market_name, levels, session_start, now)
            except Exception as error:  # never let a data error end the day
                notify.send(f"Zerodha data fetch failed ({type(error).__name__}: {error}) - retrying at the next candle.",
                            phone=False)
                continue
            if not index_rows and now.time() >= NO_DATA_GIVE_UP:
                notify.send("No index candles today - market holiday? Stopping.")
                break
            events = feed(engine, index_rows, premiums, processed, now, state, notify, late_before=started)
            state.set_engine(engine)
            if events:
                record("watching")
            state.set_status(f"Last candle {max(processed):%H:%M} processed" if processed else "Waiting for 09:15 data")
    except KeyboardInterrupt:
        status = "stopped early (Ctrl+C)"
    open_trade = engine.open_trade
    if open_trade is not None and open_trade.exit_reason == "":
        notify.send(f"Bot stopped with an open {open_trade.side} {open_trade.strike:g} trade - no exit recorded", phone=False)
    record(status)
    total = sum(t.pnl_points for t in engine.trades if t.exit_reason)
    state.set_engine(engine)
    state.set_status(f"Day finished: {len(engine.trades)} paper trade(s), P&L {total:+.2f} points = Rs {total * market.quantity:+,.0f}")
    notify.send(f"HLC day finished: {len(engine.trades)} paper trade(s), P&L {total:+.2f} points = Rs {total * market.quantity:+,.0f}")
    _keep_dashboard_open(url)


# --- Replay -------------------------------------------------------------------


def replay(day: date, market_name: str, record: bool = False, dashboard: bool = False) -> None:
    """Text replay of a recent day. record=True writes the result to history/hlc/ (e.g. a day the live bot
    didn't run); dashboard=True also serves it on the HLC dashboard and keeps it open."""
    kite = connected_client()
    market = HLC_MARKETS[market_name]
    chain, prev_day, idx, lv, ce, pe = morning_plan(kite, day, market_name)
    yesterday = {"CE": (ce["high"], ce["low"], ce["close"]), "PE": (pe["high"], pe["low"], pe["close"])}
    print(f"HLC PLAN {market_name} {day} (PAPER) - close {idx['close']} on {prev_day}, expiry {chain.expiry}")
    print("  " + "  ".join(f"{n} {v:g}" for n, v in reversed(lv.ladder())))
    for line in info_lines(lv, yesterday):
        print("  " + line)

    start, end = datetime.combine(day, time(9, 15)), datetime.combine(day, time(15, 30))
    index = _historical(kite, MARKETS[market_name].index_token, start, end, "5minute")
    if not index:
        raise SystemExit(f"No index candles for {day}")
    step = market.strike_step
    lo = int(min(c["low"] for c in index) // step - 2) * step
    hi = int(max(c["high"] for c in index) // step + 3) * step
    premiums: dict[tuple[float, str], dict[datetime, Candle]] = {}
    for strike in sorted({float(s) for s in range(lo, hi + step, step)} | {float(lv.atm)}):
        for option_type in ("CE", "PE"):
            contract = chain.by_key.get((strike, option_type))
            if contract:
                premiums[(strike, option_type)] = _series(_historical(kite, contract["instrument_token"], start, end, "5minute"))

    engine = HlcDay(day, lv, market, yesterday)
    state = None
    if dashboard:
        state = HlcState(market_name, "REPLAY", day.isoformat(), market.quantity)
        symbols = {s: chain.by_key[(float(lv.atm), s)]["tradingsymbol"] for s in ("CE", "PE")}
        state.set_plan(lv, prev_day.isoformat(), chain.expiry.isoformat(), yesterday, symbols)
    for event in feed(engine, index, premiums, set(), end + timedelta(minutes=10), state, None):
        print(event)
        if state:
            state.log(event)
    total = sum(t.pnl_points for t in engine.trades if t.exit_reason)
    summary = (f"{len(engine.trades)} trade(s), {total:+.2f} points = Rs {total * market.quantity:+,.0f} "
               f"({market.quantity} qty, paper, before charges)")
    print("\n" + summary)
    if record:
        record_hlc_day(day, market_name, lv, yesterday, engine.big_gap, engine.trades, market.quantity, "replayed",
                       note="Replayed on the day's real candles after the close (the live HLC bot wasn't running).")
        print(f"Recorded in {HLC_HISTORY_DIR}")
    if state:
        state.set_engine(engine)
        state.set_status(f"Replay of {day}: {summary}")
        url = start_dashboard(state, DASHBOARD_PORTS[market_name], PAGE, HLC_HISTORY_DIR)
        print(f"HLC dashboard: {url}", flush=True)
        _keep_dashboard_open(url)


def main() -> None:
    parser = argparse.ArgumentParser(description="HLC strategy - paper mode on Zerodha data (no orders).")
    parser.add_argument("--market", choices=sorted(HLC_MARKETS), default="NIFTY")
    parser.add_argument("--replay", metavar="YYYY-MM-DD", help="text replay of a recent trading day")
    parser.add_argument("--no-browser", action="store_true", help="don't open the dashboard automatically")
    parser.add_argument("--record", action="store_true", help="replay: write the result to history/hlc/")
    parser.add_argument("--dashboard", action="store_true", help="replay: show it on the HLC dashboard")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(PROJECT_ROOT / ".env")
    if args.replay:
        replay(date.fromisoformat(args.replay), args.market, args.record, args.dashboard)
    else:
        live(args.market, not args.no_browser)


if __name__ == "__main__":
    main()
