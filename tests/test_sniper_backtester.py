"""
Regression tests for sniper_backtester.simulate_day(), using the worked
example's plan row and a simple linear pricing stand-in so each test can
engineer exact premium crossings from spot values:

    CE(K) = spot - K + 100        PE(K) = K - spot + 100

With the worked example's strikes (ATM 23200, OTM CE 23300, OTM PE 23100):
  - OTM PE 23100 = 23200 - spot   -> first-half "down" entry (> 100) needs spot < 23100
  - OTM CE 23300 = spot - 23200   -> second-half "up" entry (> 64) needs spot > 23264
Spot 23150 is a quiet baseline where nothing triggers.
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from functools import partial

from sniper_backtester import simulate_day as _simulate_day

# Most tests here check entry/exit mechanics with the original "bought at the signal candle's close" fill.
# The owner's fill-at-the-square rule (2026-09-29) has its own tests at the end, using _simulate_day.
simulate_day = partial(_simulate_day, fill_at_square=False)
from sniper_engine import trailed_stop
from sniper_signal import MARKETS, build_daily_plan

WORKED_EXAMPLE_PREMIUMS = {
    (23100, "CE"): 147.40,
    (23100, "PE"): 59.20,
    (23200, "CE"): 89.15,
    (23000, "PE"): 34.25,
    (23300, "CE"): 48.80,
    (23200, "PE"): 99.80,
}
ROW = build_daily_plan(23140.5, MARKETS["NIFTY"], lambda k, t: WORKED_EXAMPLE_PREMIUMS[(k, t)]).final
DAY = date(2026, 9, 29)
BASELINE = 23150


def _price(spot, strike, option_type, when):
    return spot - strike + 100 if option_type == "CE" else strike - spot + 100


def _day(overrides: dict[str, tuple[float, float, float]] = None, fill=None) -> pd.DataFrame:
    """Full 09:15-15:25 day. overrides maps "HH:MM" -> (high, low, close);
    fill=(high, low, close) applies to every non-overridden candle from the
    first override onwards (default: flat baseline)."""
    overrides = overrides or {}
    rows = []
    started = False
    for ts in pd.date_range(f"{DAY} 09:15", f"{DAY} 15:25", freq="5min"):
        key = ts.strftime("%H:%M")
        started = started or key in overrides
        if key in overrides:
            high, low, close = overrides[key]
        elif fill and started:
            high, low, close = fill
        else:
            high, low, close = BASELINE + 5, BASELINE - 5, BASELINE
        rows.append({"date": ts, "open": close, "high": high, "low": low, "close": close, "volume": 0})
    return pd.DataFrame(rows)


def test_plan_row_is_worked_example():
    assert ROW.atm_strike == 23200


def test_quiet_day_no_trade():
    trades, _ = simulate_day(DAY, ROW, _day(), _price)
    assert trades == []


def test_first_half_down_hits_target():
    # 09:40 closes 23095 -> OTM PE 23100 = 105 > 100 and ATM CE 23200 = -5 < 89.15: buy at 105.
    # 09:45 low 23050 -> OTM PE best 150 >= target 144.
    trades, _ = simulate_day(DAY, ROW, _day({"09:40": (23100, 23090, 23095), "09:45": (23100, 23050, 23060)}), _price)

    [t] = trades
    assert (t.half, t.direction, t.buy_strike, t.buy_type) == ("first", "down", 23100, "PE")
    assert (t.entry_square, t.stop_loss, t.target) == (100, 81, 144)
    assert t.entry_fill == 105
    assert t.exit_reason == "TARGET"
    assert t.exit_premium == 144
    assert t.pnl_points == pytest.approx(39)


def test_first_half_down_hits_stop():
    # 09:45 high 23125 -> OTM PE worst 75 <= stop 81.
    trades, _ = simulate_day(DAY, ROW, _day({"09:40": (23100, 23090, 23095), "09:45": (23125, 23100, 23110)}), _price)
    [t] = trades
    assert t.exit_reason == "STOPLOSS"
    assert t.pnl_points == pytest.approx(81 - 105)


def test_stop_wins_when_both_cross_in_one_candle():
    trades, _ = simulate_day(DAY, ROW, _day({"09:40": (23100, 23090, 23095), "09:45": (23125, 23050, 23100)}), _price)
    assert trades[0].exit_reason == "STOPLOSS"


def test_before_0930_is_ignored():
    trades, _ = simulate_day(DAY, ROW, _day({"09:20": (23100, 23090, 23095)}), _price)  # closes 09:25
    assert trades == []


def test_candle_closing_at_0930_counts():
    """29-09-2026: 22700 PE closed 101.90 on the 09:25-09:30 candle - the owner's entry at 100."""
    trades, _ = simulate_day(DAY, ROW, _day({"09:25": (23100, 23090, 23095)}), _price)
    [t] = trades
    assert (t.entry_time[11:16], t.entry_square) == ("09:25", 100)


def test_close_must_be_strictly_above_square():
    # Close 23100 -> OTM PE exactly 100: not above the 100 square.
    trades, _ = simulate_day(DAY, ROW, _day({"09:40": (23105, 23095, 23100)}), _price)
    assert trades == []


def test_time_exit_at_1500():
    trades, _ = simulate_day(DAY, ROW, _day({"09:40": (23100, 23090, 23095)}, fill=(23100, 23090, 23095)), _price)
    [t] = trades  # OTM PE sits at 105 all afternoon - already above the second-half square 64, never crosses it
    assert t.exit_reason == "TIME_EXIT_1500"
    assert t.exit_time.endswith("14:55:00")  # the candle closing at 15:00
    assert t.exit_premium == 105


def test_second_half_up_uses_sniper_square():
    # Spot 23270: OTM CE 23300 = 70. Above the second-half square 64 (Sniper 54), but below the
    # first-half square 100 - so 11:55 does nothing and 12:30 enters.
    trades, _ = simulate_day(
        DAY, ROW, _day({"11:55": (23275, 23265, 23270), "12:30": (23275, 23265, 23270), "12:35": (23305, 23265, 23300)}), _price
    )
    [t] = trades
    assert (t.half, t.direction, t.buy_strike, t.buy_type) == ("second", "up", 23300, "CE")
    assert (t.entry_square, t.stop_loss, t.target) == (64, 49, 100)
    assert t.entry_fill == 70
    assert t.exit_reason == "TARGET"


def test_one_trade_per_half_max_two_per_day():
    candles = _day(
        {
            "09:40": (23100, 23090, 23095),  # first-half entry
            "09:45": (23100, 23050, 23060),  # target
            "10:00": (23100, 23090, 23095),  # would trigger again - first half already used
            "10:05": (23150, 23145, 23150),
            "12:30": (23275, 23265, 23270),  # second-half entry
            "12:35": (23305, 23265, 23300),  # target
            "13:00": (23275, 23265, 23270),  # second half already used
            "13:05": (23150, 23145, 23150),
        }
    )
    trades, _ = simulate_day(DAY, ROW, candles, _price)
    # Owner, 30-09: the first trade hit its target, so no second trade that day.
    assert [(t.half, t.exit_reason) for t in trades] == [("first", "TARGET")]


def test_second_trade_only_after_the_first_is_stopped_out():
    candles = _day(
        {
            "09:40": (23100, 23090, 23095),  # first-half entry at 105 (SL 81)
            "09:45": (23125, 23100, 23110),  # stop: OTM PE worst 75 <= 81
            "12:30": (23275, 23265, 23270),  # second-half entry
            "12:35": (23305, 23265, 23300),  # target
        }
    )
    trades, _ = simulate_day(DAY, ROW, candles, _price)
    assert [(t.half, t.exit_reason) for t in trades] == [("first", "STOPLOSS"), ("second", "TARGET")]


def test_already_above_square_needs_a_fresh_cross():
    # OTM PE runs to 105 at 09:20, before the window opens, and stays there.
    candles = _day({"09:20": (23100, 23090, 23095)}, fill=(23100, 23090, 23095))
    assert simulate_day(DAY, ROW, candles, _price) == ([], 0)

    # Without the crossing rule, 09:30 "enters" at 105, and 12:30 buys the same PE again at 105. Levels come
    # from the square actually above (100), so the second-half target is 144, not the plan's 100.
    trades, _ = simulate_day(DAY, ROW, candles, _price, require_cross=False)
    # The first trade never exits (no stop, no target), so no second trade (owner, 30-09).
    assert [(t.half, t.entry_fill, t.entry_square, t.target) for t in trades] == [("first", 105, 100, 144)]


def test_already_above_buys_the_next_square_it_crosses():
    """28-09-2026: OTM PE jumped from 59 to 164 in the 09:15 candle (before the window), was 189.40 at
    09:25 and closed 197.25 at 09:30 - crossing 196 (14^2). Owner's rule: buy there, SL 13^2, target 16^2."""
    candles = _day(
        {
            "09:15": (23040, 23030, 23036),  # PE 164 - crosses 100..144, but before 09:30
            "09:25": (23015, 23005, 23010.6),  # PE 189.40
            "09:30": (23005, 22995, 23002.75),  # PE 197.25 > 196 = 14^2, previous 189.40 <= 196
        },
        fill=(23005, 22995, 23002.75),
    )
    [t] = simulate_day(DAY, ROW, candles, _price)[0]
    assert (t.entry_time[11:16], t.entry_fill, t.entry_square, t.stop_loss, t.target) == ("09:30", 197.25, 196, 169, 256)


def test_candle_jumping_several_squares_uses_the_highest():
    # Previous close 90, this candle closes 125: crosses 100 and 121 -> entry square 121, SL 100, target 169.
    candles = _day({"09:35": (23115, 23105, 23110), "09:40": (23080, 23070, 23075)})
    [t] = simulate_day(DAY, ROW, candles, _price)[0]
    assert (t.entry_square, t.stop_loss, t.target) == (121, 100, 169)


@pytest.mark.parametrize(
    "stop, close, expected",
    [
        (81, 105, 81),  # above 100 only -> unchanged
        (81, 121, 81),  # exactly 121 is not "above" 121
        (81, 121.05, 100),  # above 121 -> 100
        (81, 150, 121),  # above 144 -> 121 (can jump more than one step)
        (121, 125, 121),  # never moves down
        (144, 175, 144),
        (144, 200, 169),
    ],
)
def test_trailed_stop(stop, close, expected):
    assert trailed_stop(stop, close) == expected


# OTM PE 23100 = 23200 - spot. Entry at 09:40 close 23095 -> 105 (square 100, SL 81, target 144).
ENTRY = {"09:40": (23100, 23090, 23095)}


def test_trailing_moves_stop_to_entry_then_exits_there():
    candles = _day({**ENTRY,
                    "09:45": (23080, 23070, 23075),  # PE 120-130, closes 125 > 121 -> SL 100
                    "09:50": (23105, 23090, 23100)})  # PE low 95 <= 100 -> trailing stop hit
    [t] = simulate_day(DAY, ROW, candles, _price)[0]
    assert (t.exit_reason, t.exit_premium, t.trail_stop) == ("TRAIL_STOP", 100, 100)
    assert t.pnl_points == pytest.approx(-5)  # bought 105, out at 100 - instead of the 81 stop


def test_without_trailing_same_day_holds_the_original_stop():
    candles = _day({**ENTRY, "09:45": (23080, 23070, 23075), "09:50": (23105, 23090, 23100)},
                   fill=(23105, 23090, 23100))
    [t] = simulate_day(DAY, ROW, candles, _price, trailing=False)[0]
    assert t.exit_reason == "TIME_EXIT_1500"  # PE low 95 never reaches 81


RUN_UP = {**ENTRY,
          "09:45": (23080, 23070, 23075),  # closes 125 -> SL 100
          "09:50": (23055, 23045, 23050),  # PE 145-155 (touches target 144), closes 150 -> SL 121
          "09:55": (23025, 23015, 23020),  # closes 180 -> SL 144
          "10:00": (23060, 23015, 23055)}  # PE low 140 <= 144 -> trailing stop


def test_fixed_target_still_exits_first_when_kept():
    [t] = simulate_day(DAY, ROW, _day(RUN_UP), _price)[0]
    assert (t.exit_reason, t.exit_premium) == ("TARGET", 144)


def test_without_target_trailing_rides_the_move():
    [t] = simulate_day(DAY, ROW, _day(RUN_UP), _price, keep_target=False)[0]
    assert (t.exit_reason, t.exit_premium, t.exit_time[11:16]) == ("TRAIL_STOP", 144, "10:00")
    assert t.pnl_points == pytest.approx(144 - 105)


def test_no_entry_on_candle_closing_at_1500():
    trades, _ = simulate_day(DAY, ROW, _day({"14:55": (23275, 23265, 23270)}), _price)
    assert trades == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
