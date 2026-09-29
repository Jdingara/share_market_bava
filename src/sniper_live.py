"""
Sniper strategy, PAPER MODE on live Zerodha data (PROJECT_STATUS.md §6, phase 2).
It never places orders - it only reports what it WOULD buy and sell.

    py src\\kite_auth.py          (once each morning)
    py src\\sniper_live.py        (start before 09:15 and leave running until 15:00)
    py src\\sniper_live.py --plan-only    (just print today's morning plan)
    py src\\sniper_live.py --replay 2026-09-25    (re-run a recent day on its real candles)
    py src\\sniper_live.py --market SENSEX     (SENSEX instead of NIFTY - run both in two windows)

While it runs, a dashboard is open at http://127.0.0.1:8050 for NIFTY, :8051 for SENSEX (this PC only).

Morning: builds the plan from the previous trading day's real closing prices -
NIFTY index close, then ATM / OTM option closes for the nearest expiry, gap
check and shifts (spec §1). During the day: after every 5-minute candle closes,
fetches the 4 plan contracts' real candles and feeds them to the same
sniper_engine.SniperDay used by the backtester. Entries and exits are printed,
logged to data/paper_trades/, and sent to Telegram if configured in .env.

The PC clock is assumed to be Indian time (IST).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time as time_module
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Optional

import webbrowser

from dotenv import load_dotenv

from dashboard import DashboardState, start_dashboard
from history import record_day

from kite_auth import PROJECT_ROOT, connected_client
from sniper_engine import CONTRACT_KEYS, Bar, Event, SniperDay, TradeResult
from sniper_signal import (
    CANDLE_MINUTES,
    EXIT_BY,
    MARKETS,
    DailyPlan,
    MarketConfig,
    StrikeRow,
    build_daily_plan,
    trade_setups,
)

NIFTY_INDEX_TOKEN = MARKETS["NIFTY"].index_token
DASHBOARD_PORTS = {"NIFTY": 8050, "SENSEX": 8051}
MARKET_OPEN = time(9, 15)
POLL_DELAY_SECONDS = 20  # after each 5-minute boundary, give Kite time to publish the finished candle
HISTORICAL_PAUSE_SECONDS = 0.35  # Kite's historical API allows 3 requests/second
NO_DATA_GIVE_UP = time(9, 45)  # no candles by then -> treat as a market holiday
OUT_DIR = PROJECT_ROOT / "data" / "paper_trades"


# --- Kite data --------------------------------------------------------------


class OptionChain:
    """Today's nearest-expiry option contracts for one index, from Kite's instrument list."""

    def __init__(self, kite, today: date, market: MarketConfig = MARKETS["NIFTY"]):
        exchange, name = market.options_exchange, market.name
        self.name = name
        rows = [i for i in kite.instruments(exchange) if i["name"] == name and i["segment"] == f"{exchange}-OPT"]
        upcoming = [i["expiry"] for i in rows if i["expiry"] >= today]
        if not upcoming:
            raise SystemExit(f"No {name} option expiries found on/after today in Kite's instrument list.")
        self.expiry: date = min(upcoming)
        self.by_key = {(float(i["strike"]), i["instrument_type"]): i for i in rows if i["expiry"] == self.expiry}

    def contract(self, strike: float, option_type: str) -> dict:
        try:
            return self.by_key[(float(strike), option_type)]
        except KeyError:
            raise SystemExit(f"No {self.name} {strike:g} {option_type} contract listed for expiry {self.expiry}") from None


NiftyOptions = OptionChain


HISTORICAL_ATTEMPTS = 3  # Kite occasionally times out (7 s) - retry before giving up

# Owner, 2026-09-29: BSE's correct SENSEX closing prices are only there after 08:30 the next morning.
PLAN_NOT_BEFORE = {"SENSEX": time(8, 31)}


def plan_wait_until(market_name: str, now: datetime) -> Optional[datetime]:
    """When the morning plan may be built, if that's later than now (else None)."""
    earliest = PLAN_NOT_BEFORE.get(market_name)
    if earliest is None or now.time() >= earliest:
        return None
    return datetime.combine(now.date(), earliest)


def wait_for_closing_prices(market_name: str, set_status) -> None:
    until = plan_wait_until(market_name, datetime.now())
    if until:
        set_status(f"Waiting until {until:%H:%M} for the final {market_name} closing prices (BSE updates them after 08:30)")
        print(f"Waiting until {until:%H:%M} for the final {market_name} closing prices...", flush=True)
        _sleep_until(until)


def _historical(kite, token: int, start: datetime, end: datetime, interval: str) -> list[dict]:
    for attempt in range(1, HISTORICAL_ATTEMPTS + 1):
        time_module.sleep(HISTORICAL_PAUSE_SECONDS * attempt)
        try:
            return kite.historical_data(token, start, end, interval)
        except Exception as error:  # network timeouts, 429s, Kite 5xx
            if attempt == HISTORICAL_ATTEMPTS or "Token" in type(error).__name__:
                raise
            print(f"  (Kite request failed: {type(error).__name__} - retrying, attempt {attempt + 1})", flush=True)


def _naive(ts: datetime) -> datetime:
    return ts.replace(tzinfo=None)


def previous_daily_close(kite, token: int, today: date) -> tuple[date, float]:
    """(date, close) of the last daily candle before today."""
    start = datetime.combine(today - timedelta(days=14), time(0, 0))
    end = datetime.combine(today - timedelta(days=1), time(23, 59))
    candles = [c for c in _historical(kite, token, start, end, "day") if _naive(c["date"]).date() < today]
    if not candles:
        raise SystemExit(f"No daily candles before {today} for instrument {token}")
    last = candles[-1]
    return _naive(last["date"]).date(), float(last["close"])


def build_morning_plan(kite, today: date, market: MarketConfig = MARKETS["NIFTY"]) -> tuple[DailyPlan, OptionChain, date]:
    options = OptionChain(kite, today, market)
    previous_day, index_close = previous_daily_close(kite, market.index_token, today)
    cache: dict[tuple[float, str], float] = {}

    def premium(strike: float, option_type: str) -> float:
        if (strike, option_type) not in cache:
            contract = options.contract(strike, option_type)
            close_day, close = previous_daily_close(kite, contract["instrument_token"], today)
            if close_day != previous_day:
                print(f"  WARNING: {contract['tradingsymbol']} last traded {close_day}, index closed {previous_day}")
            cache[(strike, option_type)] = close
        return cache[(strike, option_type)]

    return build_daily_plan(index_close, market, premium), options, previous_day


def plan_contracts(row: StrikeRow, options: NiftyOptions) -> dict[str, dict]:
    return {
        "atm_ce": options.contract(row.atm_strike, "CE"),
        "atm_pe": options.contract(row.atm_strike, "PE"),
        "otm_ce": options.contract(row.otm_ce_strike, "CE"),
        "otm_pe": options.contract(row.otm_pe_strike, "PE"),
    }


def completed_bars(
    candles: dict[str, list[dict]], processed: set[datetime], now: datetime, row: StrikeRow
) -> list[tuple[datetime, dict[str, Bar]]]:
    """New, fully closed 5-minute candles as engine input, oldest first. Kite
    also returns the still-forming candle, which is skipped until it closes. If
    a contract had no trades in some candle, its last close carries forward
    (yesterday's close if it has not traded yet today)."""
    by_key = {key: {_naive(c["date"]): c for c in candles.get(key, [])} for key in CONTRACT_KEYS}
    closed_times = sorted(
        t for times in by_key.values() for t in times if t + timedelta(minutes=CANDLE_MINUTES) <= now
    )
    last_close = {
        "atm_ce": row.atm_ce_close,
        "atm_pe": row.atm_pe_close,
        "otm_ce": row.otm_ce_close,
        "otm_pe": row.otm_pe_close,
    }
    result = []
    for when in dict.fromkeys(closed_times):
        bars = {}
        for key in CONTRACT_KEYS:
            candle = by_key[key].get(when)
            if candle is None:
                bars[key] = Bar(last_close[key], last_close[key], last_close[key])
            else:
                bars[key] = Bar(float(candle["high"]), float(candle["low"]), float(candle["close"]),
                               float(candle["open"]) if candle.get("open") is not None else None)
                last_close[key] = bars[key].close
        if when not in processed:
            result.append((when, bars))
    return result


# --- Reporting --------------------------------------------------------------


class Notifier:
    """Prints, appends to today's log file, and sends to Telegram when
    TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in .env."""

    def __init__(self, today: date, state: Optional[DashboardState] = None, prefix: str = "log", phone: bool = True):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.log_path = OUT_DIR / f"{prefix}_{today.isoformat()}.txt"
        self.state = state
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN") if phone else None
        self.telegram_chat = os.getenv("TELEGRAM_CHAT_ID")

    def send(self, message: str, phone: bool = True) -> None:
        stamped = f"[{datetime.now():%H:%M:%S}] {message}"
        print(stamped, flush=True)
        with self.log_path.open("a", encoding="utf-8") as log:
            log.write(stamped + "\n")
        if self.state:
            self.state.log(message)
        if phone and self.telegram_token and self.telegram_chat:
            try:
                data = urllib.parse.urlencode({"chat_id": self.telegram_chat, "text": message}).encode()
                urllib.request.urlopen(f"https://api.telegram.org/bot{self.telegram_token}/sendMessage", data, timeout=10)
            except Exception as error:  # an alert failure must never stop the bot
                print(f"  (Telegram send failed: {error})", flush=True)


def describe_plan(plan: DailyPlan, expiry: date, previous_day: date) -> str:
    lines = [f"SNIPER PLAN (paper) - {plan.market} close {plan.index_close:g} on {previous_day}, expiry {expiry}"]
    for a in plan.attempts:
        lines.append(
            f"  ATM {a.atm_strike:g}: ATM CE {a.atm_ce_close:.2f} / PE {a.atm_pe_close:.2f}, "
            f"OTM {a.otm_ce_strike:g} CE {a.otm_ce_close:.2f} / {a.otm_pe_strike:g} PE {a.otm_pe_close:.2f}, "
            f"Sniper {a.sniper:.2f}, gaps CE {a.ce_gap:+.2f} {'OK' if a.ce_ok else 'FAIL'} "
            f"PE {a.pe_gap:+.2f} {'OK' if a.pe_ok else 'FAIL'}"
        )
    if plan.final is None:
        lines.append(f"NO PLAN TODAY: {plan.reason}")
        return "\n".join(lines)
    lines.append(f"FINAL: {plan.reason}, Sniper {plan.final.sniper:.2f}")
    for s in trade_setups(plan.final):
        lines.append(
            f"  {s.half:<6} half, market {s.direction:<4}: buy {s.buy_strike:g} {s.buy_type} "
            f"when a candle closes above {s.levels.entry} (trigger {s.levels.trigger:.2f}) - "
            f"SL {s.levels.stop_loss}, target {s.levels.target}"
        )
    return "\n".join(lines)


def describe_event(event: Event, contracts: dict[str, dict], late: bool, qty: int = MARKETS["NIFTY"].quantity) -> str:
    note = "  (catch-up: this candle closed before the bot started)" if late else ""
    if event.kind in ("ORDER", "CANCEL"):
        symbol = contracts["otm_ce" if event.setup.buy_type == "CE" else "otm_pe"]["tradingsymbol"]
        trigger = event.setup.levels.trigger
        note = (" - HIGH confidence: ATM already below Sniper" if event.atm_below_sniper else "") + note
        if event.kind == "ORDER" and event.square:
            return (f"SIGNAL {symbol}: candle {event.when:%H:%M} closed {event.signal_close:.2f} (above trigger {trigger:.2f}) - "
                    f"WOULD BUY {qty} at {event.square} if it comes back, or at {event.next_square} if it runs up{note}")
        if event.kind == "ORDER":
            return (f"SIGNAL {symbol}: candle {event.when:%H:%M} closed {event.signal_close:.2f} (above trigger {trigger:.2f}) - "
                    f"WOULD BUY {qty} at {event.next_square} when it rises there{note}")
        levels = f"{event.square}/{event.next_square}" if event.square else f"{event.next_square}"
        return f"Order for {symbol} at {levels} cancelled - window ended without a fill{note}"
    t = event.trade
    symbol = contracts["otm_ce" if t.buy_type == "CE" else "otm_pe"]["tradingsymbol"]
    if event.kind == "ENTRY":
        conf = " - HIGH confidence: ATM below Sniper" if t.atm_below_sniper else ""
        return (f"WOULD BUY {qty} x {symbol} at {t.entry_fill:.2f} ({t.half} half, candle {t.entry_time[11:16]}) - "
                f"SL {t.stop_loss} (trails up), target {t.target}{conf}{note}")
    return (f"WOULD EXIT {qty} x {symbol} at {t.exit_premium:.2f} - {t.exit_reason} "
            f"(bought {t.entry_fill:.2f}, P&L {t.pnl_points:+.2f} points = Rs {t.pnl_points * qty:+,.0f}){note}")


def save_trades(trades: list[TradeResult], today: date, prefix: str = "trades") -> Optional[Path]:
    if not trades:
        return None
    path = OUT_DIR / f"{prefix}_{today.isoformat()}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(TradeResult.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(t) for t in trades)
    return path


# --- Main loop --------------------------------------------------------------


def _sleep_until(target: datetime) -> None:
    while (remaining := (target - datetime.now()).total_seconds()) > 0:
        time_module.sleep(min(remaining, 30))


def _next_poll(now: datetime) -> datetime:
    """The next moment POLL_DELAY_SECONDS after a 5-minute boundary (never before 09:20:20)."""
    delay = timedelta(seconds=POLL_DELAY_SECONDS)
    boundary = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % CANDLE_MINUTES)
    if boundary + delay <= now:
        boundary += timedelta(minutes=CANDLE_MINUTES)
    first = datetime.combine(now.date(), MARKET_OPEN) + timedelta(minutes=CANDLE_MINUTES)
    return max(boundary, first) + delay


def _feed(engine: SniperDay, when: datetime, bars: dict[str, Bar], contracts: dict[str, dict], notify: Notifier,
          state: Optional[DashboardState], late: bool = False, qty: int = MARKETS["NIFTY"].quantity,
          recorder: Optional[Callable[[str], None]] = None) -> None:
    if state:
        state.add_candle(when, bars)
    events = engine.on_candle(when, bars)
    for event in events:
        if late and event.kind == "ENTRY":
            event.trade.note = "catch-up"
        notify.send(describe_event(event, contracts, late, qty))
    if events and recorder:
        recorder("watching")
    if state:
        state.set_trades(engine.trades)
        state.set_status(f"Last candle {when:%H:%M} processed" + (" - day finished" if engine.done else ""))


def watch(kite, engine: SniperDay, contracts: dict[str, dict], notify: Notifier,
          state: Optional[DashboardState] = None, qty: int = MARKETS["NIFTY"].quantity,
          recorder: Optional[Callable[[str], None]] = None) -> None:
    today, row = engine.day, engine.row
    processed: set[datetime] = set()
    started = datetime.now()
    session_start = datetime.combine(today, MARKET_OPEN)
    last_bars: Optional[tuple[datetime, dict[str, Bar]]] = None

    while not engine.done:
        now = datetime.now()
        if now.time() >= (datetime.combine(today, EXIT_BY) + timedelta(minutes=5)).time():
            break
        next_poll = _next_poll(now)
        if state:
            state.set_status(f"Waiting for the next candle - checking at {next_poll:%H:%M:%S}")
        _sleep_until(next_poll)
        now = datetime.now()

        try:
            candles = {
                key: _historical(kite, c["instrument_token"], session_start, now, f"{CANDLE_MINUTES}minute")
                for key, c in contracts.items()
            }
        except Exception as error:  # network hiccup / Kite error: never let it end the day - retry next candle
            notify.send(f"Zerodha data fetch failed ({type(error).__name__}: {error}) - retrying at the next candle.",
                        phone=False)
            continue
        new = completed_bars(candles, processed, now, row)
        if not new and not processed and now.time() >= NO_DATA_GIVE_UP:
            notify.send("No option candles received today - market holiday? Stopping.")
            break

        for when, bars in new:
            processed.add(when)
            last_bars = (when, bars)
            late = when + timedelta(minutes=CANDLE_MINUTES) < started
            _feed(engine, when, bars, contracts, notify, state, late, qty, recorder)
            if engine.done:
                break

    if engine.open_trades and last_bars:
        for event in engine.finish(*last_bars):
            notify.send(describe_event(event, contracts, False, qty))


def replay(kite, engine: SniperDay, contracts: dict[str, dict], notify: Notifier, state: DashboardState,
           seconds_per_candle: float, qty: int = MARKETS["NIFTY"].quantity) -> None:
    """Re-runs a past day on its real 5-minute option candles, paced so the
    dashboard can be watched filling in."""
    day = engine.day
    start, end = datetime.combine(day, MARKET_OPEN), datetime.combine(day, time(15, 30))
    candles = {
        key: _historical(kite, c["instrument_token"], start, end, f"{CANDLE_MINUTES}minute") for key, c in contracts.items()
    }
    bars_list = completed_bars(candles, set(), end + timedelta(minutes=CANDLE_MINUTES), engine.row)
    if not bars_list:
        notify.send(f"No option candles for {day} - not a trading day, or the contracts are no longer listed.")
        return
    for when, bars in bars_list:
        _feed(engine, when, bars, contracts, notify, state, qty=qty)
        if engine.done:
            break
        time_module.sleep(seconds_per_candle)
    if engine.open_trades:
        for event in engine.finish(*bars_list[-1]):
            notify.send(describe_event(event, contracts, False, qty))


def _keep_dashboard_open(url: str) -> None:
    print(f"\nDashboard stays open at {url} - press Ctrl+C (or close this window) to stop.", flush=True)
    try:
        while True:
            time_module.sleep(3600)
    except KeyboardInterrupt:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Sniper strategy - paper mode on live Zerodha data (no orders).")
    parser.add_argument("--plan-only", action="store_true", help="show today's morning plan only")
    parser.add_argument("--replay", metavar="YYYY-MM-DD", help="re-run a recent trading day on its real candles")
    parser.add_argument("--speed", type=float, default=0.5, help="replay: seconds per candle (default 0.5)")
    parser.add_argument("--no-browser", action="store_true", help="don't open the dashboard automatically")
    parser.add_argument("--market", choices=sorted(MARKETS), default="NIFTY", help="index to trade (default NIFTY)")
    args = parser.parse_args()
    market = MARKETS[args.market]
    qty = market.quantity

    load_dotenv(PROJECT_ROOT / ".env")
    day = date.fromisoformat(args.replay) if args.replay else date.today()
    if not args.replay and day.weekday() >= 5:
        raise SystemExit("Today is a weekend - no market. To see the bot work, replay a recent day:\n"
                         "  py src\\sniper_live.py --replay YYYY-MM-DD")
    utc_offset = datetime.now().astimezone().utcoffset()
    if utc_offset != timedelta(hours=5, minutes=30):
        print(f"WARNING: PC clock is UTC{utc_offset}, not IST - candle times will be wrong.")

    kite = connected_client()
    state = DashboardState("REPLAY" if args.replay else "LIVE", day.isoformat(), qty, market.name)
    url = start_dashboard(state, DASHBOARD_PORTS[market.name])
    print(f"Dashboard: {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)

    prefix = ("replay_" if args.replay else "") + ("" if market.name == "NIFTY" else f"{market.name}_")
    notify = Notifier(day, state, prefix=f"{prefix}log", phone=not args.replay)
    notify.send(("REPLAY of " + day.isoformat() if args.replay else f"Sniper bot started ({market.name}, {qty} qty)")
                + " - PAPER MODE, no real orders.",
                phone=False)

    if not args.replay:
        wait_for_closing_prices(market.name, state.set_status)
    state.set_status("Building the morning plan from yesterday's closing prices...")
    plan, options, previous_day = build_morning_plan(kite, day, market)
    contracts = plan_contracts(plan.final, options) if plan.final else {}
    state.set_plan(plan, options.expiry.isoformat(), previous_day.isoformat(), contracts)
    notify.send(describe_plan(plan, options.expiry, previous_day))
    (OUT_DIR / f"{prefix}plan_{day.isoformat()}.json").write_text(
        json.dumps(
            {"index_close": plan.index_close, "reason": plan.reason, "expiry": options.expiry.isoformat(),
             "attempts": [asdict(a) for a in plan.attempts], "final": asdict(plan.final) if plan.final else None},
            indent=2,
        )
    )
    symbols = {"CE": contracts["otm_ce"]["tradingsymbol"], "PE": contracts["otm_pe"]["tradingsymbol"]} if contracts else {}
    engine: Optional[SniperDay] = None

    def record(status: str) -> None:
        """Writes today's plan and trades to history/ (live runs only)."""
        if args.replay or args.plan_only:
            return
        try:
            record_day(day, market.name, plan, options.expiry.isoformat(), previous_day.isoformat(), qty,
                       engine.trades if engine else [], symbols, status)
        except Exception as error:  # history must never stop the bot
            print(f"  (history update failed: {error})", flush=True)

    if plan.final is None:
        record("no plan")
    if args.plan_only or plan.final is None:
        state.set_status("No plan today." if plan.final is None else "Plan only - not watching the market.")
        _keep_dashboard_open(url)
        return

    notify.send("Watching " + ", ".join(c["tradingsymbol"] for c in contracts.values()) + " until 15:00.", phone=False)
    engine = SniperDay(day, plan.final)
    record("watching")
    status = "finished"
    try:
        if args.replay:
            replay(kite, engine, contracts, notify, state, args.speed, qty)
        else:
            watch(kite, engine, contracts, notify, state, qty, record)
    except KeyboardInterrupt:
        status = "stopped early (Ctrl+C)"
        notify.send("Stopped by user (Ctrl+C).", phone=False)
    record(status)
    path = save_trades(engine.trades, day, prefix=f"{prefix}trades")
    total = sum(t.pnl_points for t in engine.trades if t.exit_reason)
    state.set_trades(engine.trades)
    state.set_status(f"Day finished: {len(engine.trades)} paper trade(s), P&L {total:+.2f} points = Rs {total * qty:+,.0f}")
    notify.send(f"Day finished: {len(engine.trades)} paper trade(s), P&L {total:+.2f} points = Rs {total * qty:+,.0f}."
                + (f" Saved to {path}" if path else ""))
    _keep_dashboard_open(url)


if __name__ == "__main__":
    main()
