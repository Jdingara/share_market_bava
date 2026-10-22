"""
Vengat ORB - live paper bot on Zerodha data (owner, 2026-10-19). PAPER MODE - no orders are placed.

    py src\\orb_live.py --market NIFTY            (dashboard http://127.0.0.1:8054)
    py src\\orb_live.py --market SENSEX           (dashboard http://127.0.0.1:8055)
    py src\\orb_live.py --market NIFTY --replay 2026-10-16 [--record]
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
from hlc_signal import Candle
from keep_awake import keep_awake
from kite_auth import PROJECT_ROOT, connected_client
from orb_engine import MAX_TRADES, ORB_MARKETS, OrbDay
from orb_history import ORB_HISTORY_DIR, record_orb_day
from sniper_live import (CANDLE_MINUTES, MARKET_OPEN, Notifier, OptionChain, _historical, _keep_dashboard_open, _naive,
                         _next_poll, _sleep_until)
from sniper_signal import MARKETS

DASHBOARD_PORTS = {"NIFTY": 8054, "SENSEX": 8055}
PAGE = PROJECT_ROOT / "src" / "orb_dashboard.html"
EXIT_AFTER = time(15, 25)
NO_DATA_GIVE_UP = time(9, 45)


class OrbState:
    def __init__(self, market: str, mode: str, day: str):
        self._lock = threading.Lock()
        self._data = {"strategy": "Vengat ORB", "market": market, "mode": mode, "day": day, "status": "Starting...",
                      "range": None, "expiry": "", "candles": [], "trades": [], "log": [], "updated": ""}

    def _set(self, **values) -> None:
        with self._lock:
            self._data.update(values)
            self._data["updated"] = datetime.now().strftime("%H:%M:%S")

    def set_status(self, status: str) -> None:
        self._set(status=status)

    def log(self, message: str) -> None:
        with self._lock:
            self._data["log"].append({"time": datetime.now().strftime("%H:%M:%S"), "text": message})

    def add_candle(self, when: datetime, index: Candle) -> None:
        with self._lock:
            self._data["candles"].append({"time": when.strftime("%H:%M"), "index": index.close})

    def set_engine(self, engine: OrbDay) -> None:
        self._set(range={"high": engine.high, "low": engine.low} if engine.high is not None else None,
                  trades=[{**t.__dict__, "pnl_rupees": t.pnl_rupees} for t in engine.trades])

    def to_json(self) -> bytes:
        with self._lock:
            return json.dumps(self._data).encode("utf-8")


def _series(rows: list[dict]) -> dict[datetime, Candle]:
    return {_naive(r["date"]): Candle(r["open"], r["high"], r["low"], r["close"]) for r in rows}


def _fetch(kite, chain: OptionChain, market_name: str, start: datetime, end: datetime):
    """The index candles and the CE/PE candles of every strike the index has been near today."""
    index_rows = _historical(kite, MARKETS[market_name].index_token, start, end, f"{CANDLE_MINUTES}minute")
    if not index_rows:
        return index_rows, {}
    step = ORB_MARKETS[market_name].strike_step
    lo = int(min(r["low"] for r in index_rows) // step - 1) * step
    hi = int(max(r["high"] for r in index_rows) // step + 2) * step
    premiums = {}
    for strike in range(lo, hi + step, step):
        for side in ("CE", "PE"):
            contract = chain.by_key.get((float(strike), side))
            if contract:
                premiums[(float(strike), side)] = _series(
                    _historical(kite, contract["instrument_token"], start, end, f"{CANDLE_MINUTES}minute"))
    return index_rows, premiums


def feed(engine: OrbDay, index_rows, premiums, processed: set, now: datetime, state: Optional[OrbState],
         notify: Optional[Notifier], late_before: Optional[datetime] = None) -> list[str]:
    out = []
    for row in index_rows:
        when = _naive(row["date"])
        if when in processed or when + timedelta(minutes=CANDLE_MINUTES) > now:
            continue
        processed.add(when)
        index = Candle(row["open"], row["high"], row["low"], row["close"])
        chain = {key: series[when] for key, series in premiums.items() if when in series}
        events = engine.on_candle(when, index, chain)
        if state:
            state.add_candle(when, index)
        late = late_before is not None and when + timedelta(minutes=CANDLE_MINUTES) < late_before
        for event in events:
            text = f"[{when:%H:%M} candle] {event}" + ("  (catch-up)" if late else "")
            out.append(text)
            if notify:
                notify.send(text)
        if engine.done:
            break
    return out


def live(market_name: str, open_browser: bool) -> None:
    market = ORB_MARKETS[market_name]
    day = date.today()
    if day.weekday() >= 5:
        raise SystemExit("Today is a weekend - no market.")
    kite = connected_client()
    state = OrbState(market_name, "LIVE", day.isoformat())
    url = start_dashboard(state, DASHBOARD_PORTS[market_name], PAGE, ORB_HISTORY_DIR)
    print(f"Vengat ORB dashboard: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    notify = Notifier(day, state, prefix=f"ORB_{market_name}_log")
    notify.send(f"Vengat ORB started ({market_name}, qty {market.lot} per trade, max {MAX_TRADES} trades) - PAPER MODE, "
                f"no real orders.", phone=False)
    chain = OptionChain(kite, day, MARKETS[market_name])
    state._set(expiry=chain.expiry.isoformat())
    engine = OrbDay(day, market)

    def record(status: str) -> None:
        try:
            record_orb_day(day, market_name, engine, status)
        except Exception as error:  # history must never stop the bot
            print(f"  (history update failed: {error})", flush=True)

    processed: set[datetime] = set()
    started = datetime.now()
    session_start = datetime.combine(day, MARKET_OPEN)
    status = "finished"
    tried_after_close = False
    try:
        while not engine.done:
            if datetime.now().time() >= EXIT_AFTER:
                if processed or tried_after_close:
                    break
                tried_after_close = True  # started after the close - replay the whole day once
            else:
                next_poll = _next_poll(datetime.now())
                state.set_status(f"Waiting for the next candle - checking at {next_poll:%H:%M:%S}")
                _sleep_until(next_poll)
            now = datetime.now()
            try:
                index_rows, premiums = _fetch(kite, chain, market_name, session_start, now)
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
    record(status)
    state.set_engine(engine)
    points, rupees = engine.total()
    summary = f"Vengat ORB day finished: {len(engine.trades)} paper trade(s), {points:+.2f} points = Rs {rupees:+,.0f}"
    state.set_status(summary)
    notify.send(summary)
    _keep_dashboard_open(url)


def replay(day: date, market_name: str, record: bool = False) -> None:
    kite = connected_client()
    market = ORB_MARKETS[market_name]
    chain = OptionChain(kite, day, MARKETS[market_name])
    start, end = datetime.combine(day, time(9, 15)), datetime.combine(day, time(15, 30))
    index_rows, premiums = _fetch(kite, chain, market_name, start, end)
    if not index_rows:
        raise SystemExit(f"No index candles for {day}")
    engine = OrbDay(day, market)
    print(f"Vengat ORB replay {market_name} {day} (PAPER), expiry {chain.expiry}")
    for event in feed(engine, index_rows, premiums, set(), end + timedelta(minutes=10), None, None):
        print(event)
    points, rupees = engine.total()
    print(f"\n{len(engine.trades)} trade(s), {points:+.2f} points = Rs {rupees:+,.0f} (fixed qty, before charges)")
    if record:
        record_orb_day(day, market_name, engine, "replayed", note="Replayed on the day's real candles after the close.")
        print(f"Recorded in {ORB_HISTORY_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Vengat ORB - paper mode on Zerodha data (no orders).")
    parser.add_argument("--market", choices=sorted(ORB_MARKETS), default="NIFTY")
    parser.add_argument("--replay", metavar="YYYY-MM-DD", help="text replay of a recent trading day")
    parser.add_argument("--record", action="store_true", help="replay: write the result to history/orb/")
    parser.add_argument("--no-browser", action="store_true", help="don't open the dashboard automatically")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(PROJECT_ROOT / ".env")
    if args.replay:
        replay(date.fromisoformat(args.replay), args.market, args.record)
    else:
        keep_awake()
        live(args.market, not args.no_browser)


if __name__ == "__main__":
    main()
