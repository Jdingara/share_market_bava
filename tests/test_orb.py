import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hlc_signal import Candle
from orb_engine import ORB_MARKETS, OrbDay


def _at(hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 10, 19, h, m)


def _chain(ce=100.0, pe=100.0, strike=23000.0):
    return {(strike, "CE"): Candle(ce, ce, ce, ce), (strike, "PE"): Candle(pe, pe, pe, pe)}


def _day():
    day = OrbDay(date(2026, 10, 19), ORB_MARKETS["NIFTY"])
    day.on_candle(_at("09:15"), Candle(23000, 23040, 22990, 23020), _chain())  # range 22990 - 23040
    return day


def test_close_above_the_range_buys_the_atm_ce_with_sl_at_the_low_and_a_1_to_2_target():
    day = _day()
    assert day.on_candle(_at("09:25"), Candle(23020, 23050, 23015, 23045), _chain()) == []  # closes 09:30 - not after 09:30
    events = day.on_candle(_at("09:30"), Candle(23045, 23060, 23040, 23050), _chain(ce=120, strike=23050.0))
    t = day.trades[0]
    assert (t.side, t.strike, t.entry_fill, t.qty) == ("CE", 23050.0, 120, 130)  # NIFTY 2 lots
    assert (t.sl_index, t.target_index) == (23000, 23050 + 2 * 50)  # 60 > 50 -> capped
    assert events[0].startswith("BUY 130 x CE 23050")


def test_target_then_re_entry_outside_the_range():
    day = _day()
    day.on_candle(_at("09:30"), Candle(23045, 23060, 23040, 23050), _chain(ce=120, strike=23050.0))
    day.on_candle(_at("09:35"), Candle(23050, 23175, 23045, 23160), _chain(ce=180, strike=23050.0) | _chain(ce=170, strike=23150.0))
    first, second = day.trades
    assert first.exit_reason.startswith("TARGET 1:2") and first.pnl_points == 60
    assert second.side == "CE" and second.strike == 23150.0  # still outside the range -> re-entry


def test_opposite_break_closes_the_old_and_opens_the_new_side():
    day = _day()
    day.on_candle(_at("09:30"), Candle(23045, 23060, 23040, 23050), _chain(ce=120, strike=23050.0))
    day.on_candle(_at("09:35"), Candle(23050, 23052, 22960, 22970), _chain(ce=60, pe=140, strike=23050.0) | _chain(pe=150, strike=22950.0))
    first, second = day.trades
    assert first.exit_reason.startswith("SL") and second.side == "PE" and second.sl_index == 23020  # 22970 + 50 cap


def test_no_entry_in_the_lunch_gap_and_square_off_at_1516():
    day = _day()
    assert day.on_candle(_at("12:05"), Candle(23045, 23060, 23040, 23050), _chain(strike=23050.0)) == []
    day.on_candle(_at("15:00"), Candle(23045, 23060, 23040, 23050), _chain(ce=120, strike=23050.0))
    events = day.on_candle(_at("15:10"), Candle(23050, 23055, 23045, 23052), _chain(ce=125, strike=23050.0))
    assert day.trades[0].exit_reason == "15:16 square-off" and day.done and events


def test_at_most_ten_trades():
    day = _day()
    for i in range(12):
        hhmm = f"{10 + i // 6:02d}:{(i % 6) * 10:02d}"
        day.on_candle(_at(hhmm), Candle(23045, 23200, 23040, 23050), _chain(ce=100, strike=23050.0))
    assert len(day.trades) == 10


def test_sl_is_capped_at_50_nifty_points():
    day = OrbDay(date(2026, 10, 19), ORB_MARKETS["NIFTY"])
    day.on_candle(_at("09:15"), Candle(23000, 23100, 22980, 23050), _chain())  # low 22980 is 125 below the entry
    day.on_candle(_at("09:30"), Candle(23090, 23110, 23085, 23105), _chain(ce=150, strike=23100.0))
    t = day.trades[0]
    assert t.sl_index == 23055 and t.target_index == 23205
