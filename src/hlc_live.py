"""
HLC strategy on Zerodha data - PAPER ONLY, never places orders.

    py src\\hlc_live.py --replay 2026-09-29 [--market NIFTY|SENSEX]

For now this replays a recent trading day on its real 5-minute candles (the
option contracts must still be listed) and prints the morning plan and every
decision. The live watch loop, dashboard and history follow once the owner has
checked replays against their own charts.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta

from hlc_engine import HlcDay
from hlc_signal import HLC_MARKETS, Candle, choose_atm, hlc_levels, leg_label
from kite_auth import connected_client
from sniper_live import OptionChain, _historical, _naive
from sniper_signal import MARKETS


def previous_day_candle(kite, token: int, day: date) -> tuple[date, dict]:
    start = datetime.combine(day - timedelta(days=14), time(0, 0))
    end = datetime.combine(day - timedelta(days=1), time(23, 59))
    candles = [c for c in _historical(kite, token, start, end, "day") if _naive(c["date"]).date() < day]
    if not candles:
        raise SystemExit(f"No daily candles before {day} for instrument {token}")
    return _naive(candles[-1]["date"]).date(), candles[-1]


def morning_plan(kite, day: date, market_name: str):
    market = HLC_MARKETS[market_name]
    chain = OptionChain(kite, day, MARKETS[market_name])
    prev_day, idx = previous_day_candle(kite, MARKETS[market_name].index_token, day)
    cache: dict[tuple[float, str], dict] = {}

    def daily(strike, option_type):
        if (strike, option_type) not in cache:
            contract = chain.by_key.get((float(strike), option_type))
            cache[(strike, option_type)] = previous_day_candle(kite, contract["instrument_token"], day)[1] if contract else None
        return cache[(strike, option_type)]

    atm = choose_atm(idx["close"], market.strike_step, lambda k, t: (daily(k, t) or {}).get("close"))
    ce, pe = daily(atm, "CE"), daily(atm, "PE")
    levels = hlc_levels(idx["close"], atm, ce["close"], pe["close"])
    return chain, prev_day, idx, levels, ce, pe


def replay(day: date, market_name: str) -> None:
    kite = connected_client()
    market = HLC_MARKETS[market_name]
    chain, prev_day, idx, lv, ce, pe = morning_plan(kite, day, market_name)
    print(f"HLC PLAN {market_name} {day} (PAPER) - close {idx['close']} on {prev_day}, expiry {chain.expiry}")
    print(f"  ATM {lv.atm:g}: CE H {ce['high']} L {ce['low']} C {ce['close']} -> {leg_label(ce['high'], ce['low'], ce['close'])}; "
          f"PE H {pe['high']} L {pe['low']} C {pe['close']} -> {leg_label(pe['high'], pe['low'], pe['close'])}")
    print("  " + "  ".join(f"{n} {v:g}" for n, v in reversed(lv.ladder())))

    start, end = datetime.combine(day, time(9, 15)), datetime.combine(day, time(15, 30))
    index = _historical(kite, MARKETS[market_name].index_token, start, end, "5minute")
    if not index:
        raise SystemExit(f"No index candles for {day}")
    step = market.strike_step
    lo = int(min(c["low"] for c in index) // step - 7) * step
    hi = int(max(c["high"] for c in index) // step + 8) * step
    premiums: dict[tuple[float, str], dict[datetime, Candle]] = {}
    for strike in range(lo, hi + step, step):
        for option_type in ("CE", "PE"):
            contract = chain.by_key.get((float(strike), option_type))
            if contract:
                rows = _historical(kite, contract["instrument_token"], start, end, "5minute")
                premiums[(float(strike), option_type)] = {
                    _naive(r["date"]): Candle(r["open"], r["high"], r["low"], r["close"]) for r in rows}

    engine = HlcDay(day, lv, market, {"CE": (ce["high"], ce["low"], ce["close"]), "PE": (pe["high"], pe["low"], pe["close"])})
    for row in index:
        when = _naive(row["date"])
        bar = Candle(row["open"], row["high"], row["low"], row["close"])
        chain_now = {key: series[when] for key, series in premiums.items() if when in series}
        for event in engine.on_candle(when, bar, chain_now):
            print(f"[{when:%H:%M}-{(when + timedelta(minutes=5)):%H:%M}] {event}")
        if engine.done:
            break

    total = sum(t.pnl_points for t in engine.trades if t.exit_reason)
    print(f"\n{len(engine.trades)} trade(s), {total:+.2f} points = Rs {total * market.quantity:+,.0f} "
          f"({market.quantity} qty, paper, before charges)")


def main() -> None:
    parser = argparse.ArgumentParser(description="HLC strategy - paper replay on real Zerodha candles (no orders).")
    parser.add_argument("--replay", metavar="YYYY-MM-DD", required=True)
    parser.add_argument("--market", choices=sorted(HLC_MARKETS), default="NIFTY")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    replay(date.fromisoformat(args.replay), args.market)


if __name__ == "__main__":
    main()
