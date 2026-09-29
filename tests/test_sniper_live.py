"""
Offline tests for sniper_live.py with a fake Kite client - no network, no
credentials. The fake serves PROJECT_STATUS.md §5's worked example (data
28-09-2026, trading 29-09-2026) as if it were Zerodha's real data.
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import sniper_live
from kite_auth import request_token_from
from sniper_engine import SniperDay

IST = timezone(timedelta(hours=5, minutes=30))
TODAY = date(2026, 9, 29)
EXPIRY = date(2026, 9, 29)  # expiry day uses the same-day expiry
PREVIOUS_CLOSES = {
    (23100, "CE"): 147.40,
    (23100, "PE"): 59.20,
    (23200, "CE"): 89.15,
    (23000, "PE"): 34.25,
    (23300, "CE"): 48.80,
    (23200, "PE"): 99.80,
}


def _token(strike, option_type):
    return int(strike) * 10 + (1 if option_type == "CE" else 2)


class FakeKite:
    def __init__(self):
        self.calls = []

    def instruments(self, exchange):
        rows = []
        for expiry in (EXPIRY, EXPIRY + timedelta(days=7), date(2026, 9, 22)):  # includes an expired one
            for strike in range(22500, 23900, 100):
                for option_type in ("CE", "PE"):
                    rows.append(
                        {
                            "instrument_token": _token(strike, option_type) + (0 if expiry == EXPIRY else 7),
                            "tradingsymbol": f"NIFTY{expiry:%y%m%d}{strike}{option_type}",
                            "name": "NIFTY",
                            "segment": "NFO-OPT",
                            "expiry": expiry,
                            "strike": float(strike),
                            "instrument_type": option_type,
                        }
                    )
        rows.append({"name": "BANKNIFTY", "segment": "NFO-OPT", "expiry": EXPIRY, "strike": 50000.0,
                     "instrument_type": "CE", "instrument_token": 1, "tradingsymbol": "X"})
        return rows

    def historical_data(self, token, start, end, interval):
        self.calls.append((token, interval))
        assert interval == "day"
        if token == sniper_live.NIFTY_INDEX_TOKEN:
            close = 23140.5
        else:
            strike, kind = divmod(token, 10)
            close = PREVIOUS_CLOSES[(strike, "CE" if kind == 1 else "PE")]
        return [
            {"date": datetime(2026, 9, 25, tzinfo=IST), "close": 1.0},
            {"date": datetime(2026, 9, 28, tzinfo=IST), "close": close},
        ]


@pytest.fixture(autouse=True)
def _no_rate_limit_pause(monkeypatch):
    monkeypatch.setattr(sniper_live, "HISTORICAL_PAUSE_SECONDS", 0)


def test_morning_plan_matches_worked_example():
    kite = FakeKite()
    plan, options, previous_day = sniper_live.build_morning_plan(kite, TODAY)

    assert options.expiry == EXPIRY
    assert previous_day == date(2026, 9, 28)
    assert [a.atm_strike for a in plan.attempts] == [23100, 23200]
    assert plan.final.sniper == pytest.approx(54.00)
    # Each contract fetched once, even though ATM 23100 PE / 23200 CE appear in both attempts.
    tokens = [t for t, _ in kite.calls]
    assert len(tokens) == len(set(tokens))

    contracts = sniper_live.plan_contracts(plan.final, options)
    assert contracts["otm_pe"]["tradingsymbol"] == "NIFTY26092923100PE"
    assert contracts["otm_ce"]["tradingsymbol"] == "NIFTY26092923300CE"

    text = sniper_live.describe_plan(plan, options.expiry, previous_day)
    assert "buy 23100 PE when a candle closes above 100" in text
    assert "SL 49, target 100" in text


def _candle(hhmm, high, low, close):
    h, m = map(int, hhmm.split(":"))
    return {"date": datetime(2026, 9, 29, h, m, tzinfo=IST), "high": high, "low": low, "close": close}


def _row():
    kite = FakeKite()
    plan, _, _ = sniper_live.build_morning_plan(kite, TODAY)
    return plan.final


def test_completed_bars_skips_forming_candle_and_carries_forward():
    row = _row()
    candles = {
        "atm_ce": [_candle("09:15", 90, 80, 85), _candle("09:20", 86, 70, 72)],
        "atm_pe": [_candle("09:15", 110, 100, 105), _candle("09:20", 120, 104, 118)],
        "otm_ce": [_candle("09:15", 50, 40, 45)],  # no trade in the 09:20 candle
        "otm_pe": [],  # not traded at all yet
    }
    now = datetime(2026, 9, 29, 9, 26)  # 09:25 candle would still be forming
    candles["atm_ce"].append(_candle("09:25", 75, 70, 71))

    bars = sniper_live.completed_bars(candles, set(), now, row)
    assert [w.strftime("%H:%M") for w, _ in bars] == ["09:15", "09:20"]
    second = bars[1][1]
    assert second["otm_ce"].close == 45  # carried from 09:15
    assert second["otm_pe"].close == pytest.approx(59.2)  # yesterday's close

    # Already-processed candles are not returned again.
    assert [w.strftime("%H:%M") for w, _ in sniper_live.completed_bars(candles, {bars[0][0]}, now, row)] == ["09:20"]


def test_live_bars_drive_the_engine_to_an_entry():
    """Real-option-shaped candles: the market falls, OTM PE 23100 closes above 100 at 09:40."""
    row = _row()
    quiet = dict(atm_ce=(90, 80, 85), atm_pe=(105, 95, 100), otm_ce=(50, 45, 47), otm_pe=(62, 55, 58))
    fall = dict(atm_ce=(80, 60, 62), atm_pe=(130, 110, 128), otm_ce=(40, 30, 31), otm_pe=(104, 80, 103))
    candles = {key: [] for key in quiet}
    for hhmm, shape in (("09:30", quiet), ("09:35", quiet), ("09:40", fall)):
        for key, (h, l, c) in shape.items():
            candles[key].append(_candle(hhmm, h, l, c))

    engine = SniperDay(TODAY, row)
    events = []
    for when, bars in sniper_live.completed_bars(candles, set(), datetime(2026, 9, 29, 9, 50), row):
        events += engine.on_candle(when, bars)

    [entry] = events
    assert entry.kind == "ENTRY"
    assert (entry.trade.buy_strike, entry.trade.buy_type, entry.trade.entry_fill) == (23100, "PE", 103)
    assert (entry.trade.stop_loss, entry.trade.target) == (81, 144)


def test_next_poll_waits_for_candle_close():
    assert sniper_live._next_poll(datetime(2026, 9, 29, 8, 50)) == datetime(2026, 9, 29, 9, 20, 20)
    assert sniper_live._next_poll(datetime(2026, 9, 29, 9, 41, 3)) == datetime(2026, 9, 29, 9, 45, 20)
    assert sniper_live._next_poll(datetime(2026, 9, 29, 9, 45, 0)) == datetime(2026, 9, 29, 9, 45, 20)
    assert sniper_live._next_poll(datetime(2026, 9, 29, 9, 45, 20)) == datetime(2026, 9, 29, 9, 50, 20)


class _Clock:
    def __init__(self, start):
        self.now = start

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


def test_full_day_watch_loop_with_fake_clock(monkeypatch, tmp_path):
    """Runs watch() from 09:00 to the end of day on a fake clock: the bot must
    only see candles that have closed, enter at 09:40, exit on target at 09:45,
    and stop by itself at 15:00."""
    clock = _Clock(datetime(2026, 9, 29, 9, 0))

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now

    class FakeTime:
        sleep = staticmethod(clock.sleep)

    monkeypatch.setattr(sniper_live, "datetime", FakeDatetime)
    monkeypatch.setattr(sniper_live, "time_module", FakeTime)
    monkeypatch.setattr(sniper_live, "OUT_DIR", tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    row = _row()
    quiet = dict(atm_ce=(90, 80, 85), atm_pe=(105, 95, 100), otm_ce=(50, 45, 47), otm_pe=(62, 55, 58))
    script = {
        "09:40": dict(atm_ce=(80, 60, 62), atm_pe=(130, 110, 128), otm_ce=(40, 30, 31), otm_pe=(104, 80, 103)),
        "09:45": dict(atm_ce=(62, 40, 45), atm_pe=(170, 125, 160), otm_ce=(31, 20, 22), otm_pe=(150, 100, 140)),
    }
    token_key = {c["instrument_token"]: key for key, c in sniper_live.plan_contracts(row, FakeKite_options()).items()}
    seen_future = []

    class LiveKite:
        def historical_data(self, token, start, end, interval):
            assert interval == "5minute"
            out = []
            t = datetime(2026, 9, 29, 9, 15)
            while t <= end and t.time() < sniper_live.time(15, 30):
                shape = script.get(t.strftime("%H:%M"), quiet)[token_key[token]]
                out.append(_candle(t.strftime("%H:%M"), *shape))
                t += timedelta(minutes=5)
            if out and _naive_start(out[-1]) + timedelta(minutes=5) > end:
                seen_future.append(True)  # the still-forming candle, which the bot must ignore
            return out

    engine = SniperDay(TODAY, row)
    contracts = sniper_live.plan_contracts(row, FakeKite_options())
    sniper_live.watch(LiveKite(), engine, contracts, sniper_live.Notifier(TODAY))

    assert engine.done
    [trade] = engine.trades
    assert (trade.entry_time[11:16], trade.entry_fill, trade.exit_reason, trade.exit_premium) == ("09:40", 103, "TARGET", 144)
    assert seen_future  # the fake did serve forming candles, and they were skipped
    assert clock.now.time() < sniper_live.time(15, 5)
    log = (tmp_path / "log_2026-09-29.txt").read_text(encoding="utf-8")
    assert "WOULD BUY 325 x NIFTY26092923100PE at 103.00" in log
    assert "WOULD EXIT 325 x NIFTY26092923100PE at 144.00 - TARGET" in log
    assert "Rs +13,325" in log  # 41 points x 325 qty
    assert "catch-up" not in log


def FakeKite_options():
    return sniper_live.NiftyOptions(FakeKite(), TODAY)


def _naive_start(candle):
    return candle["date"].replace(tzinfo=None)


def test_request_token_from_url_or_token():
    url = "http://127.0.0.1/?action=login&type=login&status=success&request_token=abc123XYZ"
    assert request_token_from(url) == "abc123XYZ"
    assert request_token_from("  abc123XYZ \n") == "abc123XYZ"
    with pytest.raises(SystemExit):
        request_token_from("https://kite.zerodha.com/connect/finish?api_key=k&sess_id=s")
