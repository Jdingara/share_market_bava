"""
GIFT Nifty morning check (owner, 2026-10-22): yesterday's 15:30 GIFT Nifty value vs the value now.

    py src\\gift_nifty.py --snapshot     run at 15:30 (Task Scheduler): saves the GIFT Nifty value
    py src\\gift_nifty.py --report       run in the morning: GIFT now vs yesterday's 15:30 snapshot (and vs the
                                        NIFTY spot close when there's no snapshot yet)

Source: groww.in's GIFT Nifty page (public). Information only - nothing here trades.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "data" / "gift_nifty.csv"
URL = "https://groww.in/indices/global-indices/sgx-nifty"
FLAT = 30  # NIFTY points: a smaller gap counts as a flat open


def fetch() -> dict:
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
    blob = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S).group(1)
    out = {}
    for key in ("value", "close", "open", "high", "low", "dayChange", "tsInMillis"):
        m = re.search(r'"%s":\s*([0-9.\-]+)' % key, blob)
        if m:
            out[key] = float(m.group(1))
    if "value" not in out:
        raise RuntimeError("GIFT Nifty value not found on the page")
    ts = out.get("tsInMillis")
    out["time"] = datetime.fromtimestamp(ts / 1000 if ts and ts > 1e11 else ts).strftime("%Y-%m-%d %H:%M") if ts else ""
    return out


def snapshot() -> None:
    g = fetch()
    FILE.parent.mkdir(parents=True, exist_ok=True)
    new = not FILE.exists()
    with FILE.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "taken_at", "gift_value", "quote_time"])
        w.writerow([date.today().isoformat(), datetime.now().strftime("%H:%M"), g["value"], g["time"]])
    print(f"GIFT Nifty {g['value']:g} saved ({g['time']})")


def last_snapshot() -> tuple[str, float] | None:
    if not FILE.exists():
        return None
    rows = [r for r in csv.DictReader(FILE.open(encoding="utf-8")) if r["date"] < date.today().isoformat()]
    return (rows[-1]["date"], float(rows[-1]["gift_value"])) if rows else None


def nifty_close() -> tuple[str, float] | None:
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from dotenv import load_dotenv
        from kite_auth import connected_client
        load_dotenv(ROOT / ".env")
        rows = connected_client().historical_data(256265, datetime(date.today().year, 1, 1),
                                                  datetime.combine(date.today(), datetime.min.time()), "day")
        rows = [r for r in rows if r["date"].date() < date.today()]
        return rows[-1]["date"].date().isoformat(), rows[-1]["close"]
    except Exception:
        return None


def report() -> str:
    """Owner, 22-10: take the GIFT Nifty move since yesterday 15:30 (GIFT now - GIFT at 15:30) and add those points to
    OUR NIFTY close -> the expected NIFTY open; that says GAP UP / GAP DOWN / FLAT. (Comparing GIFT with the NIFTY
    spot directly would mix in the futures premium.)"""
    g = fetch()
    lines = [f"GIFT Nifty now {g['value']:,.2f} (quote {g['time']})"]
    snap = last_snapshot()
    if snap:
        d, v = snap
        diff = g["value"] - v
        lines.append(f"  GIFT at 15:30 on {d}: {v:,.2f}  ->  GIFT difference {diff:+,.2f} points")
    elif "dayChange" in g:
        diff = g["dayChange"]  # no 15:30 snapshot yet - GIFT's own change since its previous close (approximate)
        lines.append(f"  (no 15:30 snapshot yet) GIFT change since its previous close {g.get('close', 0):,.2f}: {diff:+,.2f} points")
    else:
        diff = None
    nc = nifty_close()
    if nc and diff is not None:
        d, c = nc
        expected = c + diff
        verdict = "GAP UP" if diff > FLAT else "GAP DOWN" if diff < -FLAT else "FLAT"
        lines.append(f"  NIFTY close on {d}: {c:,.2f}  +  {diff:+,.2f}  =  expected NIFTY open about {expected:,.2f}")
        lines.append(f"  => {verdict} (about {diff:+,.0f} points; flat band +-{FLAT:g})")
    text = "
".join(lines)
    out = ROOT / "data" / "paper_trades" / f"gift_nifty_{date.today().isoformat()}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "
", encoding="utf-8")
    return text


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.snapshot:
        snapshot()
    else:
        print(report())
