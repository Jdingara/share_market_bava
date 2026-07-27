"""
Day-by-day replay of the SPFS strategy (spfs_signal.py) over cached historical
data, simulating both the locked ATM contract and its adjacent OTM contract's
premiums via Black-Scholes (options_pricing.py), the same reason
backtester.py simulates premiums rather than using real historical option
data - see options_pricing.py's module docstring.

Deliberately NOT built on top of backtester.simulate_trade(): that function
only tracks one contract against a %-based bracket, while SPFS needs to
track two contracts (ATM for the Sniper check, OTM for confirmation/entry/
exit) against an absolute-points Square Number bracket. The CSV-loading and
"complete trading day" filtering pattern is reused from backtester.py; the
simulation algorithm itself is new.

v1 scope: no fake-breakout/reversal retry path (see spfs_signal.py's
docstring and PROJECT_STATUS.md) - a day either confirms and trades, or it
returns one of several NO_TRADE/SKIPPED outcomes and moves on.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from options_pricing import black_scholes_price
from spfs_signal import (
    SpfsSetup,
    build_daily_setup,
    is_confirmed,
    next_square,
    time_to_expiry_years,
    trade_levels,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DAILY_CSV = PROJECT_ROOT / "data" / "historical" / "NIFTY_50_day.csv"
INTRADAY_CSV = PROJECT_ROOT / "data" / "historical" / "NIFTY_50_5minute.csv"  # finer grain than 15-min - needed to
# catch specific premium levels (Sniper level, Square Number crossings) with reasonable precision
RESULTS_DIR = PROJECT_ROOT / "data" / "backtest_results"

MIN_DAILY_HISTORY = 55  # same rationale as backtester.py: enough rows for EMA(50) + a 20-day volatility window
MAX_DAILY_DATA_GAP_DAYS = 4  # staleness guard - see PROJECT_STATUS.md; the daily and intraday CSVs are fetched
# independently and can silently drift apart. Without this, a day whose "previous close" resolves to a
# stale, distant row would compute a wrong Sniper level with no visible error.


@dataclass
class SpfsTradeResult:
    date: str
    outcome: str  # TRADE | NO_TRADE_NEUTRAL_TREND | NO_TRADE_NO_CONFIRMATION |
    # NO_TRADE_CONFIRMED_NO_SQUARE_ENTRY | SKIPPED_STALE_DAILY_DATA | SKIPPED_INSUFFICIENT_HISTORY
    trend: str
    option_type: str  # "CE" | "PE" | ""
    atm_strike: float
    otm_strike: float
    expiry: str
    atm_previous_close_premium: float
    sniper_level: float
    confirmed: bool
    confirmation_time: str
    otm_premium_at_confirmation: float
    entry_time: str
    entry_square: float
    stop_loss_level: float
    target_level: float
    exit_time: str
    exit_premium: float
    exit_reason: str  # "TARGET" | "STOPLOSS" | "EOD_CLOSE" | ""
    pnl_points: float
    pnl_pct: float
    reasoning: str


def _empty_result(day: date, outcome: str, reasoning: str, setup: Optional[SpfsSetup] = None) -> SpfsTradeResult:
    return SpfsTradeResult(
        date=day.isoformat(),
        outcome=outcome,
        trend=setup.trend if setup else "",
        option_type=setup.option_type if setup and setup.option_type else "",
        atm_strike=setup.atm_strike if setup and setup.atm_strike else 0.0,
        otm_strike=setup.otm_strike if setup and setup.otm_strike else 0.0,
        expiry=setup.expiry.isoformat() if setup and setup.expiry else "",
        atm_previous_close_premium=setup.atm_previous_close_premium if setup and setup.atm_previous_close_premium else 0.0,
        sniper_level=setup.sniper_level if setup and setup.sniper_level else 0.0,
        confirmed=False,
        confirmation_time="",
        otm_premium_at_confirmation=0.0,
        entry_time="",
        entry_square=0.0,
        stop_loss_level=0.0,
        target_level=0.0,
        exit_time="",
        exit_premium=0.0,
        exit_reason="",
        pnl_points=0.0,
        pnl_pct=0.0,
        reasoning=reasoning,
    )


def _premium_extremes(candle, strike: float, tte: float, volatility: float, option_type: str) -> tuple[float, float]:
    """(best, worst) premium achievable within this candle's high/low range for a
    long position in `strike` - same convention as backtester.simulate_trade."""
    premium_at_high = black_scholes_price(candle["high"], strike, tte, volatility, option_type)
    premium_at_low = black_scholes_price(candle["low"], strike, tte, volatility, option_type)
    return (premium_at_high, premium_at_low) if option_type == "CE" else (premium_at_low, premium_at_high)


def simulate_spfs_day(day: date, daily_history: pd.DataFrame, day_intraday: pd.DataFrame) -> SpfsTradeResult:
    day_open_spot = day_intraday.iloc[0]["open"]
    setup = build_daily_setup(daily_history, day_open_spot, day)

    if setup.option_type is None:
        return _empty_result(day, "NO_TRADE_NEUTRAL_TREND", setup.reasoning, setup)

    option_type = setup.option_type
    atm_strike = setup.atm_strike
    otm_strike = setup.otm_strike
    expiry = setup.expiry
    volatility = setup.volatility

    # --- Phase 1: OTM confirmation scan ---
    # Uses each leg's own favorable extreme within the candle (ATM's lowest reachable
    # premium, OTM's highest reachable premium), NOT the same single spot value for
    # both. This is a deliberate correction from an initial close-only design: since
    # OTM and ATM are the same option type with OTM's strike further out, no-arbitrage
    # means OTM's premium can never exceed ATM's premium at any single shared spot/vol/
    # time point - so requiring "ATM decayed to Sniper" AND "OTM above ATM's old close"
    # at literally the same spot value is mathematically unsatisfiable (ATM's own cap
    # at 70% of its previous close would force OTM below that too). Evaluating each leg
    # at its own extreme within the candle's high/low range (the same "did price touch
    # this level today" convention already used elsewhere in this project for stop/
    # target crossings) is the only operationalization that can actually trigger.
    confirmation_index: Optional[int] = None
    confirmation_time = ""
    otm_premium_at_confirmation = 0.0

    for i in range(len(day_intraday)):
        candle = day_intraday.iloc[i]
        candle_time = pd.Timestamp(candle["date"]).to_pydatetime()
        tte = time_to_expiry_years(candle_time, expiry)
        _, atm_lowest_premium = _premium_extremes(candle, atm_strike, tte, volatility, option_type)
        otm_highest_premium, _ = _premium_extremes(candle, otm_strike, tte, volatility, option_type)

        if is_confirmed(atm_lowest_premium, otm_highest_premium, setup.sniper_level, setup.atm_previous_close_premium):
            confirmation_index = i
            confirmation_time = candle_time.isoformat()
            otm_premium_at_confirmation = otm_highest_premium
            break

    if confirmation_index is None:
        return _empty_result(day, "NO_TRADE_NO_CONFIRMATION", f"{setup.reasoning}; OTM never confirmed", setup)

    # --- Phase 2: Square Number entry wait, starting the candle after confirmation ---
    entry_index: Optional[int] = None
    entry_square = 0.0
    entry_time = ""
    current_reference_premium = otm_premium_at_confirmation

    for i in range(confirmation_index + 1, len(day_intraday)):
        candle = day_intraday.iloc[i]
        candle_time = pd.Timestamp(candle["date"]).to_pydatetime()
        tte = time_to_expiry_years(candle_time, expiry)
        target_square = next_square(current_reference_premium)

        best_premium, _ = _premium_extremes(candle, otm_strike, tte, volatility, option_type)
        if best_premium >= target_square:
            entry_index = i
            entry_square = target_square
            entry_time = candle_time.isoformat()
            break

        current_reference_premium = black_scholes_price(candle["close"], otm_strike, tte, volatility, option_type)

    if entry_index is None:
        return _empty_result(
            day,
            "NO_TRADE_CONFIRMED_NO_SQUARE_ENTRY",
            f"{setup.reasoning}; confirmed at {confirmation_time} but no Square Number entry reached before EOD",
            setup,
        )

    # --- Phase 3: trade management ---
    stop_loss_level, target_level = trade_levels(entry_square)
    exit_time, exit_premium, exit_reason = entry_time, entry_square, "EOD_CLOSE"

    for i in range(entry_index + 1, len(day_intraday)):
        candle = day_intraday.iloc[i]
        candle_time = pd.Timestamp(candle["date"]).to_pydatetime()
        tte = time_to_expiry_years(candle_time, expiry)
        best_premium, worst_premium = _premium_extremes(candle, otm_strike, tte, volatility, option_type)

        # Conservative tie-break, same convention as backtester.simulate_trade: if both
        # the stop and target are theoretically crossable within one candle, assume
        # the stop hit first.
        if worst_premium <= stop_loss_level:
            exit_time, exit_premium, exit_reason = candle_time.isoformat(), stop_loss_level, "STOPLOSS"
            break
        if best_premium >= target_level:
            exit_time, exit_premium, exit_reason = candle_time.isoformat(), target_level, "TARGET"
            break

        exit_time = candle_time.isoformat()
        exit_premium = black_scholes_price(candle["close"], otm_strike, tte, volatility, option_type)
    else:
        exit_reason = "EOD_CLOSE"

    pnl_points = exit_premium - entry_square
    pnl_pct = pnl_points / entry_square * 100

    return SpfsTradeResult(
        date=day.isoformat(),
        outcome="TRADE",
        trend=setup.trend,
        option_type=option_type,
        atm_strike=atm_strike,
        otm_strike=otm_strike,
        expiry=expiry.isoformat(),
        atm_previous_close_premium=round(setup.atm_previous_close_premium, 2),
        sniper_level=round(setup.sniper_level, 2),
        confirmed=True,
        confirmation_time=confirmation_time,
        otm_premium_at_confirmation=round(otm_premium_at_confirmation, 2),
        entry_time=entry_time,
        entry_square=entry_square,
        stop_loss_level=stop_loss_level,
        target_level=target_level,
        exit_time=exit_time,
        exit_premium=round(exit_premium, 2),
        exit_reason=exit_reason,
        pnl_points=round(pnl_points, 2),
        pnl_pct=round(pnl_pct, 2),
        reasoning=setup.reasoning,
    )


def _load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_df = pd.read_csv(DAILY_CSV)
    daily_df["date"] = pd.to_datetime(daily_df["date"])
    daily_df = daily_df.sort_values("date").reset_index(drop=True)

    intraday_df = pd.read_csv(INTRADAY_CSV)
    intraday_df["date"] = pd.to_datetime(intraday_df["date"])
    intraday_df = intraday_df.sort_values("date").reset_index(drop=True)
    return daily_df, intraday_df


def run_spfs_backtest(start_date: Optional[date] = None, end_date: Optional[date] = None) -> list[SpfsTradeResult]:
    daily_df, intraday_df = _load_data()
    intraday_df["trading_day"] = intraday_df["date"].dt.date

    all_days = sorted(intraday_df["trading_day"].unique())
    full_day_candle_count = intraday_df["trading_day"].value_counts().median()
    complete_days = [
        d for d in all_days if (intraday_df["trading_day"] == d).sum() >= full_day_candle_count * 0.8
    ]
    if start_date is not None:
        complete_days = [d for d in complete_days if d >= start_date]
    if end_date is not None:
        complete_days = [d for d in complete_days if d <= end_date]

    results: list[SpfsTradeResult] = []

    for day in complete_days:
        daily_history = daily_df[daily_df["date"].dt.date < day]
        if len(daily_history) < MIN_DAILY_HISTORY:
            results.append(_empty_result(day, "SKIPPED_INSUFFICIENT_HISTORY", "Fewer than 55 prior daily rows available"))
            continue

        last_daily_date = daily_history["date"].dt.date.iloc[-1]
        if (day - last_daily_date).days > MAX_DAILY_DATA_GAP_DAYS:
            results.append(
                _empty_result(
                    day,
                    "SKIPPED_STALE_DAILY_DATA",
                    f"Nearest prior daily row is {last_daily_date.isoformat()}, "
                    f"{(day - last_daily_date).days} days before {day.isoformat()} - daily/intraday CSVs have drifted apart",
                )
            )
            continue

        day_intraday = intraday_df[intraday_df["trading_day"] == day].drop(columns=["trading_day"]).reset_index(drop=True)
        results.append(simulate_spfs_day(day, daily_history, day_intraday))

    return results


def summarize_spfs(results: list[SpfsTradeResult]) -> None:
    total_days = len(results)

    def count(outcome: str) -> int:
        return sum(1 for r in results if r.outcome == outcome)

    trades = [r for r in results if r.outcome == "TRADE"]
    wins = [t for t in trades if t.exit_reason == "TARGET"]
    losses = [t for t in trades if t.exit_reason == "STOPLOSS"]
    eod = [t for t in trades if t.exit_reason == "EOD_CLOSE"]

    print(f"Days evaluated:              {total_days}")
    print(f"  No-trade (neutral trend):  {count('NO_TRADE_NEUTRAL_TREND')}")
    print(f"  No-trade (no confirmation):{count('NO_TRADE_NO_CONFIRMATION')}")
    print(f"  No-trade (confirmed, no square entry): {count('NO_TRADE_CONFIRMED_NO_SQUARE_ENTRY')}")
    print(f"  Skipped (stale daily data): {count('SKIPPED_STALE_DAILY_DATA')}")
    print(f"  Skipped (insufficient history): {count('SKIPPED_INSUFFICIENT_HISTORY')}")
    print(f"Trades taken:                {len(trades)}")
    if trades:
        avg_points = sum(t.pnl_points for t in trades) / len(trades)
        avg_pct = sum(t.pnl_pct for t in trades) / len(trades)
        print(f"  Hit target:   {len(wins)}")
        print(f"  Hit stop:     {len(losses)}")
        print(f"  EOD close:    {len(eod)}")
        print(f"  Win rate (target vs stop, excl EOD): {len(wins) / max(len(wins) + len(losses), 1) * 100:.1f}%")
        print(f"  Overall win rate (target hits / all trades): {len(wins) / len(trades) * 100:.1f}%")
        print(f"  Average P&L per trade: {avg_points:+.2f} points ({avg_pct:+.2f}%)")


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results = run_spfs_backtest()

    out_path = RESULTS_DIR / "spfs_trades.csv"
    pd.DataFrame([asdict(r) for r in results]).to_csv(out_path, index=False)
    print(f"Full day-by-day results saved to {out_path}\n")

    summarize_spfs(results)


if __name__ == "__main__":
    main()
