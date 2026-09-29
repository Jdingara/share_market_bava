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


def test_gap_down_buys_pe_at_0930_and_exits_at_the_last_level():
    day = HlcDay(date(2026, 9, 29), LEVELS, HLC_MARKETS["NIFTY"])
    day.on_candle(_at("09:15"), Candle(22732.45, 22753, 22680, 22684), _chain((60, 62, 55, 58)))
    day.on_candle(_at("09:20"), Candle(22683, 22686, 22656, 22667), _chain((58, 66, 57, 65)))
    events = day.on_candle(_at("09:25"), Candle(22667, 22668, 22624, 22624.2), _chain((65, 74, 64, 72.55)))
    assert events and events[0].startswith("BUY PE 22800 at 72.55 (GAP")  # our ATM, not the balanced 22650
    t = day.open_trade
    assert (t.sl_premium, [n for n, _ in t.targets]) == (47.55, ["S3"])  # 72.55 - 25
    day.on_candle(_at("09:30"), Candle(22624, 22638, 22611, 22620), _chain((72, 80, 70, 78)))
    events = day.on_candle(_at("09:35"), Candle(22619, 22619.5, 22569.7, 22577.3), _chain((78, 110, 77, 104.3)))
    assert "TARGET S3" in events[0]
    assert (t.exit_premium, t.pnl_points) == (104.3, pytest.approx(31.75))


def test_breaking_a_level_moves_the_sl_to_it():
    day = HlcDay(date(2026, 9, 29), LEVELS, HLC_MARKETS["NIFTY"])
    day.on_candle(_at("09:20"), Candle(22760, 22762, 22740, 22745), _chain((60, 62, 55, 58)))  # opens below 22780.25
    day.on_candle(_at("09:25"), Candle(22745, 22750, 22735, 22740), _chain((58, 66, 57, 60)))  # GAP PE, targets S1..S3
    t = day.open_trade
    assert [n for n, _ in t.targets] == ["S1", "S2", "S3"]
    events = day.on_candle(_at("09:30"), Candle(22740, 22741, 22700, 22705), _chain((60, 75, 59, 74)))  # closes below S1
    assert "S1 22728.5 broken" in events[0] and t.trail_level[0] == "S1"
    events = day.on_candle(_at("09:35"), Candle(22705, 22740, 22700, 22735), _chain((74, 76, 62, 63)))  # back above S1 (SL 35 not hit)
    assert "closed back across S1" in events[0] and t.pnl_points == pytest.approx(3)


def test_big_gap_uses_the_strike_near_the_market_and_exits_when_the_pattern_turns():
    day = HlcDay(date(2026, 9, 29), LEVELS, HLC_MARKETS["NIFTY"])
    chain = lambda pe: {(22600.0, "CE"): Candle(40, 42, 38, 41), (22600.0, "PE"): Candle(*pe),
                        (22800.0, "CE"): Candle(5, 6, 4, 5), (22800.0, "PE"): Candle(190, 195, 185, 190)}
    day.on_candle(_at("09:15"), Candle(22610, 22620, 22590, 22600), chain((50, 52, 48, 50)))  # opens 170 below 22780.25
    events = day.on_candle(_at("09:25"), Candle(22600, 22605, 22595, 22598), chain((50, 60, 49, 58)))
    assert day.big_gap and events[0].startswith("BUY PE 22600 at 58.00 (GAP, BIG gap down")
    day.on_candle(_at("09:30"), Candle(22598, 22600, 22580, 22585), chain((58, 66, 57, 65)))  # red, nothing
    events = day.on_candle(_at("09:35"), Candle(22584, 22603, 22583, 22602), chain((65, 66, 58, 59)))  # bullish engulfing
    assert "pattern turned: index Bullish Engulfing" in events[0]
    assert day.trades[0].pnl_points == pytest.approx(1)


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
