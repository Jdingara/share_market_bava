"""history.py: per-day records are replaced, not duplicated, and the markdown adds up."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from history import _read, record_day
from sniper_engine import TradeResult
from sniper_signal import MARKETS, build_daily_plan

PREMIUMS = {(23100, "CE"): 147.40, (23100, "PE"): 59.20, (23200, "CE"): 89.15,
            (23000, "PE"): 34.25, (23300, "CE"): 48.80, (23200, "PE"): 99.80}
PLAN = build_daily_plan(23140.5, MARKETS["NIFTY"], lambda k, t: PREMIUMS[(k, t)])
SYMBOLS = {"CE": "NIFTY26SEP23300CE", "PE": "NIFTY26SEP23100PE"}


def _trade(exit_reason="", exit_premium=0.0, pnl=0.0):
    return TradeResult(date="2026-09-28", half="first", direction="down", buy_strike=23100, buy_type="PE",
                       trigger=89.15, entry_square=196, stop_loss=169, target=256,
                       entry_time="2026-09-28T09:30:00", entry_fill=197.25,
                       exit_time="2026-09-28T10:40:00" if exit_reason else "", exit_premium=exit_premium,
                       exit_reason=exit_reason, pnl_points=pnl, trail_stop=196, note="catch-up")


def _record(folder, trades, status, day=date(2026, 9, 28), market="NIFTY"):
    record_day(day, market, PLAN, "2026-09-29", "2026-09-25", 325, trades, SYMBOLS, status, history_dir=folder)


def test_open_trade_then_exit_replaces_the_day(tmp_path):
    _record(tmp_path, [_trade()], "watching")
    [row] = _read(tmp_path / "trades.csv")
    assert row["exit_reason"] == "OPEN" and row["pnl_rupees"] == ""

    _record(tmp_path, [_trade("TARGET", 256, 58.75)], "finished")
    [day] = _read(tmp_path / "days.csv")
    [row] = _read(tmp_path / "trades.csv")
    assert (day["status"], day["trades"], day["pnl_rupees"]) == ("finished", "1", "19094")
    assert (row["exit_reason"], row["pnl_rupees"], row["symbol"], row["note"]) == ("TARGET", "19094", "NIFTY26SEP23100PE", "catch-up")

    md = (tmp_path / "TRADE_HISTORY.md").read_text(encoding="utf-8")
    assert "All days: 1 trade(s), +58.75 points, ₹+19,094" in md
    assert "| first | 325 × NIFTY26SEP23100PE | 09:30 (catch-up) | 197.25 | 196 | 169 → 196 | 256 | 256 (10:40) | TARGET | +58.75 | ₹+19,094 |" in md


def test_days_and_markets_accumulate(tmp_path):
    _record(tmp_path, [_trade("TARGET", 256, 58.75)], "finished")
    _record(tmp_path, [], "watching", day=date(2026, 9, 30))
    assert "- No trade yet." in (tmp_path / "TRADE_HISTORY.md").read_text(encoding="utf-8")
    _record(tmp_path, [], "finished", day=date(2026, 9, 29))
    _record(tmp_path, [], "no plan", day=date(2026, 9, 29), market="SENSEX")
    days = _read(tmp_path / "days.csv")
    assert [(d["date"], d["market"]) for d in days] == [
        ("2026-09-28", "NIFTY"), ("2026-09-29", "NIFTY"), ("2026-09-29", "SENSEX"), ("2026-09-30", "NIFTY")]
    md = (tmp_path / "TRADE_HISTORY.md").read_text(encoding="utf-8")
    assert md.index("## 2026-09-30") < md.index("## 2026-09-29") < md.index("## 2026-09-28")  # newest first
    assert "- No trade (no square crossed in the entry windows)." in md


def test_two_bots_writing_at_once_keep_both_rows(tmp_path):
    """30-09: the NIFTY and SENSEX bots rewrote the shared file at the same moment and one row was lost."""
    import threading
    threads = [threading.Thread(target=_record, args=(tmp_path, [], "finished", date(2026, 9, 30), market))
               for market in ("NIFTY", "SENSEX") for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(d["market"] for d in _read(tmp_path / "days.csv")) == ["NIFTY", "SENSEX"]
    assert not (tmp_path / ".lock").exists()
