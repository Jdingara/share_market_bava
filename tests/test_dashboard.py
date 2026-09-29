"""The dashboard serves the page, the live state and the all-days history."""

import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import dashboard
from history import record_day
from sniper_signal import MARKETS, build_daily_plan

PREMIUMS = {(23100, "CE"): 147.40, (23100, "PE"): 59.20, (23200, "CE"): 89.15,
            (23000, "PE"): 34.25, (23300, "CE"): 48.80, (23200, "PE"): 99.80}


def test_dashboard_serves_page_state_and_history(monkeypatch, tmp_path):
    plan = build_daily_plan(23140.5, MARKETS["NIFTY"], lambda k, t: PREMIUMS[(k, t)])
    record_day(date(2026, 9, 28), "NIFTY", plan, "2026-09-29", "2026-09-25", 325, [], {}, "finished", history_dir=tmp_path)
    monkeypatch.setattr(dashboard, "HISTORY_DIR", tmp_path)

    url = dashboard.start_dashboard(dashboard.DashboardState("LIVE", "2026-09-29", 325, "NIFTY"), port=8190)
    get = lambda path: urllib.request.urlopen(url + path, timeout=5).read()

    assert b"History" in get("/")
    assert json.loads(get("/api/state"))["market"] == "NIFTY"
    history = json.loads(get("/api/history"))
    assert [(d["date"], d["market"], d["status"]) for d in history["days"]] == [("2026-09-28", "NIFTY", "finished")]
