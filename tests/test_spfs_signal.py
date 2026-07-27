"""
Unit tests for spfs_signal.py. Where possible these check exact arithmetic
identities (e.g. sniper_level == previous_close * 0.70) rather than memorized
reference decimals, matching the convention in test_options_pricing.py.
"""

import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import spfs_signal
from options_pricing import nearest_strike
from spfs_signal import (
    build_daily_setup,
    is_confirmed,
    lock_atm_strike,
    next_square,
    option_type_for_trend,
    otm_strike_for,
    previous_square,
    sniper_level,
    trade_levels,
)


# --- lock_atm_strike / _closest_ce_pe_strike ---
#
# black_scholes_price is monkeypatched here with a synthetic CE/PE pair whose
# gap is a simple, exactly-known function of distance from a chosen "true ATM"
# target (gap = 2 * |strike - target|, minimized only at target) - this gives
# full deterministic control over which strike "wins" the search, rather than
# depending on real Black-Scholes numbers (which would require hand-verifying
# a forward-price/interest-rate-carry calculation to predict).


def _fake_bs_centered_at(target):
    def fake(spot, strike, tte, volatility, option_type):
        distance = strike - target
        return (1000 - distance) if option_type == "CE" else (1000 + distance)

    return fake


def test_closest_ce_pe_strike_finds_exact_minimum_gap_within_radius(monkeypatch):
    monkeypatch.setattr(spfs_signal, "black_scholes_price", _fake_bs_centered_at(24000))
    assert spfs_signal._closest_ce_pe_strike(23900, reference_spot=23922, tte=5 / 365, volatility=0.12) == 24000


def test_closest_ce_pe_strike_clamped_to_search_radius(monkeypatch):
    # True target (24300) is 8 strikes from center (23900) - beyond the +/-3
    # radius - so the closest reachable candidate (center + 3*50 = 24050) wins.
    monkeypatch.setattr(spfs_signal, "black_scholes_price", _fake_bs_centered_at(24300))
    assert spfs_signal._closest_ce_pe_strike(23900, reference_spot=23922, tte=5 / 365, volatility=0.12) == 24050


def test_lock_atm_strike_refines_beyond_simple_rounding(monkeypatch):
    # Matches the user's own worked example: previous close 23922 rounds to a
    # naive 23900, but the closest-CE/PE-gap search (target genuinely at 24000)
    # shifts the real ATM there instead.
    monkeypatch.setattr(spfs_signal, "black_scholes_price", _fake_bs_centered_at(24000))
    atm = lock_atm_strike(previous_close_spot=23922, day_open_spot=23980, previous_tte=5 / 365, volatility=0.12)
    assert atm == 24000


def test_lock_atm_strike_small_overnight_move_keeps_previous_close_based_atm(monkeypatch):
    # No refinement shift here (target == center == 24000); today's open (24030)
    # differs by less than one full strike interval - no gap override.
    monkeypatch.setattr(spfs_signal, "black_scholes_price", _fake_bs_centered_at(24000))
    atm = lock_atm_strike(previous_close_spot=24012, day_open_spot=24030, previous_tte=5 / 365, volatility=0.12)
    assert atm == 24000


def test_lock_atm_strike_huge_gap_overrides_to_todays_open(monkeypatch):
    # ATM (24250, no refinement shift) but today opens 330 points away (>= the
    # 50-point gap threshold) - the stale ATM is discarded for a fresh search
    # re-centered on today's actual open instead.
    monkeypatch.setattr(spfs_signal, "black_scholes_price", _fake_bs_centered_at(24250))
    atm = lock_atm_strike(previous_close_spot=24240, day_open_spot=24580, previous_tte=5 / 365, volatility=0.12)
    assert atm == 24600


def test_lock_atm_strike_gap_exactly_at_threshold_overrides(monkeypatch):
    # Exactly one strike interval away (50 points) still counts as a huge gap
    # (rule uses >=, not strict >).
    monkeypatch.setattr(spfs_signal, "black_scholes_price", _fake_bs_centered_at(24250))
    atm = lock_atm_strike(previous_close_spot=24240, day_open_spot=24300, previous_tte=5 / 365, volatility=0.12)
    assert atm == 24300


# --- otm_strike_for ---


def test_otm_strike_for_call_is_one_interval_above():
    assert otm_strike_for(24000, "CE") == 24050


def test_otm_strike_for_put_is_one_interval_below():
    assert otm_strike_for(24000, "PE") == 23950


# --- option_type_for_trend ---


def test_option_type_for_trend_mapping():
    assert option_type_for_trend("bullish") == "CE"
    assert option_type_for_trend("bearish") == "PE"
    assert option_type_for_trend("neutral") is None


# --- sniper_level ---


def test_sniper_level_default_30_percent_drop():
    assert sniper_level(100.0) == 70.0


def test_sniper_level_custom_fraction():
    assert sniper_level(100.0, fraction=0.5) == 50.0


# --- next_square / previous_square ---


def test_next_square_exact_multiple_stays_itself():
    assert next_square(100) == 100
    assert next_square(80) == 80
    assert next_square(0) == 0


def test_next_square_rounds_up_when_above_grid():
    assert next_square(81) == 100
    assert next_square(118) == 120
    assert next_square(83.5) == 100


def test_next_square_is_float_noise_safe():
    assert next_square(100.0000000001) == 100
    assert next_square(99.9999999999) == 100


def test_previous_square_exact_multiple_stays_itself():
    assert previous_square(100) == 100


def test_previous_square_rounds_down_when_above_grid():
    assert previous_square(99.99) == 80
    assert previous_square(119) == 100


def test_previous_square_is_float_noise_safe():
    assert previous_square(100.01) == 100


def test_trade_levels_stop_and_target_from_entry():
    stop_loss, target = trade_levels(120)
    assert (stop_loss, target) == (100, 160)


# --- is_confirmed ---


def test_is_confirmed_true_when_both_conditions_hold():
    assert is_confirmed(atm_premium=65, otm_premium=105, sniper_level_value=70, atm_previous_close_premium=100)


def test_is_confirmed_false_when_only_atm_condition_holds():
    assert not is_confirmed(atm_premium=65, otm_premium=95, sniper_level_value=70, atm_previous_close_premium=100)


def test_is_confirmed_false_when_only_otm_condition_holds():
    assert not is_confirmed(atm_premium=85, otm_premium=105, sniper_level_value=70, atm_previous_close_premium=100)


def test_is_confirmed_atm_boundary_is_inclusive():
    # rule uses <=
    assert is_confirmed(atm_premium=70, otm_premium=105, sniper_level_value=70, atm_previous_close_premium=100)


def test_is_confirmed_otm_boundary_is_exclusive():
    # rule uses strict > - exactly equal to the previous close does not confirm
    assert not is_confirmed(atm_premium=65, otm_premium=100, sniper_level_value=70, atm_previous_close_premium=100)


# --- build_daily_setup ---


def _synthetic_daily_history(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [c * 1.005 for c in closes],
            "low": [c * 0.995 for c in closes],
            "close": closes,
            "volume": [0] * len(closes),
        }
    )


def test_build_daily_setup_bullish_locks_call_atm_and_computes_sniper_level():
    closes = [24000 + 15 * i + 5 * math.sin(i) for i in range(60)]
    daily_history = _synthetic_daily_history(closes)
    day_open_spot = 24900.0
    trade_date = date(2026, 3, 15)  # a Sunday-agnostic date well after the synthetic history

    setup = build_daily_setup(daily_history, day_open_spot, trade_date)

    assert setup.trend == "bullish"
    assert setup.option_type == "CE"
    # Exact ATM value (real, non-monkeypatched Black-Scholes) is covered by the
    # dedicated lock_atm_strike/_closest_ce_pe_strike tests above - here just
    # confirm it's a real strike within the search radius of naive rounding.
    assert setup.atm_strike % 50 == 0
    assert abs(setup.atm_strike - nearest_strike(closes[-1])) <= spfs_signal.ATM_SEARCH_RADIUS_STRIKES * 50
    assert setup.otm_strike == setup.atm_strike + 50
    assert setup.atm_previous_close_premium is not None and setup.atm_previous_close_premium > 0
    assert setup.sniper_level == pytest.approx(setup.atm_previous_close_premium * 0.70)


def test_build_daily_setup_neutral_trend_has_no_atm_locked():
    closes = [24000.0] * 60
    daily_history = _synthetic_daily_history(closes)

    setup = build_daily_setup(daily_history, day_open_spot=24000.0, trade_date=date(2026, 3, 15))

    assert setup.trend == "neutral"
    assert setup.option_type is None
    assert setup.atm_strike is None
    assert setup.otm_strike is None
    assert setup.sniper_level is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
