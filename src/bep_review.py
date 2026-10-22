"""
Vengat BEP daily record (owner, 2026-10-22: "idhai daily pathivu seiyyavum"). After the close: build that day's levels
from the previous trading day's closes (same maths as bep_levels.py, ATM = previous close rounded to 100) and record how
the index treated each level - reached or not, first touch, candles closed beyond, how far beyond, how far back.

    py src\\bep_review.py                    today (after 15:30)
    py src\\bep_review.py --day 2026-10-21   any day whose option contracts are still listed on Zerodha

Writes history/bep/days.csv (one row per level, re-running a day replaces its rows) and history/bep/BEP_HISTORY.md.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from bep_levels import MARKETS, VARIANTS, _Closes  # noqa: E402

HISTORY = ROOT / "history" / "bep"
CSV = HISTORY / "days.csv"
FIELDS = ["date", "market", "step", "levels_from", "atm", "level_name", "level", "reached", "first_touch", "closes_beyond",
          "max_beyond", "max_back", "day_open", "day_high", "day_low", "day_close"]
STEPS = 3  # levels each side beyond the ATM's RES / SUP


def ladder(kite, market: str, prev: date, step: int) -> tuple[float, list[tuple[str, float, int]]]:
    m = dict(MARKETS[market], step=step)
    c = _Closes(kite, market, prev)
    spot = c.day_close(m["token"])
    if spot is None:
        raise SystemExit(f"no {market} candle on {prev}")
    atm = round(spot / m["step"]) * m["step"]
    out = []
    for n in range(0, STEPS + 1):
        for sign, label in ((1, "RES"), (-1, "SUP")):
            k = atm + sign * n * m["step"]
            ce, pe = c.option(k + m["step"], "CE"), c.option(k - m["step"], "PE")
            if ce is not None and pe is not None:
                out.append((f"{k:g} {label}", round(k + sign * (ce + pe) / 2, 2), sign))
    return atm, sorted(out, key=lambda x: -x[1])


def review(kite, market: str, day: date, step: int = 100) -> list[dict]:
    m = MARKETS[market]
    rows = kite.historical_data(m["token"], datetime.combine(day - timedelta(days=10), datetime.min.time()),
                                datetime.combine(day - timedelta(days=1), datetime.max.time()), "day")
    prev = max(r["date"].date() for r in rows)
    atm, levels = ladder(kite, market, prev, step)
    c = kite.historical_data(m["token"], datetime.combine(day, datetime.min.time()),
                             datetime.combine(day, datetime.max.time()), "5minute")
    if not c:
        raise SystemExit(f"no {market} candles on {day}")
    hi, lo = max(x["high"] for x in c), min(x["low"] for x in c)
    out = []
    for name, level, sign in levels:
        hits = [i for i, x in enumerate(c) if x["low"] <= level <= x["high"]
                or (i == 0 and (x["open"] > level if sign > 0 else x["open"] < level))]
        row = {"date": day.isoformat(), "market": market, "step": step, "levels_from": prev.isoformat(), "atm": atm,
               "level_name": name, "level": level, "day_open": c[0]["open"], "day_high": hi, "day_low": lo,
               "day_close": c[-1]["close"]}
        if not hits:
            row.update(reached="no", first_touch="", closes_beyond=0,
                       max_beyond=round(-(level - hi) if sign > 0 else -(lo - level), 2), max_back="")
        else:
            after = c[hits[0]:]
            row.update(reached="yes", first_touch=after[0]["date"].strftime("%H:%M"),
                       closes_beyond=sum(1 for x in after if (x["close"] > level if sign > 0 else x["close"] < level)),
                       max_beyond=round((max(x["high"] for x in after) - level) if sign > 0
                                        else (level - min(x["low"] for x in after)), 2),
                       max_back=round((level - min(x["low"] for x in after)) if sign > 0
                                      else (max(x["high"] for x in after) - level), 2))
        out.append(row)
    return out


def save(rows: list[dict]) -> None:
    HISTORY.mkdir(parents=True, exist_ok=True)
    old = list(csv.DictReader(CSV.open(encoding="utf-8"))) if CSV.exists() else []
    for r in old:
        r["step"] = r.get("step") or "100"  # rows written before the 22-10 SENSEX variants were all 100
    keys = {(r["date"], r["market"], str(r["step"])) for r in rows}
    keep = [r for r in old if (r["date"], r["market"], r["step"]) not in keys]
    allrows = sorted(keep + [{k: str(v) for k, v in r.items()} for r in rows],
                     key=lambda r: (r["date"], r["market"], int(r["step"]), -float(r["level"])))
    with CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(allrows)
    write_md(allrows)


def write_md(rows: list[dict]) -> None:
    lines = ["# Vengat BEP - daily record", "",
             "Levels from the previous trading day's closes: SNI(K) = (K+100 CE close + K-100 PE close) / 2; "
             "RES = K + SNI(K), SUP = K - SNI(K); K = ATM, then 100 by 100. Information only - no trades. "
             "Written by `src/bep_review.py`.", "",
             "*beyond* = how far the index went past the level after touching it (negative = missed by); "
             "*back* = how far it came back the other way.", ""]
    days = sorted({(r["date"], r["market"], r["step"]) for r in rows}, key=lambda x: (x[0], x[1], -int(x[2])), reverse=True)
    for d, mk, st in days:
        rs = [r for r in rows if r["date"] == d and r["market"] == mk and r["step"] == st]
        r0 = rs[0]
        lines += [f"## {d} {mk} - strikes every {st} (levels from {r0['levels_from']}, ATM {r0['atm']})",
                  f"Open {r0['day_open']} · High {r0['day_high']} · Low {r0['day_low']} · Close {r0['day_close']}", "",
                  "| Level | Value | Reached | First touch | Closes beyond | Beyond | Back |", "|---|---|---|---|---|---|---|"]
        for r in rs:
            lines.append(f"| {r['level_name']} | {float(r['level']):,.2f} | {r['reached']} | {r['first_touch']} | "
                         f"{r['closes_beyond']} | {r['max_beyond']} | {r['max_back']} |")
        lines.append("")
    (HISTORY / "BEP_HISTORY.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", help="YYYY-MM-DD (default today)")
    ap.add_argument("--market", choices=sorted(MARKETS), help="default: NIFTY and SENSEX")
    a = ap.parse_args()
    from dotenv import load_dotenv
    from kite_auth import connected_client
    load_dotenv(ROOT / ".env")
    kite = connected_client()
    day = date.fromisoformat(a.day) if a.day else date.today()
    for mk, st in [(mk, st) for mk in ([a.market] if a.market else ["NIFTY", "SENSEX"]) for st in VARIANTS[mk]]:
        try:
            rows = review(kite, mk, day, st)
        except SystemExit as error:
            print(f"{mk}: {error}")
            continue
        save(rows)
        print(f"{day} {mk} (every {st}): open {rows[0]['day_open']} high {rows[0]['day_high']} low {rows[0]['day_low']}")
        for r in rows:
            print(f"  {r['level_name']:10s} {r['level']:10,.2f}  reached {r['reached']:3s} {r['first_touch']:5s} "
                  f"beyond {r['max_beyond']}  back {r['max_back']}")
