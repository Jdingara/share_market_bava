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
LEVELS = hlc_levels(22780.25, 22800, 84.20, 71.45)
YESTERDAY = {"CE": (298.5, 77.05, 84.20), "PE": (94.0, 8.4, 71.45)}


def _row(hhmm, o, h, l, c):
    hh, mm = map(int, hhmm.split(":"))
    return {"date": datetime(2026, 9, 29, hh, mm, tzinfo=IST), "open": o, "high": h, "low": l, "close": c}


INDEX = [_row("09:15", 22732.45, 22753, 22680, 22684), _row("09:20", 22683, 22686, 22656, 22667),
         _row("09:25", 22667, 22668, 22624, 22624.2), _row("09:30", 22624, 22638, 22611, 22620),
         _row("09:35", 22619, 22619.5, 22569.7, 22577.3), _row("09:40", 22577, 22628, 22573, 22613)]
PE = {datetime(2026, 9, 29, 9, 15) + timedelta(minutes=5 * i): Candle(*c) for i, c in enumerate(
    [(77, 133.9, 76.5, 132), (132, 149, 127, 139.8), (139, 180, 138, 177.1), (177, 190, 164, 186.8),
     (186, 233, 186, 222.7), (222, 225, 177, 189.8)])}
CE = {t: Candle(20, 21, 19, 20) for t in PE}


def test_feed_processes_closed_candles_once_and_updates_state_and_history(tmp_path):
    engine = HlcDay(date(2026, 9, 29), LEVELS, HLC_MARKETS["NIFTY"], YESTERDAY)
    state = HlcState("NIFTY", "LIVE", "2026-09-29", 325)
    state.set_plan(LEVELS, "2026-09-28", "2026-09-29", YESTERDAY, {"CE": "NIFTY26SEP22800CE", "PE": "NIFTY26SEP22800PE"})
    premiums = {(22800.0, "CE"): CE, (22800.0, "PE"): PE}
    processed = set()

    events = feed(engine, INDEX, premiums, processed, datetime(2026, 9, 29, 9, 33), state, None)  # 09:30 candle still forming
    assert len(processed) == 3 and any("BUY PE 22800 at 177.10" in e for e in events)
    assert feed(engine, INDEX, premiums, processed, datetime(2026, 9, 29, 9, 33), state, None) == []  # nothing new
    events = feed(engine, INDEX, premiums, processed, datetime(2026, 9, 29, 9, 46), state, None)
    assert any("TARGET S3" in e for e in events)

    state.set_engine(engine)
    data = json.loads(state.to_json())
    assert data["trades"][0]["pnl_points"] == 45.6 and data["blocked"] == {"CE": "PE PANIC yesterday and above its high 94 today"}
    assert "★ Buyer's day" in data["info"][-1]

    record_hlc_day(date(2026, 9, 29), "NIFTY", LEVELS, YESTERDAY, engine.big_gap, engine.trades, 325, "finished", folder=tmp_path)
    md = (tmp_path / "HLC_HISTORY.md").read_text(encoding="utf-8")
    assert "All days: 1 trade(s), +45.60 points, ₹+14,820" in md and "PROFIT BOOKING / PANIC | yes" in md


def test_info_lines_flag_a_buyers_day():
    lines = info_lines(LEVELS, YESTERDAY)
    assert lines[0].startswith("CE 22800 = PROFIT BOOKING") and lines[1].startswith("PE 22800 = PANIC")
