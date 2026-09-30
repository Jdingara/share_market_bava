"""hlc_live.feed(): only closed candles, in order, once; state and history get the result."""

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hlc_engine import HlcDay
from hlc_history import record_hlc_day
from hlc_live import HlcState, feed, info_lines
from hlc_signal import HLC_MARKETS, Candle, hlc_levels

IST = timezone(timedelta(hours=5, minutes=30))
LEVELS = hlc_levels(22716.25, 22800, 156.10, 150.90)  # 30-09-2026 NIFTY (data 29-09)
YESTERDAY = {"CE": (189.0, 111.9, 156.1), "PE": (273.4, 134.85, 150.9)}


def _row(hhmm, o, h, l, c):
    hh, mm = map(int, hhmm.split(":"))
    return {"date": datetime(2026, 9, 30, hh, mm, tzinfo=IST), "open": o, "high": h, "low": l, "close": c}


INDEX = [_row("09:15", 22665, 22718.45, 22659.8, 22702.7), _row("09:20", 22702.85, 22733.35, 22697.2, 22727.95),
         _row("09:25", 22727.8, 22736.65, 22714.45, 22721.65), _row("09:30", 22720.4, 22720.4, 22672, 22690),
         _row("09:35", 22690, 22700, 22655, 22660)]
TIMES = [datetime(2026, 9, 30, 9, 15) + timedelta(minutes=5 * i) for i in range(5)]
CE = dict(zip(TIMES, [Candle(141, 142, 128, 135), Candle(135, 140, 133, 139), Candle(139, 141, 136, 137),
                      Candle(137, 138, 128, 130), Candle(130, 131, 110, 111)]))
PE = {t: Candle(150, 152, 148, 150) for t in TIMES}


def test_feed_processes_closed_candles_once_and_updates_state_and_history(tmp_path):
    engine = HlcDay(date(2026, 9, 30), LEVELS, HLC_MARKETS["NIFTY"], YESTERDAY)
    state = HlcState("NIFTY", "LIVE", "2026-09-30", 325)
    state.set_plan(LEVELS, "2026-09-29", "2026-10-06", YESTERDAY, {"CE": "NIFTY26O0622800CE", "PE": "NIFTY26O0622800PE"})
    premiums = {(22800.0, "CE"): CE, (22800.0, "PE"): PE}
    processed = set()

    events = feed(engine, INDEX, premiums, processed, datetime(2026, 9, 30, 9, 38), state, None)  # 09:35 still forming
    assert len(processed) == 4 and any("BUY CE 22800 at 130.00 (FIB" in e for e in events)
    assert feed(engine, INDEX, premiums, processed, datetime(2026, 9, 30, 9, 38), state, None) == []  # nothing new
    events = feed(engine, INDEX, premiums, processed, datetime(2026, 9, 30, 9, 41), state, None)
    assert any("SL (index below first low 22659.8)" in e for e in events)

    state.set_engine(engine)
    data = json.loads(state.to_json())
    assert data["trades"][0]["pnl_points"] == -19.0
    assert "★ Buyer's day" in data["info"][-1]

    record_hlc_day(date(2026, 9, 30), "NIFTY", LEVELS, YESTERDAY, engine.big_gap, engine.trades, 325, "finished", folder=tmp_path)
    md = (tmp_path / "HLC_HISTORY.md").read_text(encoding="utf-8")
    assert "All days: 1 trade(s), -19.00 points, ₹-6,175" in md and "PANIC / PROFIT BOOKING | yes" in md


def test_info_lines_flag_a_buyers_day():
    lines = info_lines(LEVELS, YESTERDAY)
    assert lines[0].startswith("CE 22800 = PANIC") and lines[1].startswith("PE 22800 = PROFIT BOOKING")
