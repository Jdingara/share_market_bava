"""
Regression tests for the SPFS Phase 1 (confirmation) -> Phase 2 (Square Number
entry) -> Phase 3 (trade management) state machine in spfs_backtester.py.

These monkeypatch black_scholes_price with a simple intrinsic-value stand-in
(spot - strike for CE) and build_daily_setup with a fixed SpfsSetup, so each
test can engineer exact premium crossings via candle OHLC values without
depending on real Black-Scholes curvature (already covered by
test_options_pricing.py) or a real daily trend (already covered by
test_spfs_signal.py's build_daily_setup tests). This isolates the thing the
pure-function tests can't catch on their own: the day-by-day wiring itself.
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import spfs_backtester
from spfs_signal import SpfsSetup

FIXED_SETUP = SpfsSetup(
    trend="bullish",
    option_type="CE",
    atm_strike=24000.0,
    otm_strike=24050.0,
    expiry=date(2026, 3, 20),
    volatility=0.15,
    atm_previous_close_premium=100.0,
    sniper_level=70.0,
    reasoning="fixed test setup",
)

EMPTY_DAILY_HISTORY = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])


def _fake_black_scholes_price(spot, strike, tte, volatility, option_type):
    """Intrinsic-value-only stand-in: monotonic in spot, trivial to invert when
    engineering exact premium crossings for a test scenario."""
    return (spot - strike) if option_type == "CE" else (strike - spot)


def _candles(rows: list[dict]) -> pd.DataFrame:
    timestamps = pd.date_range("2026-03-16 09:15", periods=len(rows), freq="5min")
    df = pd.DataFrame(rows)
    df["date"] = timestamps
    return df[["date", "open", "high", "low", "close", "volume"]]


@pytest.fixture(autouse=True)
def _patch_pricing_and_setup(monkeypatch):
    monkeypatch.setattr(spfs_backtester, "black_scholes_price", _fake_black_scholes_price)
    monkeypatch.setattr(spfs_backtester, "build_daily_setup", lambda daily_history, day_open_spot, trade_date: FIXED_SETUP)


def test_confirm_enter_hit_target():
    day_intraday = _candles(
        [
            # No confirmation yet: OTM's best premium (24010-24050=-40) never exceeds the 100 baseline.
            {"open": 24000, "high": 24010, "low": 23990, "close": 24000, "volume": 0},
            # Confirms: ATM's lowest premium (24065-24000=65) <= sniper (70); OTM's highest (24200-24050=150) > 100.
            {"open": 24100, "high": 24200, "low": 24065, "close": 24150, "volume": 0},
            # Square entry: OTM's best premium (24220-24050=170) crosses next_square(150)=160 -> enter at 160.
            {"open": 24160, "high": 24220, "low": 24140, "close": 24200, "volume": 0},
            # Target hit: OTM's best (24300-24050=250) >= target 200 (entry 160 + 2 squares); worst
            # (24200-24050=150) stays above stop (140).
            {"open": 24250, "high": 24300, "low": 24200, "close": 24280, "volume": 0},
        ]
    )

    result = spfs_backtester.simulate_spfs_day(date(2026, 3, 16), EMPTY_DAILY_HISTORY, day_intraday)

    assert result.outcome == "TRADE"
    assert result.confirmed is True
    assert result.entry_square == 160
    assert result.stop_loss_level == 140
    assert result.target_level == 200
    assert result.exit_reason == "TARGET"
    assert result.exit_premium == 200
    assert result.pnl_points == pytest.approx(40.0)


def test_confirm_enter_hit_stop():
    day_intraday = _candles(
        [
            {"open": 24000, "high": 24010, "low": 23990, "close": 24000, "volume": 0},
            {"open": 24100, "high": 24200, "low": 24065, "close": 24150, "volume": 0},
            {"open": 24160, "high": 24220, "low": 24140, "close": 24200, "volume": 0},
            # Stop hit: OTM's worst (24150-24050=100) <= stop 140 (stop checked before target, same
            # conservative tie-break convention as backtester.simulate_trade).
            {"open": 24170, "high": 24180, "low": 24150, "close": 24160, "volume": 0},
        ]
    )

    result = spfs_backtester.simulate_spfs_day(date(2026, 3, 16), EMPTY_DAILY_HISTORY, day_intraday)

    assert result.outcome == "TRADE"
    assert result.entry_square == 160
    assert result.exit_reason == "STOPLOSS"
    assert result.exit_premium == 140
    assert result.pnl_points == pytest.approx(-20.0)


def test_no_confirmation_all_day():
    # OTM's best premium (24010-24050=-40) never exceeds the 100 baseline on any candle.
    flat_candle = {"open": 24000, "high": 24010, "low": 23990, "close": 24000, "volume": 0}
    day_intraday = _candles([flat_candle, flat_candle, flat_candle, flat_candle])

    result = spfs_backtester.simulate_spfs_day(date(2026, 3, 16), EMPTY_DAILY_HISTORY, day_intraday)

    assert result.outcome == "NO_TRADE_NO_CONFIRMATION"
    assert result.confirmed is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
