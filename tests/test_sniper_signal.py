"""Unit tests for sniper_signal.py, anchored on PROJECT_STATUS.md §5's worked example."""

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from options_pricing import next_weekly_expiry
from sniper_signal import (
    MARKETS,
    build_daily_plan,
    entry_window_for,
    is_sideways,
    nearest_atm,
    square_levels,
    trade_setups,
)

NIFTY = MARKETS["NIFTY"]

# PROJECT_STATUS.md §5: data 28-09-2026, NIFTY close 23140.5
WORKED_EXAMPLE_PREMIUMS = {
    (23100, "CE"): 147.40,
    (23100, "PE"): 59.20,
    (23200, "CE"): 89.15,
    (23000, "PE"): 34.25,
    (23300, "CE"): 48.80,
    (23200, "PE"): 99.80,
}


def _lookup(table):
    return lambda strike, option_type: table[(strike, option_type)]


def test_nearest_atm():
    assert nearest_atm(23140.5, 100) == 23100
    assert nearest_atm(23150, 100) == 23200  # exact half rounds up
    assert nearest_atm(23250, 100) == 23300  # not banker's rounding (would give 23200)


def test_worked_example_plan():
    plan = build_daily_plan(23140.5, NIFTY, _lookup(WORKED_EXAMPLE_PREMIUMS))

    first, final = plan.attempts
    assert first.atm_strike == 23100
    assert first.sniper == pytest.approx(61.70)
    assert first.ce_gap == pytest.approx(85.70)
    assert first.pe_gap == pytest.approx(-2.50)
    assert first.ce_ok and not first.pe_ok

    assert plan.final == final
    assert final.atm_strike == 23200
    assert final.otm_ce_strike == 23300
    assert final.otm_pe_strike == 23100
    assert final.sniper == pytest.approx(54.00)
    assert final.ce_gap == pytest.approx(35.15)
    assert final.pe_gap == pytest.approx(45.80)


def test_worked_example_trade_table():
    plan = build_daily_plan(23140.5, NIFTY, _lookup(WORKED_EXAMPLE_PREMIUMS))
    table = {
        (s.half, s.direction): (s.buy_strike, s.buy_type, s.levels.trigger, s.levels.entry, s.levels.stop_loss, s.levels.target)
        for s in trade_setups(plan.final)
    }
    assert table[("first", "down")] == (23100, "PE", 89.15, 100, 81, 144)
    assert table[("first", "up")] == (23300, "CE", 99.80, 100, 81, 144)
    assert table[("second", "down")] == (23100, "PE", pytest.approx(54.0), 64, 49, 100)
    assert table[("second", "up")] == (23300, "CE", pytest.approx(54.0), 64, 49, 100)


def _flat_premiums(atm_ce_gap, atm_pe_gap, atm_strike, sniper=50.0):
    """A premium lookup where every ATM gives the same gaps, relative to a
    Sniper of 50 (OTM CE and OTM PE both 50)."""

    def lookup(strike, option_type):
        if strike == atm_strike:
            return sniper + (atm_ce_gap if option_type == "CE" else atm_pe_gap)
        return sniper

    return lookup


def test_ce_fail_shifts_down():
    # Mirror image of the worked example: CE gap fails at 23100, both pass at 23000.
    mirrored = {
        (23100, "CE"): 59.20,
        (23100, "PE"): 147.40,
        (23200, "CE"): 34.25,
        (23000, "PE"): 89.15,
        (23000, "CE"): 99.80,
        (22900, "PE"): 48.80,
    }
    plan = build_daily_plan(23059.5, NIFTY, _lookup(mirrored))
    assert [a.atm_strike for a in plan.attempts] == [23100, 23000]
    assert plan.attempts[0].ce_gap == pytest.approx(-2.50)
    assert plan.final.sniper == pytest.approx(54.00)


def test_both_fail_is_no_plan():
    plan = build_daily_plan(23100, NIFTY, _flat_premiums(10, 10, 23100))
    assert plan.final is None
    assert not plan.attempts[0].ce_ok and not plan.attempts[0].pe_ok  # 20 fails too; no OTM fallback
    assert plan.reason.startswith("both gaps fail")


def test_gap_exactly_min_passes():
    plan = build_daily_plan(23100, NIFTY, _flat_premiums(25, 25, 23100))
    assert plan.final is not None


def test_sensex_keeps_the_nearest_atm_and_widens_the_otms_until_both_gaps_reach_40():
    """Owner, 29-09: SENSEX ATM = nearest round strike; move the OTMs out until both gaps >= 40.
    29-09 closes (72771.72 -> ATM 72800): at +-100 the PE gap is -22.62; further strikes are cheaper."""
    closes = {(72800, "CE"): 500.40, (72800, "PE"): 357.85,
              (72900, "CE"): 444.20, (72700, "PE"): 316.75,  # +-100: Sniper 380.48 -> PE gap -22.62
              (73000, "CE"): 394.35, (72600, "PE"): 280.00,  # +-200: Sniper 337.18 -> PE gap 20.67
              (73100, "CE"): 345.95, (72500, "PE"): 247.00}  # +-300: Sniper 296.48 -> gaps 203.92 / 61.37
    plan = build_daily_plan(72771.72, MARKETS["SENSEX"], _lookup(closes))
    assert [a.otm_ce_strike - a.atm_strike for a in plan.attempts] == [100, 200, 300]
    assert all(a.atm_strike == 72800 for a in plan.attempts)
    assert (plan.final.otm_ce_strike, plan.final.otm_pe_strike) == (73100, 72500)
    assert plan.final.sniper == pytest.approx(296.475)


def test_nifty_still_shifts_the_atm():
    assert not MARKETS["NIFTY"].widen_otm and MARKETS["SENSEX"].min_gap == 40


def test_nifty_moves_one_otm_out_when_the_shifts_oscillate():
    """Owner, 01-10: 30-09 close 22620.5 flips between ATM 22600 (PE gap 19.33) and 22700 (CE gap 18.55);
    then keep ATM 22600 and move the CE up or the PE down - both pass, the bigger smaller-gap wins."""
    closes = {(22600, "CE"): 164.50, (22600, "PE"): 114.65, (22700, "CE"): 113.15, (22500, "PE"): 77.50,
              (22700, "PE"): 163.35, (22800, "CE"): 74.55, (22400, "PE"): 52.10}
    # Owner, 05-10: the fallback was dropped for NIFTY ("only our trades") - 01-10 is now a no-plan day ...
    plan = build_daily_plan(22620.5, NIFTY, _lookup(closes))
    assert plan.final is None and [a.atm_strike for a in plan.attempts[:4]] == [22600, 22700, 22600, 22700]
    # ... the fallback itself still works if switched back on
    from dataclasses import replace
    plan = build_daily_plan(22620.5, replace(NIFTY, widen_otm_fallback=True), _lookup(closes))
    assert (plan.final.atm_strike, plan.final.otm_ce_strike, plan.final.otm_pe_strike) == (22600, 22800, 22500)
    assert plan.final.sniper == pytest.approx(76.025)
    assert (plan.final.ce_gap, plan.final.pe_gap) == (pytest.approx(88.475), pytest.approx(38.625))


def test_max_three_shifts_then_no_plan():
    # PE gap always fails, CE always passes -> keeps shifting up; widening never helps either.
    def lookup(strike, option_type):
        if strike % 100 == 0 and option_type == "CE" and strike >= 23100:
            return 100.0
        return 50.0

    plan = build_daily_plan(23100, NIFTY, lookup)
    assert plan.final is None
    assert [a.atm_strike for a in plan.attempts[:4]] == [23100, 23200, 23300, 23400]


@pytest.mark.parametrize(
    "trigger, entry, sl, target",
    [
        (89.15, 100, 81, 144),
        (99.80, 100, 81, 144),
        (100.0, 100, 81, 144),  # exactly a square: at-or-above keeps it
        (100.01, 121, 100, 169),
        (54.0, 64, 49, 100),
        (0.5, 1, 0, 9),
    ],
)
def test_square_levels(trigger, entry, sl, target):
    levels = square_levels(trigger)
    assert (levels.entry, levels.stop_loss, levels.target) == (entry, sl, target)
    assert levels.entry >= trigger


def test_square_levels_rejects_non_positive():
    with pytest.raises(ValueError):
        square_levels(0)


@pytest.mark.parametrize(
    "hhmm, half",
    [
        ("09:20", None),  # closes 09:25
        ("09:25", "first"),  # closes 09:30 - counts (owner, 2026-09-29)
        ("09:30", "first"),
        ("11:55", "first"),  # closes 12:00
        ("12:00", "second"),  # closes 12:05 - second half starts right after 12:00 (owner)
        ("12:20", "second"),
        ("12:25", "second"),  # closes 12:30
        ("12:30", "second"),
        ("14:55", "second"),  # closes 15:00
        ("15:00", None),
    ],
)
def test_entry_windows(hhmm, half):
    assert entry_window_for(datetime.fromisoformat(f"2026-09-29T{hhmm}")) == half


def test_sideways():
    prev = {"atm_ce": 89.15, "atm_pe": 99.80, "otm_ce": 48.8, "otm_pe": 59.2}
    assert is_sideways({"atm_ce": 80, "atm_pe": 90, "otm_ce": 40, "otm_pe": 50}, prev)
    assert not is_sideways({"atm_ce": 80, "atm_pe": 100, "otm_ce": 40, "otm_pe": 50}, prev)


def test_expiry_day_uses_same_day():
    tuesday = date(2026, 9, 29)
    assert next_weekly_expiry(tuesday, 1) == tuesday
    assert next_weekly_expiry(date(2026, 9, 28), 1) == tuesday
    assert next_weekly_expiry(date(2026, 9, 30), 1) == date(2026, 10, 6)


def test_relaxed_gap_20_before_the_otm_fallback_05_10_nifty():
    """Owner, 05-10: 25 first, then 20, then the OTM fallback. 01-10 closes: ATM 22500 passes at 20."""
    closes = {(22400, "CE"): 161.50, (22400, "PE"): 99.30, (22500, "CE"): 106.90, (22300, "PE"): 66.00,
              (22500, "PE"): 144.10, (22600, "CE"): 67.30}
    plan = build_daily_plan(22422, NIFTY, _lookup(closes))
    assert (plan.final.atm_strike, plan.final.otm_ce_strike, plan.final.otm_pe_strike) == (22500, 22600, 22400)
    assert plan.final.sniper == pytest.approx(83.30) and "(gap >= 20)" in plan.reason
