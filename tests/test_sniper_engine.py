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


# --- First TSL step on a touch (owner, 2026-10-07) - bought 100 (SL 81, target 144), first square 121 ---------
FILLED_AT_100 = [("09:20", (78.60, 64.05, 72.10, 67.30)), ("09:25", (103.90, 71.40, 101.90, 71.75)),
                 ("09:30", (112.00, 90.45, 107.95, 101.85))]


def test_touching_the_next_square_moves_the_first_tsl_to_cost():
    engine, _ = _run(FILLED_AT_100 + [("09:35", (125, 105, 110, 108))])  # high 125 >= 121, close 110 < 121
    assert engine.open_trades[0][1].trail_stop == 100


def test_same_candle_back_to_cost_exits_at_cost():
    # 07-10 NIFTY 22600 PE @ 144: 09:40 high 170 >= 169, low 143.75 -> out at 144.
    engine, events = _run(FILLED_AT_100 + [("09:35", (125, 99, 110, 108))])
    [t] = engine.trades
    assert (t.exit_reason, t.exit_premium, t.pnl_points) == ("TRAIL_STOP", 100, 0)


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


def test_atm_close_trigger_does_not_need_the_atm_below_the_sniper():
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


def test_sideways_day_uv_trade_on_the_atm_after_reversal_and_retest():
    """Owner, 08-10: all 4 below their closes -> ATM PE Bullish Engulfing, then a green candle retesting its low
    -> buy the ATM PE at the square (limit 144 / stop 169)."""
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
    assert (trade.entry_fill, trade.stop_loss, trade.target) == (131.11, 100, 169)



@pytest.mark.ride
def test_normal_day_rides_past_the_target_with_the_trailing_sl():
    """Owner, 09-10: not a buyer's day -> the target doesn't exit; the trailing SL does."""
    from sniper_engine import Bar, SniperDay
    from sniper_signal import MARKETS, build_daily_plan
    closes = {(22600, "CE"): 132.60, (22600, "PE"): 141.70, (22700, "CE"): 87.15, (22500, "PE"): 98.60}
    row = build_daily_plan(22603, MARKETS["NIFTY"], lambda k, t: closes[(k, t)]).final
    day = SniperDay(date(2026, 10, 9), row)
    assert day.ride_normal_days and not day.buyers_day
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
    # owner 09-10: reaching the target moved the TSL to one square above the entry -> a later drop exits in profit
    locked = (int(trade.entry_square ** 0.5) + 1) ** 2
    assert trade.trail_stop >= locked
    events = day.on_candle(at("09:45"), {"atm_ce": Bar(120, 110, 112, 120), "atm_pe": Bar(170, 150, 168, 150),
                                         "otm_ce": Bar(82, 75, 78, 82), "otm_pe": Bar(trade.target, locked - 10, locked - 5, trade.target)})
    assert trade.exit_reason == "TRAIL_STOP" and trade.pnl_points > 0
