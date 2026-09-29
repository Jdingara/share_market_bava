"""
Owner's fill-at-the-square rule (2026-09-29): a candle closing above the square
is only the signal; the buy is at the square if price comes back to it, or at
the next square if it runs up first.

Uses the §5 worked example's plan: first half, market down -> buy 23100 PE
above 100 (SL 81, target 144). Premium bars are given directly.
"""

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sniper_engine import Bar, SniperDay
from sniper_signal import MARKETS, build_daily_plan

PREMIUMS = {(23100, "CE"): 147.40, (23100, "PE"): 59.20, (23200, "CE"): 89.15,
            (23000, "PE"): 34.25, (23300, "CE"): 48.80, (23200, "PE"): 99.80}
ROW = build_daily_plan(23140.5, MARKETS["NIFTY"], lambda k, t: PREMIUMS[(k, t)]).final


def _at(hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 9, 29, h, m)


def _bars(otm_pe):
    """Market falling: ATM CE below its 89.15 close; the bought OTM PE as given (high, low, close, open)."""
    flat = Bar(20, 20, 20, 20)
    return {"atm_ce": flat, "atm_pe": Bar(200, 200, 200, 200), "otm_ce": Bar(5, 5, 5, 5), "otm_pe": Bar(*otm_pe)}


def _run(candles):
    engine = SniperDay(date(2026, 9, 29), ROW)
    events = []
    for hhmm, pe in candles:
        events += engine.on_candle(_at(hhmm), _bars(pe))
    return engine, events


def test_29_09_22700pe_signal_at_101_90_bought_back_at_100():
    """Real 22700 PE candles on 29-09-2026 (high, low, close, open)."""
    engine, events = _run([
        ("09:20", (78.60, 64.05, 72.10, 67.30)),
        ("09:25", (103.90, 71.40, 101.90, 71.75)),  # closes above 100 at 09:30 -> signal
        ("09:30", (112.00, 90.45, 107.95, 101.85)),  # comes back to 100 -> bought at 100
        ("09:35", (148.85, 107.50, 139.70, 108.10)),  # 144 target
    ])
    assert [e.kind for e in events] == ["ORDER", "ENTRY", "EXIT"]
    assert (events[0].square, events[0].next_square, events[0].signal_close) == (100, 121, 101.90)
    [t] = engine.trades
    assert (t.entry_time[11:16], t.entry_fill, t.stop_loss, t.target) == ("09:30", 100, 81, 144)
    assert (t.exit_reason, t.exit_premium, t.pnl_points) == ("TARGET", 144, 44)


def test_close_above_trigger_is_the_signal_then_buys_when_it_rises_to_the_square():
    """Trigger = ATM CE close 89.15. A close at 95 is the signal; bought at 100 when price rises there."""
    engine, events = _run([
        ("09:25", (96, 80, 95, 82)),  # above 89.15 -> signal; still below 100 -> buy stop at 100
        ("09:30", (99, 90, 97, 95)),  # not yet
        ("09:35", (104, 96, 103, 97)),  # rises through 100 -> bought at 100
    ])
    assert [e.kind for e in events] == ["ORDER", "ENTRY"]
    assert (events[0].square, events[0].next_square) == (0, 100)  # no limit order below 100, only the stop
    [t] = engine.trades
    assert (t.entry_time[11:16], t.entry_fill, t.stop_loss, t.target) == ("09:35", 100, 81, 144)


def test_close_below_trigger_is_no_signal():
    engine, events = _run([("09:25", (90, 80, 89, 82)), ("09:30", (89.15, 85, 89.15, 88))])  # never above 89.15
    assert events == [] and engine.pending == []


def test_runs_up_without_coming_back_buys_the_next_square():
    engine, events = _run([
        ("09:20", (78, 64, 72, 67)),
        ("09:25", (104, 71, 101.9, 72)),
        ("09:30", (130, 102, 128, 102)),  # never back to 100, reaches 121 -> bought at 121
    ])
    [t] = engine.trades
    assert (t.entry_fill, t.entry_square, t.stop_loss, t.target) == (121, 121, 100, 169)


def test_opens_above_the_next_square_fills_at_the_open():
    engine, _ = _run([("09:20", (78, 64, 72, 67)), ("09:25", (104, 71, 101.9, 72)), ("09:30", (135, 125, 130, 126))])
    assert (engine.trades[0].entry_fill, engine.trades[0].entry_square) == (126, 121)


def test_touches_both_with_unknown_order_assumes_the_worse_price():
    engine, _ = _run([("09:20", (78, 64, 72, 67)), ("09:25", (104, 71, 101.9, 72)), ("09:30", (125, 95, 110, 105))])
    assert (engine.trades[0].entry_fill, engine.trades[0].entry_square) == (121, 121)


def test_filled_and_stopped_in_the_same_candle():
    engine, events = _run([("09:20", (78, 64, 72, 67)), ("09:25", (104, 71, 101.9, 72)), ("09:30", (102, 78, 80, 101))])
    [t] = engine.trades
    assert [e.kind for e in events] == ["ORDER", "ENTRY", "EXIT"]
    assert (t.entry_fill, t.exit_reason, t.exit_premium) == (100, "STOPLOSS", 81)


def test_order_cancelled_when_the_window_ends_unfilled():
    engine, events = _run([
        ("11:50", (78, 64, 72, 67)),
        ("11:55", (104, 71, 101.9, 72)),  # signal on the candle closing 12:00
        ("12:00", (104, 102, 103, 102)),  # 12:00-12:05 is outside the first half -> cancelled
    ])
    assert [e.kind for e in events] == ["ORDER", "CANCEL"]
    assert engine.trades == [] and engine.pending == []


def test_waits_several_candles_for_the_pullback():
    engine, _ = _run([
        ("09:20", (78, 64, 72, 67)),
        ("09:25", (104, 71, 101.9, 72)),
        ("09:30", (110, 101, 108, 102)),
        ("09:35", (115, 104, 106, 108)),
        ("09:40", (107, 99, 103, 106)),  # back to 100 two candles later
    ])
    assert (engine.trades[0].entry_time[11:16], engine.trades[0].entry_fill) == ("09:40", 100)
