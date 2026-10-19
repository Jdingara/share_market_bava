from datetime import date, datetime, timedelta

from lalitha_engine import LalithaDay
from lalitha_indicators import Bar, bollinger, pivots, rsi, supertrend


def test_pivots_traditional():
    p = pivots(110, 90, 100)
    assert p["P"] == 100 and p["R1"] == 110 and p["S1"] == 90


def test_rsi_all_gains_is_100_and_bollinger_flat_is_zero_width():
    assert rsi([float(i) for i in range(30)])[-1] == 100.0
    lower, mid, upper = bollinger([5.0] * 25)[-1]
    assert lower == mid == upper == 5.0


def test_supertrend_turns_up_on_a_strong_rally_and_down_on_a_drop():
    bars = [Bar(100, 101, 99, 100)] * 15
    up = bars + [Bar(100 + i, 102 + i, 99 + i, 101 + i) for i in range(1, 15)]
    assert supertrend(up)[-1][1] == 1
    down = up + [Bar(110 - 3 * i, 111 - 3 * i, 105 - 3 * i, 106 - 3 * i) for i in range(1, 10)]
    assert supertrend(down)[-1][1] == -1


def _day():
    warm = [Bar(100, 100.5, 99.5, 100)] * 40  # flat history
    return LalithaDay(date(2026, 10, 19), 260, (101, 99, 100), warm)  # P 100, R1 101, S1 99


def test_ce_signal_buys_the_premium_nearest_250_and_exits_on_the_supertrend_flip():
    day = _day()
    t0 = datetime(2026, 10, 19, 9, 15)
    prem = {(22900.0, "CE"): 310.0, (23000.0, "CE"): 255.0, (23100.0, "CE"): 190.0}
    candidates = lambda side: [22900.0, 23000.0, 23100.0]
    events = []
    for i in range(6):  # a strong rally: above R1 and the upper band, RSI > 70, Supertrend up
        c = 101 + 2 * i
        events += day.on_candle(t0 + timedelta(minutes=5 * i), Bar(c - 1.5, c + 0.5, c - 2, c), lambda k, s: prem.get((k, s)), candidates)
        if day.trades:
            break
    t = day.trades[0]
    assert t.side == "CE" and t.strike == 23000.0 and t.entry_fill == 255.0 and t.qty == 260
    when = t0 + timedelta(minutes=50)
    day.on_candle(when, Bar(100, 100, 80, 80), lambda k, s: 150.0, candidates)  # crash -> Supertrend flips down
    assert t.exit_reason.startswith("Supertrend turned down") and t.exit_premium == 150.0
