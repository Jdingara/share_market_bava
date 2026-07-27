"""
Not an automated test - a manual sanity check for the SPFS strategy
(spfs_signal.py / spfs_backtester.py) against real cached data. For each of
the last several complete trading days, prints the locked ATM/OTM setup, the
Sniper level, and - critically - the best OTM premium and worst ATM premium
actually reached THAT DAY (even on days that never confirmed), so a human can
see how close the day came to confirming, not just whether it did.

Run after fetching real daily + 5minute data via data_fetch.py.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from spfs_backtester import _load_data, MIN_DAILY_HISTORY, _premium_extremes, simulate_spfs_day
from spfs_signal import build_daily_setup, time_to_expiry_years

DAYS_TO_CHECK = 10

daily_df, intraday_df = _load_data()
intraday_df["trading_day"] = intraday_df["date"].dt.date

all_days = sorted(intraday_df["trading_day"].unique())
full_day_candle_count = intraday_df["trading_day"].value_counts().median()
complete_days = [d for d in all_days if (intraday_df["trading_day"] == d).sum() >= full_day_candle_count * 0.8]

days_to_test = complete_days[-DAYS_TO_CHECK:]

for day in days_to_test:
    daily_history = daily_df[daily_df["date"].dt.date < day]
    if len(daily_history) < MIN_DAILY_HISTORY:
        print(f"{day}: skipped, not enough prior daily history")
        continue

    day_intraday = intraday_df[intraday_df["trading_day"] == day].drop(columns=["trading_day"]).reset_index(drop=True)
    day_open_spot = day_intraday.iloc[0]["open"]
    setup = build_daily_setup(daily_history, day_open_spot, day)

    print(f"\n=== {day} ===")
    print(f"  day range:  low={day_intraday['low'].min():.1f} high={day_intraday['high'].max():.1f}")
    print(f"  trend bias: {setup.trend}")

    if setup.option_type is None:
        print("  no ATM locked (neutral trend) - no trade today")
        continue

    print(
        f"  locked ATM {setup.atm_strike} {setup.option_type} / OTM {setup.otm_strike} {setup.option_type}, "
        f"expiry {setup.expiry}"
    )
    print(f"  ATM previous close premium: {setup.atm_previous_close_premium:.2f}")
    print(f"  Sniper level (70%):         {setup.sniper_level:.2f}")

    # Best OTM premium and worst ATM premium reached anywhere in the day, even
    # if never on the same candle - shows HOW CLOSE a non-confirming day came.
    best_otm, worst_atm = float("-inf"), float("inf")
    for i in range(len(day_intraday)):
        candle = day_intraday.iloc[i]
        candle_time = pd.Timestamp(candle["date"]).to_pydatetime()
        tte = time_to_expiry_years(candle_time, setup.expiry)
        _, atm_low = _premium_extremes(candle, setup.atm_strike, tte, setup.volatility, setup.option_type)
        otm_high, _ = _premium_extremes(candle, setup.otm_strike, tte, setup.volatility, setup.option_type)
        best_otm = max(best_otm, otm_high)
        worst_atm = min(worst_atm, atm_low)

    print(
        f"  day's best OTM premium: {best_otm:.2f} (needs > {setup.atm_previous_close_premium:.2f}) "
        f"-> {'cleared' if best_otm > setup.atm_previous_close_premium else 'never cleared'}"
    )
    print(
        f"  day's worst ATM premium: {worst_atm:.2f} (needs <= {setup.sniper_level:.2f}) "
        f"-> {'reached' if worst_atm <= setup.sniper_level else 'never reached'}"
    )

    result = simulate_spfs_day(day, daily_history, day_intraday)
    print(f"  outcome: {result.outcome}")
    if result.outcome == "TRADE":
        print(
            f"    confirmed @ {result.confirmation_time}, entered @ {result.entry_time} "
            f"square={result.entry_square}, exited @ {result.exit_time} "
            f"{result.exit_reason} premium={result.exit_premium} pnl={result.pnl_points:+.1f}pts ({result.pnl_pct:+.1f}%)"
        )
