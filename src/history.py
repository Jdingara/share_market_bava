"""
Permanent day-by-day record of the paper bot, kept in history/ (committed to
git, unlike data/paper_trades/ which holds raw per-day logs):

    history/days.csv          one row per trading day per market: the plan and the day's result
    history/trades.csv        one row per paper trade
    history/TRADE_HISTORY.md  the same, readable - generated from the two CSVs

The live bot calls record_day() when the plan is built, after every entry or
exit, and when the day ends - so a bot that stops mid-day (window closed,
laptop asleep) still leaves everything up to that point, with its status
showing it never finished. Rows are keyed by (date, market) and
(date, market, half), so re-recording a day replaces it instead of adding
duplicates.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

from sniper_engine import TradeResult
from sniper_signal import DailyPlan

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = PROJECT_ROOT / "history"

DAY_FIELDS = [
    "date", "market", "index_close", "previous_day", "expiry", "atm", "shifts", "sniper",
    "plan", "trades", "pnl_points", "pnl_rupees", "qty", "status", "last_update", "note",
]
TRADE_FIELDS = [
    "date", "market", "half", "direction", "symbol", "qty", "entry_time", "entry_fill", "entry_square",
    "stop_loss", "trail_stop", "target", "exit_time", "exit_premium", "exit_reason", "pnl_points",
    "pnl_rupees", "confidence", "note",
]


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(path: Path, fields: list[str], rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def record_day(
    day: date,
    market: str,
    plan: DailyPlan,
    expiry: str,
    previous_day: str,
    qty: int,
    trades: list[TradeResult],
    symbols: dict[str, str],
    status: str,
    note: str = "",
    history_dir: Optional[Path] = None,
) -> None:
    """Replaces this day's rows for this market in the history files.
    `symbols` maps "CE"/"PE" to the bought OTM contract's trading symbol."""
    folder = history_dir or HISTORY_DIR
    closed = [t for t in trades if t.exit_reason]
    pnl = round(sum(t.pnl_points for t in closed), 2)
    row = plan.final or (plan.attempts[-1] if plan.attempts else None)
    day_row = {
        "date": day.isoformat(),
        "market": market,
        "index_close": plan.index_close,
        "previous_day": previous_day,
        "expiry": expiry,
        "atm": f"{row.atm_strike:g}" if row else "",
        "shifts": len(plan.attempts) - 1,
        "sniper": round(row.sniper, 2) if row else "",
        "plan": "yes" if plan.final else f"no plan: {plan.reason}",
        "trades": len(trades),
        "pnl_points": pnl,
        "pnl_rupees": round(pnl * qty),
        "qty": qty,
        "status": status,
        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "note": note,
    }
    key = (day_row["date"], market)
    days = [d for d in _read(folder / "days.csv") if (d["date"], d["market"]) != key] + [day_row]
    days.sort(key=lambda d: (d["date"], d["market"]))
    _write(folder / "days.csv", DAY_FIELDS, days)

    trade_rows = [
        {
            "date": day.isoformat(),
            "market": market,
            "half": t.half,
            "direction": t.direction,
            "symbol": symbols.get(t.buy_type, f"{t.buy_strike:g} {t.buy_type}"),
            "qty": qty,
            "entry_time": t.entry_time[11:16],
            "entry_fill": t.entry_fill,
            "entry_square": t.entry_square,
            "stop_loss": t.stop_loss,
            "trail_stop": t.trail_stop,
            "target": t.target,
            "exit_time": t.exit_time[11:16],
            "exit_premium": t.exit_premium if t.exit_reason else "",
            "exit_reason": t.exit_reason or "OPEN",
            "pnl_points": t.pnl_points if t.exit_reason else "",
            "pnl_rupees": round(t.pnl_points * qty) if t.exit_reason else "",
            "confidence": "HIGH (ATM below Sniper)" if getattr(t, "atm_below_sniper", False) else "normal",
            "note": getattr(t, "note", ""),
        }
        for t in trades
    ]
    all_trades = [t for t in _read(folder / "trades.csv") if (t["date"], t["market"]) != key] + trade_rows
    all_trades.sort(key=lambda t: (t["date"], t["market"], t["entry_time"]))
    _write(folder / "trades.csv", TRADE_FIELDS, all_trades)

    write_markdown(folder)


def _num(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def write_markdown(folder: Optional[Path] = None) -> Path:
    folder = folder or HISTORY_DIR
    days = _read(folder / "days.csv")
    trades = _read(folder / "trades.csv")
    total_pts = sum(_num(d["pnl_points"]) for d in days)
    total_rs = sum(_num(d["pnl_rupees"]) for d in days)
    n_trades = sum(int(_num(d["trades"])) for d in days)

    lines = [
        "# Trade History",
        "",
        "**Paper trades — no real orders.** Written automatically by the bot (`src/history.py`) after every entry/exit;",
        "don't edit by hand, change `history/days.csv` / `history/trades.csv` instead. ₹ = points × qty, before brokerage and charges.",
        "",
        f"**All days: {n_trades} trade(s), {total_pts:+.2f} points, ₹{total_rs:+,.0f}**",
        "",
        "| Date | Market | ATM | Sniper | Trades | P&L points | P&L ₹ | Status |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for d in sorted(days, key=lambda d: (d["date"], d["market"]), reverse=True):
        plan = f"{d['atm']}" if d["plan"] == "yes" else "no plan"
        lines.append(
            f"| {d['date']} | {d['market']} | {plan} | {d['sniper'] if d['plan'] == 'yes' else '–'} | {d['trades']} | "
            f"{_num(d['pnl_points']):+.2f} | ₹{_num(d['pnl_rupees']):+,.0f} | {d['status']} |"
        )

    for day in sorted({d["date"] for d in days}, reverse=True):
        weekday = datetime.fromisoformat(day).strftime("%a")
        lines += ["", f"## {day} ({weekday})"]
        for d in [d for d in days if d["date"] == day]:
            lines += [
                "",
                f"### {d['market']} — {d['status']} (last update {d['last_update']})",
                "",
                f"- {d['market']} close {d['index_close']} on {d['previous_day']}, expiry {d['expiry']}, qty {d['qty']}.",
            ]
            if d["plan"] == "yes":
                lines.append(f"- Plan: ATM {d['atm']} after {d['shifts']} shift(s), Sniper {d['sniper']}.")
            else:
                lines.append(f"- {d['plan'].capitalize()} — no trading that day.")
            if d["note"]:
                lines.append(f"- Note: {d['note']}")
            day_trades = [t for t in trades if t["date"] == day and t["market"] == d["market"]]
            if day_trades:
                lines += [
                    "",
                    "| Half | Buy | Entry | Fill | Square | SL → trailed | Target | Exit | Reason | Points | ₹ |",
                    "|---|---|---|---|---|---|---|---|---|---|---|",
                ]
                for t in day_trades:
                    sl = t["stop_loss"] if _num(t["trail_stop"]) <= _num(t["stop_loss"]) else f"{t['stop_loss']} → {_num(t['trail_stop']):g}"
                    exit_cell = f"{_num(t['exit_premium']):g} ({t['exit_time']})" if t["exit_reason"] != "OPEN" else "open"
                    pts = f"{_num(t['pnl_points']):+.2f}" if t["pnl_points"] else "–"
                    rs = f"₹{_num(t['pnl_rupees']):+,.0f}" if t["pnl_rupees"] else "–"
                    note = f" ({t['note']})" if t["note"] else ""
                    if t.get("confidence", "").startswith("HIGH"):
                        note += " ★ HIGH"
                    lines.append(
                        f"| {t['half']} | {t['qty']} × {t['symbol']} | {t['entry_time']}{note} | {t['entry_fill']} | "
                        f"{t['entry_square']} | {sl} | {t['target']} | {exit_cell} | {t['exit_reason']} | {pts} | {rs} |"
                    )
            elif d["plan"] == "yes" and d["status"] == "watching":
                lines.append("- No trade yet.")
            elif d["plan"] == "yes":
                lines.append("- No trade (no square crossed in the entry windows).")

    path = folder / "TRADE_HISTORY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
