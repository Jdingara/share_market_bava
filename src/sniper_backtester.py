"""
Day-by-day replay of the Sniper strategy (PROJECT_STATUS.md) over the cached
NIFTY 50 candles. The trading rules live in sniper_engine.SniperDay - the same
engine the live paper bot uses; this module only supplies it with bars.

PREMIUMS ARE ESTIMATES. There is no real historical option price data in this
project yet, so every premium - yesterday's closes used for the plan and every
intraday value - is a Black-Scholes estimate from the NIFTY spot price with
20-day historical volatility (see options_pricing.py). The spec's levels
(square numbers like 81/100/144) are sensitive to exact premiums, so treat these
results as a check that the logic runs end to end, not as a measure of real
P&L.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from options_pricing import black_scholes_price, historical_volatility, next_weekly_expiry, time_to_expiry_years
from sniper_engine import Bar, SniperDay, TradeResult
from sniper_signal import MARKETS, DailyPlan, MarketConfig, OptionType, StrikeRow, build_daily_plan

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DAILY_CSV = PROJECT_ROOT / "data" / "historical" / "NIFTY_50_day.csv"
INTRADAY_CSV = PROJECT_ROOT / "data" / "historical" / "NIFTY_50_5minute.csv"
RESULTS_DIR = PROJECT_ROOT / "data" / "backtest_results"

VOLATILITY_WINDOW = 20
MIN_DAILY_HISTORY = VOLATILITY_WINDOW + 1
MAX_DAILY_DATA_GAP_DAYS = 4  # staleness guard: the daily and intraday CSVs are fetched separately and can
# drift apart. Without this, "yesterday's close" could silently resolve to a distant, stale row.
MARKET_CLOSE = time(15, 30)

# (spot, strike, option_type, candle_start) -> premium
PriceFn = Callable[[float, float, OptionType, datetime], float]


@dataclass
class DayResult:
    date: str
    outcome: str  # TRADED | NO_TRADE | NO_PLAN | SKIPPED_INSUFFICIENT_HISTORY | SKIPPED_STALE_DAILY_DATA
    reason: str
    index_close: float = 0.0
    shifts: int = 0
    atm_strike: float = 0.0
    atm_ce_close: float = 0.0
    atm_pe_close: float = 0.0
    otm_ce_close: float = 0.0
    otm_pe_close: float = 0.0
    sniper: float = 0.0
    sideways_candles: int = 0
    trades: list[TradeResult] = field(default_factory=list)


def _naive(ts) -> datetime:
    return pd.Timestamp(ts).to_pydatetime().replace(tzinfo=None)


def _bars_from_spot(candle, row: StrikeRow, when: datetime, price: PriceFn) -> dict[str, Bar]:
    """Premium bars for the plan's 4 contracts from one spot candle. A PE's
    high premium comes from the spot low, and vice versa."""
    bars = {}
    for key, strike, option_type in (
        ("atm_ce", row.atm_strike, "CE"),
        ("atm_pe", row.atm_strike, "PE"),
        ("otm_ce", row.otm_ce_strike, "CE"),
        ("otm_pe", row.otm_pe_strike, "PE"),
    ):
        at_high = price(candle["high"], strike, option_type, when)
        at_low = price(candle["low"], strike, option_type, when)
        close = price(candle["close"], strike, option_type, when)
        opened = price(candle["open"], strike, option_type, when)
        bars[key] = Bar(at_high, at_low, close, opened) if option_type == "CE" else Bar(at_low, at_high, close, opened)
    return bars


def simulate_day(
    day: date, row: StrikeRow, candles: pd.DataFrame, price: PriceFn, require_cross: bool = True, **engine_options
) -> tuple[list[TradeResult], int]:
    """Walks one day's 5-minute spot candles against a finished plan row.
    Returns (trades, number of in-window candles skipped as sideways)."""
    engine = SniperDay(day, row, require_cross, **engine_options)
    when, bars = None, None
    for _, candle in candles.iterrows():
        when = _naive(candle["date"])
        bars = _bars_from_spot(candle, row, when, price)
        engine.on_candle(when, bars)
        if engine.done:
            break
    if not engine.done and when is not None:
        engine.finish(when, bars)
    return engine.trades, engine.sideways_candles


def _estimated_pricing(daily_history: pd.DataFrame, day: date, market: MarketConfig):
    """Black-Scholes estimates for one trading day: a previous-close premium
    lookup for the plan, and an intraday PriceFn for the candle walk."""
    expiry = next_weekly_expiry(day, market.expiry_weekday)
    volatility = historical_volatility(daily_history["close"], window=VOLATILITY_WINDOW)
    previous = daily_history.iloc[-1]
    previous_close_time = datetime.combine(_naive(previous["date"]).date(), MARKET_CLOSE)
    previous_tte = time_to_expiry_years(previous_close_time, expiry)

    def previous_premium(strike: float, option_type: OptionType) -> float:
        return black_scholes_price(previous["close"], strike, previous_tte, volatility, option_type)

    def intraday_price(spot: float, strike: float, option_type: OptionType, when: datetime) -> float:
        return black_scholes_price(spot, strike, time_to_expiry_years(when, expiry), volatility, option_type)

    return previous_premium, intraday_price


def _plan_fields(plan: DailyPlan) -> dict:
    row = plan.final or plan.attempts[-1]
    return dict(
        index_close=plan.index_close,
        shifts=len(plan.attempts) - 1,
        atm_strike=row.atm_strike,
        atm_ce_close=round(row.atm_ce_close, 2),
        atm_pe_close=round(row.atm_pe_close, 2),
        otm_ce_close=round(row.otm_ce_close, 2),
        otm_pe_close=round(row.otm_pe_close, 2),
        sniper=round(row.sniper, 2),
    )


def _load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_df = pd.read_csv(DAILY_CSV)
    daily_df["date"] = pd.to_datetime(daily_df["date"])
    daily_df = daily_df.sort_values("date").reset_index(drop=True)

    intraday_df = pd.read_csv(INTRADAY_CSV)
    intraday_df["date"] = pd.to_datetime(intraday_df["date"])
    intraday_df = intraday_df.sort_values("date").reset_index(drop=True)
    return daily_df, intraday_df


def run_backtest(
    market: MarketConfig = MARKETS["NIFTY"],
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    require_cross: bool = True,
    **engine_options,
) -> list[DayResult]:
    daily_df, intraday_df = _load_data()
    intraday_df["trading_day"] = intraday_df["date"].dt.date

    all_days = sorted(intraday_df["trading_day"].unique())
    full_day_candle_count = intraday_df["trading_day"].value_counts().median()
    complete_days = [d for d in all_days if (intraday_df["trading_day"] == d).sum() >= full_day_candle_count * 0.8]
    if start_date is not None:
        complete_days = [d for d in complete_days if d >= start_date]
    if end_date is not None:
        complete_days = [d for d in complete_days if d <= end_date]

    results: list[DayResult] = []
    for day in complete_days:
        daily_history = daily_df[daily_df["date"].dt.date < day]
        if len(daily_history) < MIN_DAILY_HISTORY:
            results.append(DayResult(day.isoformat(), "SKIPPED_INSUFFICIENT_HISTORY", "not enough prior daily rows"))
            continue

        last_daily_date = daily_history["date"].dt.date.iloc[-1]
        if (day - last_daily_date).days > MAX_DAILY_DATA_GAP_DAYS:
            results.append(
                DayResult(day.isoformat(), "SKIPPED_STALE_DAILY_DATA", f"previous daily row is {last_daily_date}")
            )
            continue

        previous_premium, intraday_price = _estimated_pricing(daily_history, day, market)
        plan = build_daily_plan(daily_history["close"].iloc[-1], market, previous_premium)
        if plan.final is None:
            results.append(DayResult(day.isoformat(), "NO_PLAN", plan.reason, **_plan_fields(plan)))
            continue

        candles = intraday_df[intraday_df["trading_day"] == day].drop(columns=["trading_day"]).reset_index(drop=True)
        trades, sideways_candles = simulate_day(day, plan.final, candles, intraday_price, require_cross, **engine_options)
        results.append(
            DayResult(
                day.isoformat(),
                "TRADED" if trades else "NO_TRADE",
                plan.reason,
                sideways_candles=sideways_candles,
                trades=trades,
                **_plan_fields(plan),
            )
        )
    return results


def summarize(results: list[DayResult]) -> None:
    def count(outcome: str) -> int:
        return sum(1 for r in results if r.outcome == outcome)

    trades = [t for r in results for t in r.trades]
    print("PREMIUMS ARE BLACK-SCHOLES ESTIMATES, NOT REAL OPTION PRICES - see sniper_backtester.py\n")
    print(f"Days evaluated:              {len(results)}")
    print(f"  Traded:                    {count('TRADED')}")
    print(f"  No trade (plan, no entry): {count('NO_TRADE')}")
    print(f"  No plan (gap check):       {count('NO_PLAN')}")
    print(f"  Skipped (stale data):      {count('SKIPPED_STALE_DAILY_DATA')}")
    print(f"  Skipped (short history):   {count('SKIPPED_INSUFFICIENT_HISTORY')}")
    print(f"Trades taken:                {len(trades)}")
    if not trades:
        return
    for half in ("first", "second"):
        print(f"  {half} half:                {sum(1 for t in trades if t.half == half)}")
    for reason in ("TARGET", "STOPLOSS", "TRAIL_STOP", "TIME_EXIT_1500", "DATA_END"):
        print(f"  {reason:<25}{sum(1 for t in trades if t.exit_reason == reason)}")
    wins = sum(1 for t in trades if t.pnl_points > 0)
    total = sum(t.pnl_points for t in trades)
    print(f"  Win rate (P&L > 0):        {wins / len(trades) * 100:.1f}%")
    print(f"  Total P&L:                 {total:+.2f} points")
    print(f"  Average P&L per trade:     {total / len(trades):+.2f} points "
          f"({sum(t.pnl_pct for t in trades) / len(trades):+.2f}%)")


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results = run_backtest()

    days_path = RESULTS_DIR / "sniper_days.csv"
    trades_path = RESULTS_DIR / "sniper_trades.csv"
    pd.DataFrame([{k: v for k, v in asdict(r).items() if k != "trades"} for r in results]).to_csv(days_path, index=False)
    pd.DataFrame([asdict(t) for r in results for t in r.trades], columns=list(TradeResult.__dataclass_fields__)).to_csv(
        trades_path, index=False
    )
    print(f"Day-by-day plans saved to {days_path}")
    print(f"Trades saved to {trades_path}\n")
    summarize(results)


if __name__ == "__main__":
    main()
