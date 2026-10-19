"""
Lalitha (strategy #4) - live paper bot on Zerodha data. PAPER MODE - no orders are placed.

    py src\\lalitha_live.py --market NIFTY        (dashboard :8056; SENSEX :8057; BANKNIFTY :8058)
    py src\\lalitha_live.py --market BANKNIFTY --replay 2026-10-16 [--record]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time as time_module
import webbrowser
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from dashboard import start_dashboard
from history import _read, _write, folder_lock
from keep_awake import keep_awake
from kite_auth import PROJECT_ROOT, connected_client
from lalitha_engine import CANDLE, LalithaDay
from lalitha_indicators import Bar
from sniper_live import Notifier, OptionChain, _historical, _keep_dashboard_open, _naive


@dataclass(frozen=True)
class LalithaMarket:
    name: str
    index_token: int
    options_exchange: str
    strike_step: int
    lots: int


MARKETS = {
    "NIFTY": LalithaMarket("NIFTY", 256265, "NFO", 50, 4),
    "SENSEX": LalithaMarket("SENSEX", 265, "BFO", 100, 10),
    "BANKNIFTY": LalithaMarket("BANKNIFTY", 260105, "NFO", 100, 6),
}
PORTS = {"NIFTY": 8056, "SENSEX": 8057, "BANKNIFTY": 8058}
PAGE = PROJECT_ROOT / "src" / "lalitha_dashboard.html"
HISTORY_DIR = PROJECT_ROOT / "history" / "lalitha"
INTERVAL = "3minute"
STRIKES_EACH_SIDE = 12


class State:
    def __init__(self, market: str, mode: str, day: str):
        self._lock = threading.Lock()
        self._data = {"strategy": "Lalitha", "market": market, "mode": mode, "day": day, "status": "Starting...",
                      "pivot": None, "indicators": None, "trades": [], "log": [], "expiry": "", "qty": 0, "updated": ""}

    def set(self, **values) -> None:
        with self._lock:
            self._data.update(values)
            self._data["updated"] = datetime.now().strftime("%H:%M:%S")

    def log(self, message: str) -> None:
        with self._lock:
            self._data["log"].append({"time": datetime.now().strftime("%H:%M:%S"), "text": message})

    def to_json(self) -> bytes:
        with self._lock:
            return json.dumps(self._data).encode("utf-8")


def _bars(rows: list[dict]) -> list[tuple[datetime, Bar]]:
    return [(_naive(r["date"]), Bar(r["open"], r["high"], r["low"], r["close"])) for r in rows]


class Premiums:
    """Option 3-minute closes, fetched only when needed (a signal or an open trade), cached per poll."""

    def __init__(self, kite, chain: OptionChain, day: date):
        self.kite, self.chain, self.day = kite, chain, day
        self.cache: dict[tuple[float, str], dict[datetime, float]] = {}
        self.until: Optional[datetime] = None

    def reset(self, until: datetime) -> None:
        self.cache, self.until = {}, until

    def at(self, strike: float, side: str, when: datetime) -> Optional[float]:
        key = (float(strike), side)
        if key not in self.cache:
            contract = self.chain.by_key.get(key)
            if contract is None:
                self.cache[key] = {}
            else:
                start = datetime.combine(self.day, time(9, 15))
                rows = _historical(self.kite, contract["instrument_token"], start, self.until, INTERVAL)
                self.cache[key] = {_naive(r["date"]): r["close"] for r in rows}
        return self.cache[key].get(when)


def _setup(kite, market: LalithaMarket, day: date):
    chain = OptionChain(kite, day, market)
    lot = next(iter(chain.by_key.values()))["lot_size"]
    daily = [r for r in _historical(kite, market.index_token, datetime.combine(day - timedelta(days=10), time(0, 0)),
                                    datetime.combine(day - timedelta(days=1), time(23, 59)), "day")
             if _naive(r["date"]).date() < day]
    y = daily[-1]
    warm_rows = _historical(kite, market.index_token, datetime.combine(day - timedelta(days=6), time(9, 15)),
                            datetime.combine(day - timedelta(days=1), time(15, 30)), INTERVAL)
    warmup = [b for _, b in _bars(warm_rows)]
    engine = LalithaDay(day, market.lots * lot, (y["high"], y["low"], y["close"]), warmup)
    return chain, lot, engine, y


def _candidates(chain: OptionChain, market: LalithaMarket, index_close: float):
    atm = round(index_close / market.strike_step) * market.strike_step
    strikes = [float(atm + i * market.strike_step) for i in range(-STRIKES_EACH_SIDE, STRIKES_EACH_SIDE + 1)]
    return lambda side: [k for k in strikes if (k, side) in chain.by_key]


def feed(engine: LalithaDay, rows, prem: Premiums, chain, market, processed: set, now: datetime, notify, state,
         late_before=None) -> list[str]:
    out = []
    for when, bar in _bars(rows):
        if when in processed or when + CANDLE > now:
            continue
        processed.add(when)
        events = engine.on_candle(when, bar, lambda k, s, w=when: prem.at(k, s, w), _candidates(chain, market, bar.close))
        late = late_before is not None and when + CANDLE < late_before
        for e in events:
            text = f"[{when:%H:%M} candle] {e}" + ("  (catch-up)" if late else "")
            out.append(text)
            if notify:
                notify.send(text)
        if engine.done:
            break
    if state is not None and engine.bars:
        ind = engine.indicators()
        st, r, bb = ind["st"], ind["rsi"], ind["bb"]
        state.set(indicators={"supertrend": round(st[0], 2) if st[0] else None, "direction": st[1],
                              "rsi": round(r, 1) if r else None, "bb": [round(x, 2) for x in bb] if bb else None,
                              "close": engine.bars[-1].close},
                  trades=[{**t.__dict__, "pnl_rupees": t.pnl_rupees} for t in engine.trades])
    return out


def record(day: date, market: str, engine: LalithaDay, status: str, note: str = "") -> None:
    fields_d = ["date", "market", "pivot", "r1", "s1", "trades", "pnl_points", "pnl_rupees", "status", "last_update", "note"]
    fields_t = ["date", "market", "side", "strike", "qty", "entry_time", "entry_fill", "entry_index", "exit_time",
                "exit_premium", "exit_index", "exit_reason", "pnl_points", "pnl_rupees", "entry_reason"]
    with folder_lock(HISTORY_DIR):
        pts, rs = engine.total()
        key = (day.isoformat(), market)
        drow = {"date": day.isoformat(), "market": market, "pivot": round(engine.pivot["P"], 2),
                "r1": round(engine.pivot["R1"], 2), "s1": round(engine.pivot["S1"], 2), "trades": len(engine.trades),
                "pnl_points": pts, "pnl_rupees": round(rs), "status": status,
                "last_update": datetime.now().strftime("%Y-%m-%d %H:%M"), "note": note}
        days = sorted([d for d in _read(HISTORY_DIR / "days.csv") if (d["date"], d["market"]) != key] + [drow],
                      key=lambda d: (d["date"], d["market"]))
        _write(HISTORY_DIR / "days.csv", fields_d, days)
        trows = [{"date": t.date, "market": market, "side": t.side, "strike": f"{t.strike:g}", "qty": t.qty,
                  "entry_time": t.entry_time[11:16], "entry_fill": t.entry_fill, "entry_index": t.entry_index,
                  "exit_time": t.exit_time[11:16], "exit_premium": t.exit_premium if t.exit_reason else "",
                  "exit_index": t.exit_index if t.exit_reason else "", "exit_reason": t.exit_reason or "OPEN",
                  "pnl_points": t.pnl_points if t.exit_reason else "", "pnl_rupees": round(t.pnl_rupees) if t.exit_reason else "",
                  "entry_reason": t.entry_reason} for t in engine.trades]
        trades = sorted([t for t in _read(HISTORY_DIR / "trades.csv") if (t["date"], t["market"]) != key] + trows,
                        key=lambda t: (t["date"], t["market"], t["entry_time"]))
        _write(HISTORY_DIR / "trades.csv", fields_t, trades)
        total = sum(float(d["pnl_rupees"] or 0) for d in days)
        lines = ["# Lalitha (strategy #4) - Trade History", "",
                 "**Paper trades - no real orders.** 3-minute index candles: Supertrend(10,2) + RSI(14) > 70 / < 30 + "
                 "pivot R1 / S1 + Bollinger(20,2) band close -> the CE / PE with premium nearest 250; exit on a Supertrend flip.",
                 "", f"**All days: ₹{total:+,.0f}**", "", "| Date | Market | Trades | P&L ₹ | Status |", "|---|---|---|---|---|"]
        lines += [f"| {d['date']} | {d['market']} | {d['trades']} | ₹{float(d['pnl_rupees'] or 0):+,.0f} | {d['status']} |"
                  for d in reversed(days)]
        for t in reversed(trades):
            lines.append(f"- {t['date']} {t['market']} {t['entry_time']} {t['qty']} x {t['strike']} {t['side']} @ {t['entry_fill']} "
                         f"-> {t['exit_premium'] or 'open'} ({t['exit_reason']}) ₹{t['pnl_rupees'] or '-'}")
        (HISTORY_DIR / "LALITHA_HISTORY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _next_poll(now: datetime) -> datetime:
    minutes = now.hour * 60 + now.minute
    nxt = (minutes // 3 + 1) * 3
    return datetime.combine(now.date(), time(0, 0)) + timedelta(minutes=nxt, seconds=10)


def live(name: str, open_browser: bool) -> None:
    market, day = MARKETS[name], date.today()
    if day.weekday() >= 5:
        raise SystemExit("Weekend - no market.")
    kite = connected_client()
    state = State(name, "LIVE", day.isoformat())
    url = start_dashboard(state, PORTS[name], PAGE, HISTORY_DIR)
    print(f"Lalitha dashboard: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    notify = Notifier(day, state, prefix=f"LALITHA_{name}_log", phone=False)
    chain, lot, engine, y = _setup(kite, market, day)
    state.set(pivot={k: round(v, 2) for k, v in engine.pivot.items()}, expiry=chain.expiry.isoformat(), qty=engine.qty)
    notify.send(f"Lalitha started ({name}, {market.lots} lots x {lot} = {engine.qty}, expiry {chain.expiry}) - PAPER MODE. "
                f"Pivot {engine.pivot['P']:.2f}, R1 {engine.pivot['R1']:.2f}, S1 {engine.pivot['S1']:.2f}", phone=False)
    prem = Premiums(kite, chain, day)
    processed: set[datetime] = set()
    started = datetime.now()
    status = "finished"
    tried = False
    try:
        while not engine.done:
            if datetime.now().time() >= time(15, 25):
                if processed or tried:
                    break
                tried = True
            else:
                nxt = _next_poll(datetime.now())
                state.set(status=f"Waiting for the next 3-minute candle - checking at {nxt:%H:%M:%S}")
                while datetime.now() < nxt:
                    time_module.sleep(min(30.0, max((nxt - datetime.now()).total_seconds(), 0.5)))
            now = datetime.now()
            try:
                rows = _historical(kite, market.index_token, datetime.combine(day, time(9, 15)), now, INTERVAL)
                prem.reset(now)
                events = feed(engine, rows, prem, chain, market, processed, now, notify, state, late_before=started)
            except Exception as error:
                notify.send(f"Zerodha data fetch failed ({type(error).__name__}: {error}) - retrying.", phone=False)
                continue
            if events:
                record(day, name, engine, "watching")
            state.set(status=f"Last candle {max(processed):%H:%M} processed" if processed else "Waiting for 09:15 data")
    except KeyboardInterrupt:
        status = "stopped early (Ctrl+C)"
    record(day, name, engine, status)
    pts, rs = engine.total()
    summary = f"Lalitha day finished: {len(engine.trades)} paper trade(s), {pts:+.2f} points = Rs {rs:+,.0f}"
    state.set(status=summary)
    notify.send(summary, phone=False)
    _keep_dashboard_open(url)


def replay(day: date, name: str, save: bool) -> None:
    market = MARKETS[name]
    kite = connected_client()
    chain, lot, engine, y = _setup(kite, market, day)
    print(f"Lalitha replay {name} {day} (PAPER) - qty {engine.qty}, expiry {chain.expiry}, pivot {engine.pivot['P']:.2f} "
          f"R1 {engine.pivot['R1']:.2f} S1 {engine.pivot['S1']:.2f}")
    end = datetime.combine(day, time(15, 30))
    rows = _historical(kite, market.index_token, datetime.combine(day, time(9, 15)), end, INTERVAL)
    prem = Premiums(kite, chain, day)
    prem.reset(end)
    for e in feed(engine, rows, prem, chain, market, set(), end + timedelta(minutes=5), None, None):
        print(e)
    pts, rs = engine.total()
    print(f"\n{len(engine.trades)} trade(s), {pts:+.2f} points = Rs {rs:+,.0f} (qty {engine.qty}, before charges)")
    if save:
        record(day, name, engine, "replayed", note="Replayed on the day's real candles after the close.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Lalitha (strategy #4) - paper mode on Zerodha data (no orders).")
    parser.add_argument("--market", choices=sorted(MARKETS), default="NIFTY")
    parser.add_argument("--replay", metavar="YYYY-MM-DD")
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
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
