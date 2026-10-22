"""
Permanent day-by-day record for Vengat ORB, in history/orb/ (committed):

    history/orb/days.csv        one row per day per market: range, result
    history/orb/trades.csv      one row per paper trade (with the entry / exit reason)
    history/orb/ORB_HISTORY.md  readable, newest day first

Written after every entry/exit by orb_live.py. Re-recording a (date, market) replaces it.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

from history import _read, _write, folder_lock
from orb_engine import OrbDay

ORB_HISTORY_DIR = Path(__file__).resolve().parent.parent / "history" / "orb"

DAY_FIELDS = ["date", "market", "range_high", "range_low", "trades", "pnl_points", "pnl_rupees", "status",
              "last_update", "note"]
TRADE_FIELDS = ["date", "market", "side", "strike", "qty", "entry_time", "entry_fill", "entry_index", "sl_index",
                "target_index", "exit_time", "exit_premium", "exit_index", "exit_reason", "pnl_points", "pnl_rupees",
                "entry_reason"]


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def record_orb_day(day: date, market: str, engine: OrbDay, status: str, note: str = "",
                   folder: Optional[Path] = None) -> None:
    folder = folder or ORB_HISTORY_DIR
    with folder_lock(folder):
        points, rupees = engine.total()
        key = (day.isoformat(), market)
        day_row = {"date": day.isoformat(), "market": market, "range_high": engine.high or "", "range_low": engine.low or "",
                   "trades": len(engine.trades), "pnl_points": points, "pnl_rupees": round(rupees), "status": status,
                   "last_update": datetime.now().strftime("%Y-%m-%d %H:%M"), "note": note}
        days = [d for d in _read(folder / "days.csv") if (d["date"], d["market"]) != key] + [day_row]
        days.sort(key=lambda d: (d["date"], d["market"]))
        _write(folder / "days.csv", DAY_FIELDS, days)
        rows = [{"date": t.date, "market": market, "side": t.side, "strike": f"{t.strike:g}", "qty": t.qty,
                 "entry_time": t.entry_time[11:16], "entry_fill": t.entry_fill, "entry_index": t.entry_index,
                 "sl_index": t.sl_index, "target_index": (f"prem {t.target_premium:g}" if getattr(t, "target_premium", 0) else t.target_index), "exit_time": t.exit_time[11:16],
                 "exit_premium": t.exit_premium if t.exit_reason else "", "exit_index": t.exit_index if t.exit_reason else "",
                 "exit_reason": t.exit_reason or "OPEN", "pnl_points": t.pnl_points if t.exit_reason else "",
                 "pnl_rupees": round(t.pnl_rupees) if t.exit_reason else "", "entry_reason": t.entry_reason}
                for t in engine.trades]
        trades = [t for t in _read(folder / "trades.csv") if (t["date"], t["market"]) != key] + rows
        trades.sort(key=lambda t: (t["date"], t["market"], t["entry_time"]))
        _write(folder / "trades.csv", TRADE_FIELDS, trades)
        _write_markdown(folder, days, trades)


def _write_markdown(folder: Path, days: list[dict], trades: list[dict]) -> None:
    total = sum(_num(d["pnl_rupees"]) for d in days)
    lines = ["# Vengat ORB - Trade History", "",
             "**Paper trades - no real orders.** Opening range = the index's 09:15-09:20 candle; a close outside it buys "
             "the ATM CE / PE (NIFTY 2 lots, SENSEX 6 lots), since 22-10: entry on the retest of the first candle's 0.75, SL first candle +-1 (index), target = option premium +40 / +80 then SL steps of 25 / 50. Written by `src/orb_history.py`.", "",
             f"**All days: {sum(int(_num(d['trades'])) for d in days)} trade(s), ₹{total:+,.0f}**", "",
             "| Date | Market | Range | Trades | P&L points | P&L ₹ | Status |", "|---|---|---|---|---|---|---|"]
    for d in sorted(days, key=lambda d: (d["date"], d["market"]), reverse=True):
        lines.append(f"| {d['date']} | {d['market']} | {d['range_low']} - {d['range_high']} | {d['trades']} | "
                     f"{_num(d['pnl_points']):+.2f} | ₹{_num(d['pnl_rupees']):+,.0f} | {d['status']} |")
    for day in sorted({d["date"] for d in days}, reverse=True):
        lines += ["", f"## {day}"]
        for d in [d for d in days if d["date"] == day]:
            day_trades = [t for t in trades if t["date"] == day and t["market"] == d["market"]]
            lines += ["", f"### {d['market']} - range {d['range_low']} - {d['range_high']} ({d['status']})"]
            if not day_trades:
                lines.append("- No trade.")
                continue
            lines += ["", "| Buy | Entry | Fill | SL / target (index) | Exit | Reason | Points | ₹ |",
                      "|---|---|---|---|---|---|---|---|"]
            for t in day_trades:
                exit_cell = f"{t['exit_premium']} ({t['exit_time']})" if t["exit_reason"] != "OPEN" else "open"
                lines.append(f"| {t['qty']} x {t['strike']} {t['side']} | {t['entry_time']} | {t['entry_fill']} | "
                             f"{t['sl_index']} / {t['target_index']} | {exit_cell} | {t['exit_reason']} | "
                             f"{t['pnl_points'] or '-'} | {t['pnl_rupees'] or '-'} |")
    (folder / "ORB_HISTORY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
