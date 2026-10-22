"""
Vengat BEP (#5, owner 2026-10-22) - break-even-point support / resistance levels. PAPER / information only.

Owner's rule (22-10, Sniper concept):
  * ATM = yesterday's index close rounded to the strike step.
  * Resistance ladder: each OTM CE strike K (ATM + 1 step, + 2 steps, ...) -> K + (yesterday's close of K CE) / 2
  * Support ladder:    each OTM PE strike K (ATM - 1 step, - 2 steps, ...) -> K - (yesterday's close of K PE) / 2
  * Each next strike's BEP gives the next support / resistance.
Entry / SL / target rules: not given yet - this file only computes the levels.

    py src\\bep_levels.py                 levels for the next session (from the last trading day's closes)
    py src\\bep_levels.py --day 2026-10-22 levels built from that day's closes
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

MARKETS = {"NIFTY": {"token": 256265, "exchange": "NFO", "step": 50}}
LEVELS = 5  # strikes each side


def _day_close(kite, token: int, day: date) -> float | None:
    rows = kite.historical_data(token, datetime.combine(day, datetime.min.time()),
                                datetime.combine(day, datetime.max.time()), "day")
    return rows[-1]["close"] if rows else None


def levels(kite, market: str, day: date) -> dict:
    m = MARKETS[market]
    spot = _day_close(kite, m["token"], day)
    if spot is None:
        raise RuntimeError(f"no {market} close on {day}")
    atm = round(spot / m["step"]) * m["step"]
    chain = [i for i in kite.instruments(m["exchange"]) if i["name"] == market and i["expiry"] > day]
    expiry = min(i["expiry"] for i in chain)
    token = {(i["strike"], i["instrument_type"]): i["instrument_token"] for i in chain if i["expiry"] == expiry}
    out = {"market": market, "day": day, "close": spot, "atm": atm, "expiry": expiry, "R": [], "S": []}
    for n in range(1, LEVELS + 1):
        for side, kind, sign in (("R", "CE", 1), ("S", "PE", -1)):
            strike = atm + sign * n * m["step"]
            c = _day_close(kite, token[(strike, kind)], day) if (strike, kind) in token else None
            if c is not None:
                out[side].append((n, strike, kind, c, round(strike + sign * c / 2, 2)))
    return out


def report(lv: dict) -> str:
    lines = [f"Vengat BEP {lv['market']} - from {lv['day']} closes: index {lv['close']:g}, ATM {lv['atm']:g}, "
             f"expiry {lv['expiry']}"]
    for n, strike, kind, c, level in reversed(lv["R"]):
        lines.append(f"  R{n}  {strike:g} {kind} close {c:8.2f}  ->  {level:,.2f}")
    lines.append(f"  --  ATM {lv['atm']:g}  (close {lv['close']:g})")
    for n, strike, kind, c, level in lv["S"]:
        lines.append(f"  S{n}  {strike:g} {kind} close {c:8.2f}  ->  {level:,.2f}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", help="YYYY-MM-DD: the day whose closes build the levels (default: last trading day)")
    ap.add_argument("--market", default="NIFTY", choices=sorted(MARKETS))
    a = ap.parse_args()
    from dotenv import load_dotenv
    from kite_auth import connected_client
    load_dotenv(ROOT / ".env")
    kite = connected_client()
    day = date.fromisoformat(a.day) if a.day else None
    if day is None:
        rows = kite.historical_data(MARKETS[a.market]["token"], datetime.now() - timedelta(days=10), datetime.now(), "day")
        day = max(r["date"].date() for r in rows if r["date"].date() < date.today() or datetime.now().hour >= 16)
    print(report(levels(kite, a.market, day)))
