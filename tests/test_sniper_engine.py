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
    # Owner, 06-10: SL on the close - the fill candle closes 80 < SL 81 -> out at the close.
    engine, events = _run([("09:20", (78, 64, 72, 67)), ("09:25", (104, 71, 101.9, 72)), ("09:30", (102, 78, 80, 101))])
    [t] = engine.trades
    assert [e.kind for e in events] == ["ORDER", "ENTRY", "EXIT"]
    assert (t.entry_fill, t.exit_reason, t.exit_premium) == (100, "STOPLOSS", 80)


def test_fill_candle_wick_below_the_stop_stays_open():
    engine, events = _run([("09:20", (78, 64, 72, 67)), ("09:25", (104, 71, 101.9, 72)), ("09:30", (102, 78, 85, 101))])
    assert [e.kind for e in events] == ["ORDER", "ENTRY"]
    assert engine.open_trades


def test_order_cancelled_when_the_window_ends_unfilled():
    engine, events = _run([
        ("11:50", (78, 64, 72, 67)),
        ("11:55", (104, 71, 101.9, 72)),  # signal on the candle closing 12:00
        ("12:00", (104, 102, 103, 102)),  # 12:00-12:05 is outside the first half -> cancelled
    ])
    # The first-half order is cancelled; the same 12:00-12:05 candle is already in the second half (owner,
    # 30-09), so a second-half order starts at once (103 is above Sniper 54).
    assert [e.kind for e in events] == ["ORDER", "CANCEL", "ORDER"]
    assert [e.setup.half for e in events] == ["first", "first", "second"]
    assert engine.trades == []


def test_waits_several_candles_for_the_pullback():
    engine, _ = _run([
        ("09:20", (78, 64, 72, 67)),
        ("09:25", (104, 71, 101.9, 72)),
        ("09:30", (110, 101, 108, 102)),
        ("09:35", (115, 104, 106, 108)),
        ("09:40", (107, 99, 103, 106)),  # back to 100 two candles later
    ])
    assert (engine.trades[0].entry_time[11:16], engine.trades[0].entry_fill) == ("09:40", 100)


def test_atm_below_sniper_marks_high_confidence():
    """Owner, 29-09: ATM below Sniper (54 here) = extra confidence. _bars keeps the ATM CE at 20."""
    engine, events = _run([("09:25", (104, 71, 101.9, 72)), ("09:30", (110, 95, 105, 101))])
    assert events[0].atm_below_sniper and engine.trades[0].atm_below_sniper


def test_atm_still_above_sniper_is_normal_confidence():
    engine = SniperDay(date(2026, 9, 29), ROW)
    bars = lambda pe: {"atm_ce": Bar(60, 60, 60, 60), "atm_pe": Bar(200, 200, 200, 200),
                       "otm_ce": Bar(5, 5, 5, 5), "otm_pe": Bar(*pe)}  # ATM CE 60: below its 89.15 close, above Sniper 54
    engine.on_candle(_at("09:25"), bars((104, 71, 101.9, 72)))
    engine.on_candle(_at("09:30"), bars((110, 95, 105, 101)))
    assert engine.trades[0].atm_below_sniper is False



def test_sniper_body_entry_05_10_nifty():
    """Owner, 05-10: ATM 22500 PE's 10:20 body crosses the Sniper 83.30 -> 22400 PE @ 49 (limit), fixed SL 36,
    target 81 (hit at 12:00, high 84.55)."""
    from datetime import date, datetime
    from sniper_engine import Bar, SniperDay
    from sniper_signal import MARKETS, build_daily_plan
    closes = {(22400, "CE"): 161.50, (22400, "PE"): 99.30, (22500, "CE"): 106.90, (22300, "PE"): 66.00,
              (22500, "PE"): 144.10, (22600, "CE"): 67.30}
    row = build_daily_plan(22422, MARKETS["NIFTY"], lambda k, t: closes[(k, t)]).final
    day = SniperDay(date(2026, 10, 5), row)
    at = lambda hm: datetime(2026, 10, 5, int(hm[:2]), int(hm[3:]))
    ce = Bar(70, 60, 62, 65)
    events = day.on_candle(at("10:20"), {"atm_ce": Bar(140.35, 114, 115.45, 140.35), "atm_pe": Bar(85.3, 65, 84, 65.1),
                                         "otm_ce": ce, "otm_pe": Bar(51.5, 38.15, 51.05, 38.15)})
    assert [e.kind for e in events] == ["ORDER"] and events[0].square == 49
    events = day.on_candle(at("10:25"), {"atm_ce": Bar(124.85, 101.15, 119.1, 115.45), "atm_pe": Bar(105.8, 76.8, 81.75, 84),
                                         "otm_ce": ce, "otm_pe": Bar(66.35, 45.6, 49.2, 51.05)})
    trade = events[0].trade
    assert (trade.entry_fill, trade.stop_loss, trade.target) == (49, 36, 81)
    events = day.on_candle(at("12:00"), {"atm_ce": Bar(89.3, 75.55, 87.9, 83.75), "atm_pe": Bar(131.9, 106.5, 109.1, 118.25),
                                         "otm_ce": ce, "otm_pe": Bar(84.55, 65.95, 67.7, 74.85)})
    assert events[0].trade.exit_reason == "TARGET" and events[0].trade.pnl_points == 32


# --- First-half ATM-close trigger (owner, 2026-10-06) ---------------------------------------------------------
# 06-10 SENSEX, owner's +-100 plan: ATM 72400 CE 428.80 / PE 477.15, OTM 72500 CE 377.40 / 72300 PE 432.00,
# Sniper 404.70, index close 72382.47. Normal first-half "up" trigger = ATM PE close 477.15 -> 484.
SENSEX_PREMIUMS = {(72400, "CE"): 428.80, (72400, "PE"): 477.15, (72500, "CE"): 377.40, (72300, "PE"): 432.00}
SENSEX_ROW = build_daily_plan(72382.47, MARKETS["SENSEX"], lambda k, t: SENSEX_PREMIUMS.get((k, t), 1.0)).attempts[0]


def _sensex_bars(otm_ce, atm_pe_close=347.9, index_close=72300):
    """ATM PE below the Sniper (347.9 < 404.70), ATM CE up, OTM PE down; the bought 72500 CE as given (H, L, C, O)."""
    return {"atm_ce": Bar(480, 480, 480, 480), "atm_pe": Bar(atm_pe_close, atm_pe_close, atm_pe_close, atm_pe_close),
            "otm_ce": Bar(*otm_ce), "otm_pe": Bar(300, 300, 300, 300),
            "index": Bar(index_close, index_close, index_close, index_close)}


def _run_sensex(candles, **bar_options):
    engine = SniperDay(date(2026, 10, 6), SENSEX_ROW, index_close=72382.47, near_points=30)
    events = []
    for hhmm, ce in candles:
        events += engine.on_candle(_at(hhmm), _sensex_bars(ce, **bar_options))
    return engine, events


def test_06_10_sensex_72500ce_near_the_atm_ce_close_with_the_index_below():
    """Real 72500 CE candles: 09:25 closes 417.20 (11.60 under 428.80), index below 72382.47 -> buy stop 441;
    09:30 high 458 -> bought 441 (low 408.9 stays above SL 400); 09:55 high 559.5 -> target 529."""
    engine, events = _run_sensex([
        ("09:25", (431.4, 410.6, 417.2, 424.05)),
        ("09:30", (458.0, 408.9, 448.0, 417.2)),
        ("09:35", (467.65, 433.15, 464.5, 448.0)),
        ("09:55", (559.5, 511.1, 530.85, 511.1)),
    ])
    assert [e.kind for e in events] == ["ORDER", "ENTRY", "EXIT"]
    assert (events[0].atm_close_trigger, events[0].near, events[0].next_square) == (428.80, True, 441)
    [t] = engine.trades
    assert (t.entry_time[11:16], t.entry_fill, t.stop_loss, t.target, t.trigger) == ("09:30", 441, 400, 529, 428.80)
    assert (t.exit_reason, t.exit_premium, t.pnl_points) == ("TARGET", 529, 88)


def test_near_needs_the_index_below_yesterdays_close():
    engine, events = _run_sensex([("09:25", (431.4, 410.6, 417.2, 424.05))], index_close=72450)
    assert events == []


def test_near_is_within_30_points_for_sensex():
    engine, events = _run_sensex([("09:25", (400, 390, 398.0, 395))])  # 30.80 under 428.80
    assert events == []


def test_close_above_the_atm_close_signals_without_the_index():
    engine, events = _run_sensex([("09:25", (435, 420, 432.0, 425))], index_close=72450)
    assert [e.kind for e in events] == ["ORDER"]
    assert (events[0].atm_close_trigger, events[0].near, events[0].next_square) == (428.80, False, 441)


def test_atm_close_trigger_needs_the_falling_atm_below_the_sniper():
    engine, events = _run_sensex([("09:25", (435, 420, 432.0, 425))], atm_pe_close=420)  # 420 > Sniper 404.70
    assert events == []


def test_atm_close_trigger_is_first_half_only():
    engine, events = _run_sensex([("12:10", (435, 420, 432.0, 425))])
    assert all(e.atm_close_trigger == 0 for e in events)
