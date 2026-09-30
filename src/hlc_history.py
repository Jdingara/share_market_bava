"""
Permanent day-by-day record for the HLC strategy, in history/hlc/ (committed):

    history/hlc/days.csv      one row per day per market: plan, labels, result
    history/hlc/trades.csv    one row per paper trade
    history/hlc/HLC_HISTORY.md  readable, newest day first

Written after every entry/exit by hlc_live.py, so a mid-day stop still leaves
a record. Re-recording a (date, market) replaces it.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

from hlc_engine import HlcTrade
from hlc_signal import HlcLevels, leg_label
from history import _read, _write, folder_lock

HLC_HISTORY_DIR = Path(__file__).resolve().parent.parent / "history" / "hlc"

DAY_FIELDS = ["date", "market", "close", "atm", "r1", "r2", "r3", "s1", "s2", "s3", "ce_label", "pe_label",
              "buyers_day", "big_gap", "trades", "pnl_points", "pnl_rupees", "qty", "status", "last_update", "note"]
TRADE_FIELDS = ["date", "market", "kind", "side", "strike", "pattern", "qty", "entry_time", "entry_fill", "sl",
                "sl_rule", "exit_time", "exit_premium", "exit_reason", "pnl_points", "pnl_rupees"]


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def record_hlc_day(*args, **kwargs) -> None:
    with folder_lock(kwargs.get("folder") or HLC_HISTORY_DIR):
        _record_hlc_day(*args, **kwargs)


def _record_hlc_day(day: date, market: str, levels: HlcLevels, yesterday: dict[str, tuple[float, float, float]],
                   big_gap: bool, trades: list[HlcTrade], qty: int, status: str, note: str = "",
                   folder: Optional[Path] = None) -> None:
    folder = folder or HLC_HISTORY_DIR
    ce_label, pe_label = leg_label(*yesterday["CE"]), leg_label(*yesterday["PE"])
    closed = [t for t in trades if t.exit_reason]
    pnl = round(sum(t.pnl_points for t in closed), 2)
    row = {
        "date": day.isoformat(), "market": market, "close": levels.close, "atm": f"{levels.atm:g}",
        "r1": levels.r1, "r2": levels.r2, "r3": levels.r3, "s1": levels.s1, "s2": levels.s2, "s3": levels.s3,
        "ce_label": ce_label, "pe_label": pe_label, "buyers_day": "yes" if ce_label != pe_label else "no",
        "big_gap": "yes" if big_gap else "no", "trades": len(trades), "pnl_points": pnl, "pnl_rupees": round(pnl * qty),
        "qty": qty, "status": status, "last_update": datetime.now().strftime("%Y-%m-%d %H:%M"), "note": note,
    }
    key = (row["date"], market)
    days = [d for d in _read(folder / "days.csv") if (d["date"], d["market"]) != key] + [row]
    days.sort(key=lambda d: (d["date"], d["market"]))
    _write(folder / "days.csv", DAY_FIELDS, days)

    trade_rows = [{
        "date": day.isoformat(), "market": market, "kind": t.kind, "side": t.side, "strike": f"{t.strike:g}",
        "pattern": t.pattern, "qty": qty, "entry_time": t.entry_time[11:16], "entry_fill": t.entry_fill,
        "sl": t.sl_premium, "sl_rule": t.sl_rule, "exit_time": t.exit_time[11:16],
        "exit_premium": t.exit_premium if t.exit_reason else "", "exit_reason": t.exit_reason or "OPEN",
        "pnl_points": t.pnl_points if t.exit_reason else "",
        "pnl_rupees": round(t.pnl_points * qty) if t.exit_reason else "",
    } for t in trades]
    rows = [t for t in _read(folder / "trades.csv") if (t["date"], t["market"]) != key] + trade_rows
    rows.sort(key=lambda t: (t["date"], t["market"], t["entry_time"]))
    _write(folder / "trades.csv", TRADE_FIELDS, rows)
    write_hlc_markdown(folder)


def write_hlc_markdown(folder: Optional[Path] = None) -> Path:
    folder = folder or HLC_HISTORY_DIR
    days, trades = _read(folder / "days.csv"), _read(folder / "trades.csv")
    total_pts = sum(_num(d["pnl_points"]) for d in days)
    total_rs = sum(_num(d["pnl_rupees"]) for d in days)
    lines = [
        "# HLC Trade History", "",
        "**Paper trades — no real orders.** Written by the bot (`src/hlc_history.py`). ₹ = points × qty, before charges.", "",
        f"**All days: {sum(int(_num(d['trades'])) for d in days)} trade(s), {total_pts:+.2f} points, ₹{total_rs:+,.0f}**", "",
        "| Date | Market | ATM | CE / PE yesterday | Buyer's day | Trades | P&L points | P&L ₹ | Status |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for d in sorted(days, key=lambda d: (d["date"], d["market"]), reverse=True):
        lines.append(f"| {d['date']} | {d['market']} | {d['atm']} | {d['ce_label']} / {d['pe_label']} | {d['buyers_day']} | "
                     f"{d['trades']} | {_num(d['pnl_points']):+.2f} | ₹{_num(d['pnl_rupees']):+,.0f} | {d['status']} |")
    for day in sorted({d["date"] for d in days}, reverse=True):
        lines += ["", f"## {day} ({datetime.fromisoformat(day):%a})"]
        for d in [d for d in days if d["date"] == day]:
            lines += ["", f"### {d['market']} — {d['status']} (last update {d['last_update']})", "",
                      f"- Close {d['close']}, ATM {d['atm']}{' — BIG GAP day' if d['big_gap'] == 'yes' else ''}. "
                      f"R3 {d['r3']} · R2 {d['r2']} · R1 {d['r1']} · S1 {d['s1']} · S2 {d['s2']} · S3 {d['s3']}.",
                      f"- CE {d['ce_label']}, PE {d['pe_label']}{' — buyer’s day' if d['buyers_day'] == 'yes' else ''}."]
            if d["note"]:
                lines.append(f"- Note: {d['note']}")
            day_trades = [t for t in trades if t["date"] == day and t["market"] == d["market"]]
            if day_trades:
                lines += ["", "| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |",
                          "|---|---|---|---|---|---|---|---|---|---|"]
                for t in day_trades:
                    exit_cell = f"{_num(t['exit_premium']):g} ({t['exit_time']})" if t["exit_reason"] != "OPEN" else "open"
                    pts = f"{_num(t['pnl_points']):+.2f}" if t["pnl_points"] else "–"
                    rs = f"₹{_num(t['pnl_rupees']):+,.0f}" if t["pnl_rupees"] else "–"
                    lines.append(f"| {t['kind']} | {t['qty']} × {t['strike']} {t['side']} | {t['pattern']} | {t['entry_time']} | "
                                 f"{t['entry_fill']} | {t['sl']} ({t['sl_rule']}) | {exit_cell} | {t['exit_reason']} | {pts} | {rs} |")
            else:
                lines.append("- No trade.")
    path = folder / "HLC_HISTORY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
