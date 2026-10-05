"""HLC strategy: the owner's 29-09 sheet, ATM choice, labels, patterns, and the engine's trade flow."""

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hlc_engine import HlcDay
from hlc_signal import (HLC_MARKETS, Candle, bearish_pattern, bullish_pattern, choose_atm, hlc_levels,
                        is_hammer, leg_label)


def test_levels_match_owners_sheet():
    n = hlc_levels(22780.25, 22800, 84.20, 71.45)
    assert (n.r1, n.r2, n.r3) == (22884.20, 22955.65, 23039.85)
    assert (n.s1, n.s2, n.s3) == (22728.55, 22644.35, 22572.90)
    s = hlc_levels(72771.72, 72900, 444.20, 402.10)
    assert (s.r1, s.r2, s.r3) == (73344.20, 73746.30, 74190.50)
    assert (s.s1, s.s2, s.s3) == (72497.90, 72053.70, 71651.60)


def test_atm_is_the_strike_with_ce_and_pe_nearest():
    sensex = {(72800, "CE"): 500.40, (72800, "PE"): 357.85, (72900, "CE"): 444.20, (72900, "PE"): 402.10,
              (73000, "CE"): 394.35, (73000, "PE"): 449.95}
    assert choose_atm(72771.72, 100, lambda k, t: sensex.get((k, t))) == 72900  # gap 42 beats 142 and 56
    owners_example = {(23100, "CE"): 150, (23100, "PE"): 225, (23150, "CE"): 165, (23150, "PE"): 175}
    assert choose_atm(23080, 50, lambda k, t: owners_example.get((k, t))) == 23150


def test_labels():
    assert leg_label(298.5, 77.05, 84.20) == "PROFIT BOOKING"
    assert leg_label(94, 8.4, 71.45) == "PANIC"
    assert leg_label(800, 416.7, 444.20) == "PROFIT BOOKING"
    assert leg_label(448, 105, 402.10) == "PANIC"


def test_patterns():
    assert is_hammer(Candle(22584.8, 22587.7, 22573.0, 22587.5))  # 29-09 10:20 NIFTY at S3
    red, green = Candle(22583.8, 22586.8, 22571.5, 22578.8), Candle(22578.5, 22591.5, 22575.1, 22585.6)
    assert bullish_pattern([red, green]) == ("Bullish Engulfing", 2)  # 29-09 10:10-10:15
    assert bearish_pattern([green, Candle(22586, 22590, 22575, 22577)]) == ("Bearish Engulfing", 2)
    assert bullish_pattern([Candle(100, 101, 90, 91), Candle(91, 92, 89, 90.5), Candle(90.5, 99, 90, 98)])[0] == "Morning Star"


LEVELS = hlc_levels(22780.25, 22800, 84.20, 71.45)


def _at(hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 9, 29, h, m)


def _chain(pe):
    """The morning ATM 22800's CE and PE (PE candle as given), plus a balanced 22650 that must NOT be used."""
    return {(22800.0, "CE"): Candle(20, 22, 18, 21), (22800.0, "PE"): Candle(*pe),
            (22650.0, "CE"): Candle(70, 72, 68, 71), (22650.0, "PE"): Candle(70, 72, 68, 71)}


LEVELS30 = hlc_levels(22716.25, 22800, 156.10, 150.90)  # 30-09-2026 NIFTY (data 29-09)


def _chain30(ce_close=130.0):
    return {(22800.0, "CE"): Candle(ce_close, ce_close + 2, ce_close - 2, ce_close), (22800.0, "PE"): Candle(150, 152, 148, 150)}


def test_fib_trade_30_09_nifty_real_candles():
    """30-09 NIFTY, first candle O 22665 H 22718.45 L 22659.80: low first (up swing) -> 0.75 level from the high
    = 22674.46. The 09:30 candle only dips to 22681.15 and the 09:35 to 22686.70 -> no FIB trade."""
    day = HlcDay(date(2026, 9, 30), LEVELS30, HLC_MARKETS["NIFTY"])
    assert day.on_candle(_at("09:15"), Candle(22665, 22718.45, 22659.8, 22702.7), _chain30()) == []
    assert day.on_candle(_at("09:20"), Candle(22702.85, 22733.35, 22697.2, 22727.95), _chain30()) == []
    assert day.on_candle(_at("09:25"), Candle(22727.8, 22736.65, 22714.45, 22721.65), _chain30()) == []
    assert day.on_candle(_at("09:30"), Candle(22720.4, 22720.4, 22681.15, 22690), _chain30()) == []
    assert day.on_candle(_at("09:35"), Candle(22690.05, 22704.9, 22686.7, 22688), _chain30()) == []


def test_fib_level_follows_the_swing_not_the_side_01_10_sensex():
    """Owner, 01-10: SENSEX first candle L 72187.62 -> H 72450.34 (up swing), index below yesterday's close
    72480.3 -> PE side, level = high - 0.75 x range = 72253.3. The bot had bought PE at low + 0.75 x range
    (72384.66) on the 09:30 candle - wrong. After 09:30 the index only got down to 72307.86 -> no FIB trade."""
    levels = hlc_levels(72480.3, 72500, 232.55, 279.0)
    # CE: a plain red candle - no CE pattern (the real day had CE blocked by the PE PANIC anyway)
    chain = {(72500.0, "CE"): Candle(250, 251, 240, 241), (72500.0, "PE"): Candle(320, 325, 315, 320)}
    day = HlcDay(date(2026, 10, 1), levels, HLC_MARKETS["SENSEX"])
    day.first_swing = "CE"
    candles = [("09:15", (72192.89, 72450.34, 72187.62, 72349.74)), ("09:20", (72342.87, 72374.04, 72223.99, 72239.26)),
               ("09:25", (72227.62, 72323.65, 72224.33, 72316.99)), ("09:30", (72317.48, 72437.65, 72310.38, 72310.38)),
               ("09:35", (72313.42, 72378.43, 72307.86, 72377.54)), ("09:40", (72380.2, 72402.04, 72352.25, 72370.09))]
    for t, c in candles:
        assert not any("FIB" in e for e in day.on_candle(_at(t), Candle(*c), chain))
    assert day.fib_level()[0] == pytest.approx(72253.3, abs=0.05)
    # had it dipped to the level while below yesterday's close -> PE, SL above the first high
    events = day.on_candle(_at("09:45"), Candle(72370, 72375, 72250, 72300), chain)
    assert events[0].startswith("BUY PE 72500") and day.open_trade.index_sl == 72450.34


def test_fib_ce_entry_and_first_low_sl():
    day = HlcDay(date(2026, 9, 30), LEVELS30, HLC_MARKETS["NIFTY"])
    day.on_candle(_at("09:15"), Candle(22665, 22718.45, 22659.8, 22702.7), _chain30())
    day.on_candle(_at("09:20"), Candle(22702.85, 22733.35, 22697.2, 22727.95), _chain30())
    day.on_candle(_at("09:25"), Candle(22727.8, 22736.65, 22714.45, 22721.65), _chain30())
    events = day.on_candle(_at("09:30"), Candle(22720.4, 22720.4, 22672, 22690), _chain30())  # dips to 22674.46
    assert events[0].startswith("BUY CE 22800 at 130.00 (FIB 0.75 of the first candle at 22674.46")
    t = day.open_trade
    assert (t.index_sl, [n for n, _ in t.targets]) == (22659.8, ["R1", "R2"])
    events = day.on_candle(_at("09:35"), Candle(22690, 22700, 22655, 22660), _chain30(110))  # below the first low
    assert "SL (index below first low 22659.8)" in events[0] and t.pnl_points == -20


def test_no_fib_trade_before_0930():
    day = HlcDay(date(2026, 9, 30), LEVELS30, HLC_MARKETS["NIFTY"])
    day.on_candle(_at("09:15"), Candle(22665, 22718.45, 22659.8, 22702.7), _chain30())
    assert day.on_candle(_at("09:20"), Candle(22727, 22733, 22675, 22727.95), _chain30()) == []  # touches 22682 but closes 09:25


def test_pe_fib_trade_trails_through_s1():
    day = HlcDay(date(2026, 9, 29), LEVELS, HLC_MARKETS["NIFTY"])  # close 22780.25, S1 22728.55, S2 22644.35
    day.on_candle(_at("09:15"), Candle(22760, 22770, 22740, 22745), _chain((60, 62, 55, 58)))  # below close -> PE
    day.on_candle(_at("09:20"), Candle(22745, 22750, 22738, 22742), _chain((58, 60, 57, 59)))
    day.on_candle(_at("09:25"), Candle(22742, 22743, 22734, 22735), _chain((59, 60, 58, 59)))  # plain down candle
    events = day.on_candle(_at("09:30"), Candle(22742, 22765, 22740, 22748), _chain((59, 61, 57, 60)))  # up to 22762.5
    t = day.open_trade
    assert "FIB" in events[0] and (t.side, t.index_sl, [n for n, _ in t.targets]) == ("PE", 22770, ["S1", "S2"])
    events = day.on_candle(_at("09:35"), Candle(22748, 22749, 22700, 22705), _chain((60, 75, 59, 74)))  # closes below S1
    assert "S1 22728.5 broken" in events[0] and t.trail_level[0] == "S1"
    events = day.on_candle(_at("09:40"), Candle(22705, 22740, 22700, 22735), _chain((74, 76, 62, 63)))  # back above S1
    assert "closed back across S1" in events[0] and t.pnl_points == 3


def test_big_gap_uses_the_strike_near_the_market_and_exits_when_the_pattern_turns():
    day = HlcDay(date(2026, 9, 29), LEVELS, HLC_MARKETS["NIFTY"])  # close 22780.25, R2 22955.65
    chain = lambda ce: {(22950.0, "CE"): Candle(*ce), (22950.0, "PE"): Candle(40, 42, 38, 40),
                        (22800.0, "CE"): Candle(150, 155, 148, 150), (22800.0, "PE"): Candle(5, 6, 4, 5)}
    day.first_swing = "CE"  # up swing -> level 22947.5
    day.on_candle(_at("09:15"), Candle(22960, 22970, 22940, 22950), chain((60, 62, 55, 58)))  # opens above R2
    day.on_candle(_at("09:20"), Candle(22940, 22945, 22935, 22944), chain((58, 60, 57, 59)))
    day.on_candle(_at("09:25"), Candle(22944, 22946, 22943, 22945), chain((59, 61, 57, 60)))
    events = day.on_candle(_at("09:30"), Candle(22944, 22946, 22936, 22942), chain((59, 61, 57, 60)))  # dips below 22947.5
    assert day.big_gap and events[0].startswith("BUY CE 22950 at 60.00 (FIB")
    day.on_candle(_at("09:35"), Candle(22942, 22950, 22941, 22949), chain((60, 66, 59, 65)))
    events = day.on_candle(_at("09:40"), Candle(22950, 22951, 22941, 22941.5), chain((65, 66, 58, 59)))  # bearish engulfing, above the first low
    assert "pattern turned: index Bearish Engulfing" in events[0]


def test_small_gap_keeps_the_morning_atm():
    day = HlcDay(date(2026, 9, 29), LEVELS, HLC_MARKETS["NIFTY"])
    day.on_candle(_at("09:15"), Candle(22732.45, 22753, 22680, 22684), _chain((60, 62, 55, 58)))  # 48 below
    assert not day.big_gap


def _low_premium_day():
    day = HlcDay(date(2026, 9, 29), LEVELS, HLC_MARKETS["NIFTY"])
    day.gap_done = True  # only the reversal is under test
    day.day_open = 22780.25
    return day


def _ce_chain(ce):
    return {(22800.0, "CE"): Candle(*ce), (22800.0, "PE"): Candle(200, 210, 195, 205)}


def test_low_premium_before_1330_buys_above_the_confirmation_high():
    """29-09 10:15: CE 22800 at 10.00 (10 - 25 < 0) -> buy only if the next candle breaks 10.80; SL under 2 candles."""
    day = _low_premium_day()
    day.on_candle(_at("10:10"), Candle(22583.8, 22586.8, 22571.5, 22578.8), _ce_chain((10.4, 10.9, 9.9, 10.3)))
    events = day.on_candle(_at("10:15"), Candle(22578.5, 22591.5, 22575.1, 22585.6), _ce_chain((10.3, 10.8, 9.65, 10.0)))
    assert events[0].startswith("ORDER CE 22800: low premium 10.00 - buy only above this candle's high 10.80")
    events = day.on_candle(_at("10:20"), Candle(22584.8, 22587.7, 22573.0, 22587.5), _ce_chain((10.0, 11.5, 9.8, 11.2)))
    t = day.open_trade
    assert "BUY CE 22800 at 10.80" in events[0]
    assert (t.entry_fill, t.sl_premium, t.sl_rule) == (10.8, 9.65, "2-candle low")


def test_low_premium_order_not_triggered_is_cancelled():
    day = _low_premium_day()
    day.on_candle(_at("10:10"), Candle(22583.8, 22586.8, 22571.5, 22578.8), _ce_chain((10.4, 10.9, 9.9, 10.3)))
    day.on_candle(_at("10:15"), Candle(22578.5, 22591.5, 22575.1, 22585.6), _ce_chain((10.3, 10.8, 9.65, 10.0)))
    events = day.on_candle(_at("10:20"), Candle(22584.8, 22587.7, 22580, 22583), _ce_chain((10.0, 10.5, 9.5, 9.8)))
    assert "cancelled - not triggered" in events[0] and day.trades == []


def test_low_premium_from_1330_uses_the_day_low_minus_one():
    day = _low_premium_day()
    day.on_candle(_at("13:20"), Candle(22583.8, 22586.8, 22571.5, 22578.8), _ce_chain((10.4, 10.9, 9.9, 10.3)))
    events = day.on_candle(_at("13:25"), Candle(22578.5, 22591.5, 22575.1, 22585.6), _ce_chain((10.3, 10.8, 9.65, 10.0)))
    assert "BUY CE 22800 at 10.00 (REVERSAL" in events[0]  # candle closes 13:30
    assert (day.open_trade.sl_premium, day.open_trade.sl_rule) == (8.65, "day low - 1")


def test_panic_pe_above_yesterdays_high_blocks_ce_trades():
    """29-09: 22800 PE was PANIC (H 94, L 8.4, C 71.45) and hit 133.90 at 09:15 -> no CE trade all day."""
    yday = {"CE": (298.5, 77.05, 84.20), "PE": (94.0, 8.4, 71.45)}
    day = HlcDay(date(2026, 9, 29), LEVELS, HLC_MARKETS["NIFTY"], yday)
    chain = lambda ce, pe: {(22800.0, "CE"): Candle(*ce), (22800.0, "PE"): Candle(*pe)}
    events = day.on_candle(_at("09:15"), Candle(22732.45, 22753, 22680, 22684), chain((26, 44, 25, 26.6), (77, 133.9, 76.5, 132)))
    assert events == ["No CE trades today - PE PANIC yesterday and above its high 94 today"]
    day.gap_done = True
    day.on_candle(_at("10:10"), Candle(22583.8, 22586.8, 22571.5, 22578.8), chain((10.4, 10.9, 9.9, 10.3), (210, 215, 205, 212)))
    day.on_candle(_at("10:15"), Candle(22578.5, 22591.5, 22575.1, 22585.6), chain((10.3, 10.8, 9.65, 10.0), (212, 214, 208, 209)))
    assert day.trades == []  # the S3 Bullish Engulfing CE reversal is blocked


def test_hlc_no_second_trade_after_a_winning_first_trade():
    day = HlcDay(date(2026, 9, 29), LEVELS, HLC_MARKETS["NIFTY"])  # close 22780.25, S1 22728.55, S2 22644.35
    day.on_candle(_at("09:15"), Candle(22760, 22770, 22740, 22745), _chain((60, 62, 55, 58)))
    day.on_candle(_at("09:20"), Candle(22745, 22750, 22738, 22742), _chain((58, 60, 57, 59)))
    day.on_candle(_at("09:25"), Candle(22742, 22743, 22734, 22735), _chain((59, 60, 58, 59)))  # plain down candle
    day.on_candle(_at("09:30"), Candle(22742, 22765, 22740, 22748), _chain((59, 61, 57, 60)))  # FIB PE
    day.on_candle(_at("09:35"), Candle(22748, 22749, 22700, 22705), _chain((60, 75, 59, 74)))  # S1 broken -> trail
    day.on_candle(_at("09:40"), Candle(22705, 22706, 22640, 22650), _chain((74, 95, 73, 90)))  # S2 touched: final target
    assert day.trades[0].exit_reason.startswith("TARGET S2")
    # A textbook S-level reversal afterwards must not open a second trade.
    day.on_candle(_at("09:45"), Candle(22650, 22655, 22640, 22642), _chain((90, 91, 85, 86)))
    day.on_candle(_at("09:50"), Candle(22641, 22660, 22640, 22658), _chain((86, 92, 85, 91)))
    assert len(day.trades) == 1


def test_confirm_trade_index_back_in_the_fib_zone_plus_premium_pattern():
    """Owner, 01-10 ("double confirmation"): PE side, the index comes down into the first candle's Fib
    0.75-0.786 zone (72384.66-72394.12) and the PE premium shows a bullish pattern -> buy, SL -50, S1 -> S2."""
    levels = hlc_levels(72480.3, 72500, 232.55, 279.0)
    day = HlcDay(date(2026, 10, 1), levels, HLC_MARKETS["SENSEX"])
    day.first_swing = "CE"
    ce = Candle(250, 255, 245, 250)
    seq = [("09:15", (72192.89, 72450.34, 72187.62, 72349.74), (300, 305, 295, 300)),
           ("09:20", (72342.87, 72374.04, 72300.0, 72310.0), (300, 302, 290, 295)),
           ("09:25", (72310.0, 72460.0, 72305.0, 72455.0), (295, 296, 240, 240)),   # above the zone, PE falls
           ("09:30", (72455.0, 72470.0, 72440.0, 72450.0), (240, 241, 225, 226)),   # big red PE candle
           ("09:35", (72450.0, 72455.0, 72390.0, 72400.0), (226, 250, 224, 248))]   # into the zone, PE engulfs
    events = []
    for t, idx, pe in seq:
        events = day.on_candle(_at(t), Candle(*idx), {(72500.0, "CE"): ce, (72500.0, "PE"): Candle(*pe)})
    assert events and events[-1].startswith("BUY PE 72500 at 248.00 (CONFIRM")
    t = day.open_trade
    assert t.sl_premium == 198 and [n for n, _ in t.targets] == ["S1", "S2"]


def test_panic_side_premium_targets_staircase_of_earlier_daily_highs():
    """Owner, 01-10: PANIC-side trades also target the option's earlier daily highs, one by one; a close above
    one moves on to the next, a touch without closing above exits."""
    levels = hlc_levels(72480.3, 72500, 232.55, 279.0)
    day = HlcDay(date(2026, 10, 1), levels, HLC_MARKETS["SENSEX"], {"CE": (720, 210.5, 232.55), "PE": (358, 88, 279)})
    day.daily_highs["PE"] = [358, 300, 410, 390, 520]  # yesterday first -> staircase 358, 410, 520
    assert day.premium_ladder("PE", 72500, 250) == [358, 410, 520]
    assert day.premium_ladder("PE", 72500, 400) == [410, 520]
    assert day.premium_ladder("CE", 72500, 100) == []  # CE was PROFIT BOOKING
    assert day.premium_ladder("PE", 72600, 250) == []  # not the morning ATM


def test_reversal_patterns_include_inverted_hammer_piercing_shooting_star_dark_cloud():
    """Owner, 01-10: all reversal patterns for buying - Hammer, Inverted Hammer, both Engulfings, etc."""
    from hlc_signal import bearish_pattern, bullish_pattern
    assert bullish_pattern([Candle(100, 112, 99.5, 102)])[0] == "Inverted Hammer"
    assert bearish_pattern([Candle(100, 112, 99.5, 102)])[0] == "Shooting Star"
    assert bullish_pattern([Candle(110, 111, 99, 100), Candle(99, 108, 98, 107)])[0] == "Piercing Line"
    assert bearish_pattern([Candle(100, 111, 99, 110), Candle(111, 112, 102, 103)])[0] == "Dark Cloud Cover"
    assert bullish_pattern([Candle(110, 111, 99, 100), Candle(99, 113, 98, 112)])[0] == "Bullish Engulfing"
    assert bearish_pattern([Candle(100, 111, 99, 110), Candle(111, 112, 97, 98)])[0] == "Bearish Engulfing"


def test_reversal_at_r1_targets_beyond_r1_not_r1_itself():
    """05-10 NIFTY: a PE reversal at R1 with the index a touch above R1 must target Close, not R1."""
    from hlc_live import _strikes_to_watch
    levels = hlc_levels(22422, 22450, 160.5, 120.3)  # R1 22582.5
    day = HlcDay(date(2026, 10, 5), levels, HLC_MARKETS["NIFTY"])
    assert [n for n, _ in day._targets("PE", 22582.5 - 0.01, "Close")] == ["Close"]
    # every strike the index has been near today stays watched
    rows = [{"low": 72100, "high": 72650}, {"low": 72200, "high": 72300}]
    assert {72000.0, 72600.0, 72700.0} <= _strikes_to_watch(levels, 100, rows)


def test_big_gap_only_when_opening_beyond_r2_or_s2():
    """Owner, 05-10: 431 points up (SENSEX 72341 vs close 71910) is NOT a big gap - it opened below R2 73221.6."""
    levels = hlc_levels(71909.7, 72100, 553.65, 568.0)
    day = HlcDay(date(2026, 10, 5), levels, HLC_MARKETS["SENSEX"])
    day.on_candle(_at("09:15"), Candle(72340.95, 72402.27, 72171.93, 72359.79), {})
    assert not day.big_gap
    day = HlcDay(date(2026, 10, 5), levels, HLC_MARKETS["SENSEX"])
    day.on_candle(_at("09:15"), Candle(73300, 73350, 73250, 73320), {})
    assert day.big_gap
