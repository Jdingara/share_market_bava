"""
Owner's fill-at-the-square rule (2026-09-29): a candle closing above the square
is only the signal; the buy is at the square if price comes back to it, or at
the next square if it runs up first.

Uses the §5 worked example's plan: first half, market down -> buy 23100 PE
above 100 (SL 81, target 144). Premium bars are given directly.
"""

import sys

import pytest
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


def test_close_above_trigger_is_the_signal_then_buys_when_it_rises_to_the_square(monkeypatch):
    """Trigger = ATM CE close 89.15. A close at 95 is the signal; bought at 100 when price rises there."""
    import sniper_engine as _se
    monkeypatch.setattr(_se, "RETEST_ONLY", False)  # the older buy-stop-at-the-next-square rule
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


def test_runs_up_without_coming_back_buys_the_next_square(monkeypatch):
    import sniper_engine as _se
    monkeypatch.setattr(_se, "RETEST_ONLY", False)  # the older buy-stop-at-the-next-square rule
    engine, events = _run([
        ("09:20", (78, 64, 72, 67)),
        ("09:25", (104, 71, 101.9, 72)),
        ("09:30", (130, 102, 128, 102)),  # never back to 100, reaches 121 -> bought at 121
    ])
    [t] = engine.trades
    assert (t.entry_fill, t.entry_square, t.stop_loss, t.target) == (121, 121, 100, 169)


def test_opens_above_the_next_square_fills_at_the_open(monkeypatch):
    import sniper_engine as _se
    monkeypatch.setattr(_se, "RETEST_ONLY", False)  # the older buy-stop-at-the-next-square rule
    engine, _ = _run([("09:20", (78, 64, 72, 67)), ("09:25", (104, 71, 101.9, 72)), ("09:30", (135, 125, 130, 126))])
    assert (engine.trades[0].entry_fill, engine.trades[0].entry_square) == (126, 121)


def test_touches_both_with_unknown_order_assumes_the_worse_price(monkeypatch):
    import sniper_engine as _se
    monkeypatch.setattr(_se, "RETEST_ONLY", False)  # the older buy-stop-at-the-next-square rule
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
    # The first-half order is cancelled; 12:00-12:05 is between the halves (owner 13-10: second half from 12:30).
    assert [e.kind for e in events] == ["ORDER", "CANCEL"]
    assert [e.setup.half for e in events] == ["first", "first"]
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


# --- First TSL step on a touch (owner, 2026-10-07) - bought 100 (SL 81, target 144), first square 121 ---------
FILLED_AT_100 = [("09:20", (78.60, 64.05, 72.10, 67.30)), ("09:25", (103.90, 71.40, 101.90, 71.75)),
                 ("09:30", (112.00, 90.45, 107.95, 101.85))]


@pytest.mark.legacy_trailing
def test_touching_the_next_square_moves_the_first_tsl_to_cost():
    engine, _ = _run(FILLED_AT_100 + [("09:35", (125, 105, 110, 108))])  # high 125 >= 121, close 110 < 121
    assert engine.open_trades[0][1].trail_stop == 100


@pytest.mark.legacy_trailing
def test_same_candle_back_to_cost_exits_at_cost():
    # 07-10 NIFTY 22600 PE @ 144: 09:40 high 170 >= 169, low 143.75 -> out at 144.
    engine, events = _run(FILLED_AT_100 + [("09:35", (125, 99, 110, 108))])
    [t] = engine.trades
    assert (t.exit_reason, t.exit_premium, t.pnl_points) == ("TRAIL_STOP", 100, 0)


@pytest.mark.legacy_trailing
def test_later_steps_still_need_a_close():
    engine, _ = _run(FILLED_AT_100 + [("09:35", (125, 105, 120, 108)), ("09:40", (140, 115, 130, 120))])
    assert engine.open_trades[0][1].trail_stop == 100  # 09:40 touched 144? no; closed 130 < 144 -> still 100


def test_first_touch_and_target_in_one_candle_books_the_target():
    engine, _ = _run(FILLED_AT_100 + [("09:35", (150, 99, 110, 108))])
    assert (engine.trades[0].exit_reason, engine.trades[0].exit_premium) == ("TARGET", 144)


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


def test_06_10_sensex_72500ce_near_the_atm_ce_close_with_the_index_below(monkeypatch):
    """Real 72500 CE candles: 09:25 closes 417.20 (11.60 under 428.80), index below 72382.47 -> buy stop 441;
    09:30 high 458 -> bought 441 (low 408.9 stays above SL 400); 09:55 high 559.5 -> target 529."""
    import sniper_engine as _se
    monkeypatch.setattr(_se, "FIRST_CANDLE_BREAK", False)  # tests the trigger, not the 15-10 first-candle rule
    monkeypatch.setattr(_se, "RETEST_ONLY", False)  # the older buy-stop-at-the-next-square rule
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


def test_close_above_the_atm_close_signals_without_the_index(monkeypatch):
    import sniper_engine as _se
    monkeypatch.setattr(_se, "FIRST_CANDLE_BREAK", False)  # tests the trigger, not the 15-10 first-candle rule
    engine, events = _run_sensex([("09:25", (435, 420, 432.0, 425))], index_close=72450)
    assert [e.kind for e in events] == ["ORDER"]
    assert (events[0].atm_close_trigger, events[0].near, events[0].next_square) == (428.80, False, 441)


def test_atm_close_trigger_does_not_need_the_atm_below_the_sniper(monkeypatch):
    import sniper_engine as _se
    monkeypatch.setattr(_se, "FIRST_CANDLE_BREAK", False)  # tests the trigger, not the 15-10 first-candle rule
    # Owner, 07-10: below the Sniper is good (HIGH tag), not required. ATM PE 420 > Sniper 404.70, still falling.
    engine, events = _run_sensex([("09:25", (435, 420, 432.0, 425))], atm_pe_close=420)
    assert [e.kind for e in events] == ["ORDER"]
    assert (events[0].atm_close_trigger, events[0].atm_below_sniper) == (428.80, False)


def test_atm_close_trigger_is_first_half_only():
    engine, events = _run_sensex([("12:10", (435, 420, 432.0, 425))])
    assert all(e.atm_close_trigger == 0 for e in events)


def test_atm_below_sniper_early_then_otm_above_yesterday_high_buys_the_upcoming_square():
    """Owner, 08-10: ATM CE opened below the Sniper -> OTM PE closing above its yesterday high (150) -> buy stop
    at the upcoming square 169, SL 144, target 225."""
    from datetime import date, datetime
    from sniper_engine import Bar, SniperDay
    from sniper_signal import MARKETS, build_daily_plan
    closes = {(22600, "CE"): 132.60, (22600, "PE"): 141.70, (22700, "CE"): 87.15, (22500, "PE"): 98.60}
    row = build_daily_plan(22603, MARKETS["NIFTY"], lambda k, t: closes[(k, t)]).final  # Sniper 92.88
    day = SniperDay(date(2026, 10, 8), row)
    day.otm_yesterday_high = {"otm_pe": 150.0, "otm_ce": 200.0}
    at = lambda hm: datetime(2026, 10, 8, int(hm[:2]), int(hm[3:]))
    flat_ce = Bar(90, 80, 85, 88)
    day.on_candle(at("09:15"), {"atm_ce": Bar(95, 85, 88, 90), "atm_pe": Bar(190, 170, 185, 172),
                                "otm_ce": flat_ce, "otm_pe": Bar(140, 120, 135, 125)})  # ATM CE opens 90 < 92.88
    assert "atm_ce" in day.early_below_sniper
    events = day.on_candle(at("09:30"), {"atm_ce": Bar(80, 70, 72, 78), "atm_pe": Bar(200, 185, 198, 186),
                                         "otm_ce": flat_ce, "otm_pe": Bar(158, 140, 156, 141)})  # 156 > 150
    order = [e for e in events if e.kind == "ORDER"][0]
    assert order.setup.buy_type == "PE" and order.square == 0 and order.next_square == 169


def test_first_half_no_trade_while_the_otm_is_below_its_own_close():
    """Owner, 08-10 (point 4): ATM CE below its close and the Sniper, but OTM PE below ITS close -> no trade."""
    from datetime import date, datetime
    from sniper_engine import Bar, SniperDay
    from sniper_signal import MARKETS, build_daily_plan
    closes = {(22600, "CE"): 132.60, (22600, "PE"): 141.70, (22700, "CE"): 87.15, (22500, "PE"): 98.60}
    row = build_daily_plan(22603, MARKETS["NIFTY"], lambda k, t: closes[(k, t)]).final
    day = SniperDay(date(2026, 10, 8), row)
    at = lambda hm: datetime(2026, 10, 8, int(hm[:2]), int(hm[3:]))
    events = day.on_candle(at("09:30"), {"atm_ce": Bar(95, 85, 88, 94), "atm_pe": Bar(150, 140, 148, 141),
                                         "otm_ce": Bar(90, 80, 88, 85), "otm_pe": Bar(98, 90, 95, 92)})  # 95 < 98.60
    assert events == []


def test_sideways_day_uv_trade_on_the_atm_after_reversal_and_retest(monkeypatch):
    """Owner, 08-10: all 4 below their closes -> ATM PE Bullish Engulfing, then a green candle retesting its low
    -> buy the ATM PE at the confirmation candle's Fib 0.618."""
    from datetime import date, datetime
    from sniper_engine import Bar, SniperDay
    from sniper_signal import MARKETS, build_daily_plan
    closes = {(22600, "CE"): 132.60, (22600, "PE"): 141.70, (22700, "CE"): 87.15, (22500, "PE"): 98.60}
    row = build_daily_plan(22603, MARKETS["NIFTY"], lambda k, t: closes[(k, t)]).final
    day = SniperDay(date(2026, 10, 8), row)
    at = lambda hm: datetime(2026, 10, 8, int(hm[:2]), int(hm[3:]))
    ce, oce, ope = Bar(120, 110, 112, 118), Bar(80, 70, 72, 78), Bar(90, 80, 85, 88)  # all below their closes
    day.on_candle(at("09:30"), {"atm_ce": ce, "atm_pe": Bar(140, 125, 126, 139), "otm_ce": oce, "otm_pe": ope})  # red
    day.on_candle(at("09:35"), {"atm_ce": ce, "atm_pe": Bar(141, 124, 140.5, 125), "otm_ce": oce, "otm_pe": ope})  # engulfing
    assert day.uv_pattern["atm_pe"][3] == "Bullish Engulfing"
    events = day.on_candle(at("09:40"), {"atm_ce": ce, "atm_pe": Bar(141, 125, 140, 127), "otm_ce": oce, "otm_pe": ope})
    order = events[0]
    assert order.kind == "ORDER" and order.setup.contract == "atm_pe" and (order.square, order.next_square) == (121, 144)
    # Fib 0.618 of the confirmation candle (125 -> 141): 141 - 0.618 x 16 = 131.11 -> filled when it comes back
    events = day.on_candle(at("09:45"), {"atm_ce": ce, "atm_pe": Bar(138, 130, 135, 137), "otm_ce": oce, "otm_pe": ope})
    trade = events[0].trade
    assert (trade.entry_fill, trade.stop_loss, trade.target) == (131.11, 121, 169)  # owner 09-10: SL = square below
    # 144 touched, the NEXT candle closes above 144 -> TSL 144; then 169 -> exit at the target
    day.on_candle(at("09:50"), {"atm_ce": ce, "atm_pe": Bar(145, 133, 138, 135), "otm_ce": oce, "otm_pe": ope})
    assert trade.trail_stop == 121
    day.on_candle(at("09:55"), {"atm_ce": ce, "atm_pe": Bar(150, 137, 146, 138), "otm_ce": oce, "otm_pe": ope})
    assert trade.trail_stop == 144
    day.on_candle(at("10:00"), {"atm_ce": ce, "atm_pe": Bar(170, 146, 165, 146), "otm_ce": oce, "otm_pe": ope})
    assert trade.exit_reason == "TARGET" and trade.exit_premium == 169



@pytest.mark.ride
def test_buyers_day_rides_past_the_target_with_the_trailing_sl():
    """Owner, 09-10: not a buyer's day -> the target doesn't exit; the trailing SL does."""
    from sniper_engine import Bar, SniperDay
    from sniper_signal import MARKETS, build_daily_plan
    closes = {(22600, "CE"): 132.60, (22600, "PE"): 141.70, (22700, "CE"): 87.15, (22500, "PE"): 98.60}
    row = build_daily_plan(22603, MARKETS["NIFTY"], lambda k, t: closes[(k, t)]).final
    day = SniperDay(date(2026, 10, 9), row)
    day.buyers_day = True  # owner 12-10: riding is for buyer's days
    at = lambda hm: datetime(2026, 10, 9, int(hm[:2]), int(hm[3:]))
    ce = Bar(140, 130, 132, 135)
    day.on_candle(at("09:30"), {"atm_ce": Bar(130, 120, 125, 128), "atm_pe": Bar(150, 140, 148, 141),
                                "otm_ce": Bar(90, 80, 85, 88), "otm_pe": Bar(150, 120, 149, 125)})  # signal > 132.60
    events = day.on_candle(at("09:35"), {"atm_ce": Bar(126, 118, 120, 125), "atm_pe": Bar(155, 145, 150, 148),
                                         "otm_ce": Bar(85, 80, 82, 85), "otm_pe": Bar(170, 140, 165, 149)})
    trade = next(e.trade for e in events if e.kind == "ENTRY")
    events = day.on_candle(at("09:40"), {"atm_ce": Bar(120, 110, 112, 120), "atm_pe": Bar(170, 150, 168, 150),
                                         "otm_ce": Bar(82, 75, 78, 82), "otm_pe": Bar(trade.target + 20, trade.target - 5, trade.target + 10, 165)})
    assert trade.exit_reason == ""  # went through the target, still open
    # owner 13-10: 2 squares reached -> SL one square above the entry; a later candle CLOSING above the target -> target
    assert trade.trail_stop == (int(trade.entry_square ** 0.5) + 1) ** 2
    day.on_candle(at("09:45"), {"atm_ce": Bar(120, 110, 112, 120), "atm_pe": Bar(170, 150, 168, 150),
                                "otm_ce": Bar(82, 75, 78, 82), "otm_pe": Bar(trade.target + 15, trade.target - 2, trade.target + 5, trade.target)})
    assert trade.trail_stop == trade.target
    events = day.on_candle(at("09:50"), {"atm_ce": Bar(120, 110, 112, 120), "atm_pe": Bar(170, 150, 168, 150),
                                         "otm_ce": Bar(82, 75, 78, 82), "otm_pe": Bar(trade.target + 5, trade.target - 10, trade.target - 3, trade.target + 5)})
    assert trade.exit_reason == "TRAIL_STOP" and trade.pnl_points > 0



@pytest.mark.ride
def test_buyers_day_each_square_touched_past_the_target_moves_the_tsl():
    """Owner, 12-10: entry 144 - nothing until 196 (2 squares): 196 touched -> SL 144; a later candle above 196 ->
    SL 169; 225 touched -> SL 196; the exit needs a body close below the SL."""
    from sniper_engine import Bar, SniperDay
    from sniper_signal import MARKETS, build_daily_plan
    closes = {(22600, "CE"): 132.60, (22600, "PE"): 141.70, (22700, "CE"): 87.15, (22500, "PE"): 98.60}
    row = build_daily_plan(22603, MARKETS["NIFTY"], lambda k, t: closes[(k, t)]).final
    day = SniperDay(date(2026, 10, 9), row)
    day.buyers_day = True  # owner 12-10: riding is for buyer's days
    at = lambda hm: datetime(2026, 10, 9, int(hm[:2]), int(hm[3:]))
    other = {"atm_ce": Bar(126, 118, 120, 125), "atm_pe": Bar(155, 145, 150, 148), "otm_ce": Bar(85, 80, 82, 85)}
    day.on_candle(at("09:30"), {**other, "atm_ce": Bar(130, 120, 125, 128), "otm_pe": Bar(150, 120, 149, 125)})
    events = day.on_candle(at("09:35"), {**other, "otm_pe": Bar(150, 143, 148, 149)})
    trade = next(e.trade for e in events if e.kind == "ENTRY")
    assert (trade.entry_square, trade.target) == (144, 196)
    day.on_candle(at("09:40"), {**other, "otm_pe": Bar(197, 175, 196.5, 150)})   # touches 196 -> SL 169 (1 square)
    assert trade.trail_stop == 169 and trade.exit_reason == ""
    day.on_candle(at("09:45"), {**other, "otm_pe": Bar(226, 197, 210, 196.5)})   # later candle, 225 touched -> SL 196
    assert trade.trail_stop == 196 and trade.exit_reason == ""
    day.on_candle(at("09:50"), {**other, "otm_pe": Bar(212, 190, 192, 210)})     # body closes below 196 -> out at 192
    assert trade.exit_reason == "TRAIL_STOP" and trade.pnl_points == 48



def test_sideways_day_trades_only_the_atm(monkeypatch):
    """Owner, 09-10: sideways day - no OTM trade; the U/V setup's order is for the ATM."""
    from sniper_engine import Bar, SniperDay
    from sniper_signal import MARKETS, build_daily_plan
    closes = {(22600, "CE"): 132.60, (22600, "PE"): 141.70, (22700, "CE"): 87.15, (22500, "PE"): 98.60}
    row = build_daily_plan(22603, MARKETS["NIFTY"], lambda k, t: closes[(k, t)]).final
    day = SniperDay(date(2026, 10, 8), row)
    at = lambda hm: datetime(2026, 10, 8, int(hm[:2]), int(hm[3:]))
    ce, oce, ope = Bar(120, 110, 112, 118), Bar(80, 70, 72, 78), Bar(90, 80, 85, 88)
    events = []
    for t, pe in (("09:30", Bar(140, 125, 126, 139)), ("09:35", Bar(141, 124, 140.5, 125)), ("09:40", Bar(141, 125, 140, 127))):
        events += day.on_candle(at(t), {"atm_ce": ce, "atm_pe": pe, "otm_ce": oce, "otm_pe": ope})
    assert [e.setup.contract for e in events if e.kind == "ORDER"] == ["atm_pe"]



def test_12_10_sensex_529_tsl_only_after_two_squares():
    """Owner, 12-10: 72500 PE bought 529, SL 484 - 591 (only 1 square) moves nothing; the 09:55 wick to 498 closed
    525.35 > 484 -> still in; 625 touched -> SL 529; a later candle above 625 -> SL 576."""
    from sniper_engine import Bar, SniperDay, TradeResult
    from sniper_signal import MARKETS, build_daily_plan
    closes = {(72600, "CE"): 496.50, (72600, "PE"): 459.90, (72700, "CE"): 442.45, (72500, "PE"): 418.55,
              (72500, "CE"): 554.45, (72400, "PE"): 378.00, (72700, "PE"): 505.75, (72800, "CE"): 391.80}
    row = build_daily_plan(72472.3, MARKETS["SENSEX"], lambda k, t: closes.get((k, t), 1.0)).final
    day = SniperDay(date(2026, 10, 12), row)
    day.buyers_day = True
    at = lambda hm: datetime(2026, 10, 12, int(hm[:2]), int(hm[3:]))
    other = {"atm_ce": Bar(400, 380, 390, 395), "atm_pe": Bar(600, 560, 590, 565), "otm_ce": Bar(300, 280, 290, 295)}
    setup = next(s for s in day.setups if s.half == "first" and s.buy_type == "PE")
    day._open(setup, 23, at("09:40"), 529.0, Bar(529.6, 480, 529.6, 513), True)
    trade = day.trades[0]
    assert (trade.stop_loss, trade.target) == (484, 625)
    day.ride_normal_days = True
    day.on_candle(at("09:50"), {**other, "otm_pe": Bar(591.85, 509.9, 591.85, 513.1)})   # 1 square only
    assert trade.trail_stop == 484
    day.on_candle(at("09:55"), {**other, "otm_pe": Bar(600, 498.25, 525.35, 591.85)})   # wick; close above 484
    assert trade.exit_reason == ""
    day.on_candle(at("10:40"), {**other, "otm_pe": Bar(630, 590, 600, 595)})             # 625 touched -> SL 576
    assert trade.trail_stop == 576 and trade.exit_reason == ""
    day.on_candle(at("10:45"), {**other, "otm_pe": Bar(640, 600, 632, 600)})             # later candle CLOSES above 625
    assert trade.trail_stop == 625  # owner 13-10: 2 squares locked


@pytest.mark.ride
def test_no_reentry_in_the_same_half_on_the_same_signal_13_10():
    """Owner, 13-10: after an exit, the same morning signal must not buy again in that half."""
    from sniper_engine import Bar, SniperDay
    from sniper_signal import MARKETS, build_daily_plan
    closes = {(22600, "CE"): 132.60, (22600, "PE"): 141.70, (22700, "CE"): 87.15, (22500, "PE"): 98.60}
    row = build_daily_plan(22603, MARKETS["NIFTY"], lambda k, t: closes[(k, t)]).final
    day = SniperDay(date(2026, 10, 13), row)
    day.buyers_day = True
    at = lambda hm: datetime(2026, 10, 13, int(hm[:2]), int(hm[3:]))
    other = {"atm_ce": Bar(126, 118, 120, 125), "atm_pe": Bar(155, 145, 150, 148), "otm_ce": Bar(85, 80, 82, 85)}
    day.on_candle(at("09:30"), {**other, "atm_ce": Bar(130, 120, 125, 128), "otm_pe": Bar(150, 120, 149, 125)})
    day.on_candle(at("09:35"), {**other, "otm_pe": Bar(150, 143, 148, 149)})            # bought 144
    day.on_candle(at("09:40"), {**other, "otm_pe": Bar(149, 110, 112, 148)})            # closes below SL 121 -> out
    assert day.trades[0].exit_reason == "STOPLOSS"
    events = day.on_candle(at("09:45"), {**other, "otm_pe": Bar(160, 140, 158, 140)})   # back above the trigger, no 0.618 pull-back
    assert not [e for e in events if e.kind in ("ORDER", "ENTRY")]


@pytest.mark.ride
def test_reentry_at_the_0618_pullback_of_the_previous_move(monkeypatch):
    """Owner, 13-10: after an exit, draw the Fib from the move's low to its high - a pull-back to 0.618 re-enters."""
    import sniper_engine as _se
    monkeypatch.setattr(_se, "SECOND_ENTRY_PM_REVERSAL", False)  # the 0.618 mechanics; the 12:30 rule has its own test
    from sniper_engine import Bar, SniperDay
    from sniper_signal import MARKETS, build_daily_plan
    closes = {(22600, "CE"): 132.60, (22600, "PE"): 141.70, (22700, "CE"): 87.15, (22500, "PE"): 98.60}
    row = build_daily_plan(22603, MARKETS["NIFTY"], lambda k, t: closes[(k, t)]).final
    day = SniperDay(date(2026, 10, 13), row)
    day.buyers_day = True
    at = lambda hm: datetime(2026, 10, 13, int(hm[:2]), int(hm[3:]))
    other = {"atm_ce": Bar(126, 118, 120, 125), "atm_pe": Bar(155, 145, 150, 148), "otm_ce": Bar(85, 80, 82, 85)}
    day.on_candle(at("09:30"), {**other, "atm_ce": Bar(130, 120, 125, 128), "otm_pe": Bar(150, 120, 149, 125)})
    day.on_candle(at("09:35"), {**other, "otm_pe": Bar(150, 140, 148, 149)})            # bought 144, low 140
    day.on_candle(at("09:40"), {**other, "otm_pe": Bar(240, 147, 230, 148)})            # runs to 240
    day.on_candle(at("09:45"), {**other, "otm_pe": Bar(231, 160, 165, 230)})            # trail exit on the close
    assert day.trades[0].exit_reason in ("TRAIL_STOP", "STOPLOSS")
    level = 140 + 0.618 * (240 - 140)  # 201.8 - owner 13-10: 0.618 measured up from the low
    events = day.on_candle(at("09:50"), {**other, "otm_pe": Bar(219, 199, 204, 216)})   # tests 0.618, red - no entry
    assert not [e for e in events if e.kind == "ENTRY"]
    events = day.on_candle(at("09:55"), {**other, "otm_pe": Bar(220, 200, 218, 205)})   # green without a reversal first
    assert not [e for e in events if e.kind == "ENTRY"]
    events = day.on_candle(at("10:00"), {**other, "otm_pe": Bar(210.5, 194, 209.5, 209)})  # Hammer = reversal
    assert not [e for e in events if e.kind == "ENTRY"]
    events = day.on_candle(at("10:05"), {**other, "otm_pe": Bar(219, 208, 216, 210)})   # confirmation, closes green above 201.8
    entries = [e for e in events if e.kind == "ENTRY"]
    assert entries and entries[0].trade.entry_fill == 216
    assert entries[0].trade.stop_loss == 191  # owner 13-10: re-entry SL = buy - 25
    # owner 13-10: every entry and exit has a reason
    assert "0.618 = 201.80" in entries[0].trade.entry_reason and "Hammer" in entries[0].trade.entry_reason
    assert day.trades[0].entry_reason and "closed 165" in day.trades[0].exit_detail


@pytest.mark.ride
def test_second_entry_only_from_1230_with_reversal_sl_under_its_low():
    """Owner, 13-10 (all bots): after the morning trade, one more entry - only from 12:30, reversal + green
    confirmation, SL = the reversal low - 1."""
    from sniper_engine import Bar, SniperDay
    from sniper_signal import MARKETS, build_daily_plan
    closes = {(22600, "CE"): 132.60, (22600, "PE"): 141.70, (22700, "CE"): 87.15, (22500, "PE"): 98.60}
    row = build_daily_plan(22603, MARKETS["NIFTY"], lambda k, t: closes[(k, t)]).final
    day = SniperDay(date(2026, 10, 13), row)
    day.buyers_day = True
    at = lambda hm: datetime(2026, 10, 13, int(hm[:2]), int(hm[3:]))
    other = {"atm_ce": Bar(126, 118, 120, 125), "atm_pe": Bar(155, 145, 150, 148), "otm_ce": Bar(85, 80, 82, 85)}
    day.on_candle(at("09:30"), {**other, "atm_ce": Bar(130, 120, 125, 128), "otm_pe": Bar(150, 120, 149, 125)})
    day.on_candle(at("09:35"), {**other, "otm_pe": Bar(150, 140, 148, 149)})
    day.on_candle(at("09:40"), {**other, "otm_pe": Bar(240, 147, 230, 148)})
    day.on_candle(at("09:45"), {**other, "otm_pe": Bar(231, 160, 165, 230)})
    assert len(day.trades) == 1 and day.trades[0].exit_reason
    # morning: 0.618 (201.8) tested, Hammer, green confirmation - but before 12:30 -> no entry
    day.on_candle(at("09:50"), {**other, "otm_pe": Bar(219, 199, 204, 216)})
    day.on_candle(at("09:55"), {**other, "otm_pe": Bar(220, 200, 218, 205)})
    day.on_candle(at("10:00"), {**other, "otm_pe": Bar(210.5, 194, 209.5, 209)})
    events = day.on_candle(at("10:05"), {**other, "otm_pe": Bar(219, 208, 216, 210)})
    assert not [e for e in events if e.kind == "ENTRY"]
    # 12:20 Hammer, 12:25 green confirmation (closes 12:30) -> entry, SL = 196 - 1
    day.on_candle(at("12:20"), {**other, "otm_pe": Bar(210.5, 196, 209.5, 209)})
    events = day.on_candle(at("12:25"), {**other, "otm_pe": Bar(219, 208, 216, 210)})
    entries = [e for e in events if e.kind == "ENTRY"]
    assert entries and entries[0].trade.entry_fill == 216 and entries[0].trade.stop_loss == 195


def test_retest_only_buys_the_square_when_it_comes_back():
    """Owner, 15-10 (14-10 SENSEX 73100 PE: bought 441 on a touch, the candle closed 416.40): retest only - the candle
    touching both the square (100) and the next one (121) fills at the square."""
    engine, _ = _run([("09:20", (78, 64, 72, 67)), ("09:25", (104, 71, 101.9, 72)), ("09:30", (125, 95, 110, 105))])
    assert (engine.trades[0].entry_fill, engine.trades[0].entry_square) == (100, 100)


def test_retest_only_never_chases_the_next_square(monkeypatch):
    import sniper_engine as _se
    monkeypatch.setattr(_se, "MOMENTUM_ENTRY", False)  # the retest alone (momentum has its own test)
    engine, events = _run([("09:20", (78, 64, 72, 67)), ("09:25", (104, 71, 101.9, 72)), ("09:30", (125, 102, 124, 105)),
                           ("09:35", (130, 119, 125, 124))])
    assert not engine.trades and [e.kind for e in events] == ["ORDER"]


def test_no_entry_until_the_index_closes_beyond_its_first_5_minute_candle():
    """Owner, 15-10: until an index candle closes above the first 5-minute candle's high, the market is sideways for
    a CE (up) setup - no signal; after that close the market has started."""
    engine = SniperDay(date(2026, 10, 6), SENSEX_ROW, index_close=72382.47, near_points=30)
    feed = lambda hhmm, ce, ix: engine.on_candle(_at(hhmm), {**_sensex_bars(ce), "index": Bar(*ix)})
    assert feed("09:15", (400, 390, 395, 392), (72500, 72400, 72450, 72420)) == []      # the first candle
    assert feed("09:20", (435, 420, 432, 425), (72495, 72440, 72480, 72450)) == []      # inside it - sideways
    events = feed("09:25", (435, 420, 432, 425), (72530, 72470, 72520, 72480))          # closes above 72500
    assert [e.kind for e in events] == ["ORDER"]


def test_momentum_signal_above_the_square_buys_the_next_one():
    """Owner, 15-10 (SENSEX 72800 CE: 09:25 closed 527.80 above 484, the 09:30 candle ran through 529): momentum - the
    market has started, the ATM is below its close and the Sniper -> buy at the next square (121) when it trades
    there from 09:30; SL 100, target 169."""
    engine, events = _run([("09:20", (78, 64, 72, 67)), ("09:25", (104, 71, 101.9, 72)), ("09:30", (125, 102, 124, 105))])
    [t] = engine.trades
    assert (t.entry_fill, t.stop_loss, t.target) == (121, 100, 169)
    assert "momentum" in t.entry_reason


@pytest.mark.ride
def test_every_day_rides_past_the_target_with_the_square_tsl():
    """Owner, 15-10: all Sniper trades, all days - no exit at 2 squares; the ladder locks profit and the TSL rides."""
    engine, events = _run([("09:20", (78, 64, 72, 67)), ("09:25", (104, 71, 101.9, 72)), ("09:30", (125, 102, 124, 105)),
                           ("09:35", (170, 150, 165, 160))])
    assert not engine.buyers_day
    [t] = engine.trades
    assert not t.exit_reason and t.trail_stop == 144  # 169 (2 squares) touched -> SL 144, still riding


@pytest.mark.ride
def test_entry_candle_close_does_not_move_the_sl():
    """16-10 SENSEX 74100 CE: bought 841, the entry candle closed 918.75 and the old close-trail put the SL at 841.
    With the square ladder nothing moves until 2 squares."""
    engine, _ = _run([("09:20", (78, 64, 72, 67)), ("09:25", (104, 71, 101.9, 72)), ("09:30", (150, 102, 148, 105))])
    [t] = engine.trades
    assert (t.entry_fill, t.stop_loss, t.trail_stop) == (121, 100, 100)
