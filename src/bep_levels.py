"""
Vengat BEP (#5, owner 2026-10-22) - "market edhu varai pogum": break-even-point levels that show how far the index
can travel. NO trades, no SL - information only (owner, 22-10: "ithil SL kidayathu, market edhu varai pogum endru
parpatharkku").

Default (owner's reference: Tamil Stock "Advanced Sniper" video, 22-10), strikes in steps of 100:
  * SNI(K)  = (yesterday's close of K+100 CE + yesterday's close of K-100 PE) / 2   (the Sniper of strike K)
  * Range   = ATM - SNI(ATM)  ...  ATM + SNI(ATM)          (ATM = yesterday's index close rounded to 100)
  * Up      : a break above the range travels towards (ATM+100) + SNI(ATM+100), then (ATM+200) + SNI(ATM+200), ...
  * Down    : a break below travels towards (ATM-100) - SNI(ATM-100), then (ATM-200) - SNI(ATM-200), ...
--mode otm (the owner's first description, 22-10): OTM CE strike + its close / 2 (up), OTM PE strike - its close / 2
(down), strikes in steps of 50 (NIFTY).

    py src\\bep_levels.py                       NIFTY + SENSEX levels for the next session
    py src\\bep_levels.py --day 2026-10-22      levels built from that day's closes
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

MARKETS = {"NIFTY": {"token": 256265, "exchange": "NFO", "step": 100, "otm_step": 50},
           "SENSEX": {"token": 265, "exchange": "BFO", "step": 100, "otm_step": 100}}
LEVELS = 4  # levels each side
# owner 22-10 night: SENSEX is ~3.2x NIFTY, the 100 ladder sits too tight there -> record 100 AND 300 side by side for a
# few weeks, then keep the one that fits (one day, 22-10, is not enough to choose)
VARIANTS = {"NIFTY": [100], "SENSEX": [100, 300]}


class _Closes:
    def __init__(self, kite, market: str, day: date):
        m = MARKETS[market]
        self.kite, self.day = kite, day
        chain = [i for i in kite.instruments(m["exchange"]) if i["name"] == market and i["expiry"] > day]
        self.expiry = min(i["expiry"] for i in chain)
        self.token = {(i["strike"], i["instrument_type"]): i["instrument_token"] for i in chain if i["expiry"] == self.expiry}
        self.cache: dict = {}

    def day_close(self, token: int) -> float | None:
        rows = self.kite.historical_data(token, datetime.combine(self.day, datetime.min.time()),
                                         datetime.combine(self.day, datetime.max.time()), "day")
        return rows[-1]["close"] if rows else None

    def option(self, strike: float, kind: str) -> float | None:
        if (strike, kind) not in self.cache:
            t = self.token.get((strike, kind))
            self.cache[(strike, kind)] = self.day_close(t) if t else None
        return self.cache[(strike, kind)]


def last_trading_day(kite) -> date:
    rows = kite.historical_data(256265, datetime.now() - timedelta(days=10), datetime.now(), "day")
    done = [r["date"].date() for r in rows if r["date"].date() < date.today() or datetime.now().hour >= 16]
    return max(done)


def sniper_levels(kite, market: str, day: date, strike: float | None = None, step: int | None = None) -> str:
    m = dict(MARKETS[market])
    if step:
        m["step"] = step
    c = _Closes(kite, market, day)
    spot = c.day_close(m["token"])
    if spot is None:
        raise SystemExit(f"no {market} candle on {day} (holiday?) - pass a trading day")
    # owner 22-10: like the video's setting - type any strike and its RES / SUP come out
    atm = strike if strike else round(spot / m["step"]) * m["step"]

    def sni(k):
        ce, pe = c.option(k + m["step"], "CE"), c.option(k - m["step"], "PE")
        return None if ce is None or pe is None else (ce + pe) / 2, ce, pe

    lines = [f"Vengat BEP {market} (sniper levels, strikes every {m['step']}) - from {day} closes: index {spot:g}, ATM {atm:g}, expiry {c.expiry}"]
    ups, downs = [], []
    for n in range(1, LEVELS):
        k = atm + n * m["step"]
        s, ce, pe = sni(k)
        if s is not None:
            ups.append(f"  UP {n}   {k:g} + SNI {s:7.2f}  =  {k + s:,.2f}   ({k + m['step']:g} CE {ce:g}, {k - m['step']:g} PE {pe:g})")
        k = atm - n * m["step"]
        s, ce, pe = sni(k)
        if s is not None:
            downs.append(f"  DOWN {n} {k:g} - SNI {s:7.2f}  =  {k - s:,.2f}   ({k + m['step']:g} CE {ce:g}, {k - m['step']:g} PE {pe:g})")
    s, ce, pe = sni(atm)
    lines += list(reversed(ups))
    if s is not None:
        lines.append(f"  {atm:g} RES: {atm + s:,.2f}   |   {atm:g} SUP: {atm - s:,.2f}   (SNI {s:.2f} = "
                     f"({atm + m['step']:g} CE {ce:g} + {atm - m['step']:g} PE {pe:g}) / 2)")
    lines += downs
    return "\n".join(lines)


def otm_levels(kite, market: str, day: date) -> str:
    m = MARKETS[market]
    c = _Closes(kite, market, day)
    spot = c.day_close(m["token"])
    step = m["otm_step"]
    atm = round(spot / step) * step
    lines = [f"Vengat BEP {market} (OTM strike +- close/2) - from {day} closes: index {spot:g}, ATM {atm:g}, expiry {c.expiry}"]
    ups, downs = [], []
    for n in range(1, LEVELS + 2):
        k = atm + n * step
        ce = c.option(k, "CE")
        if ce is not None:
            ups.append(f"  R{n}  {k:g} CE close {ce:8.2f}  ->  {k + ce / 2:,.2f}")
        k = atm - n * step
        pe = c.option(k, "PE")
        if pe is not None:
            downs.append(f"  S{n}  {k:g} PE close {pe:8.2f}  ->  {k - pe / 2:,.2f}")
    return "\n".join(lines + list(reversed(ups)) + [f"  --  ATM {atm:g}"] + downs)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", help="YYYY-MM-DD: the day whose closes build the levels (default: last trading day)")
    ap.add_argument("--market", choices=sorted(MARKETS), help="default: NIFTY and SENSEX")
    ap.add_argument("--mode", default="sniper", choices=("sniper", "otm"))
    ap.add_argument("--strike", type=float, help="sniper mode: build the levels around this strike (default: ATM)")
    a = ap.parse_args()
    from dotenv import load_dotenv
    from kite_auth import connected_client
    load_dotenv(ROOT / ".env")
    kite = connected_client()
    day = date.fromisoformat(a.day) if a.day else last_trading_day(kite)
    markets = [a.market] if a.market else (["NIFTY"] if a.strike else ["NIFTY", "SENSEX"])
    if a.mode == "sniper":
        text = "\n\n".join(sniper_levels(kite, mk, day, a.strike, st) for mk in markets for st in VARIANTS[mk])
    else:
        text = "\n\n".join(otm_levels(kite, mk, day) for mk in markets)
    print(text)
    out = ROOT / "data" / f"bep_levels_{date.today().isoformat()}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
