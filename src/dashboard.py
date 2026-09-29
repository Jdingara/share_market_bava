"""
Local web dashboard for the paper bot: http://127.0.0.1:8050 (only reachable
from this PC). The bot updates a DashboardState as it works; the page
(dashboard.html) polls /api/state every few seconds and redraws. Standard
library only - no extra packages.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from history import HISTORY_DIR, _read
from sniper_engine import CONTRACT_KEYS, Bar, TradeResult
from sniper_signal import DailyPlan, trade_setups

PAGE = Path(__file__).resolve().parent / "dashboard.html"
DEFAULT_PORT = 8050


class DashboardState:
    def __init__(self, mode: str, day: str, quantity: int = 0, market: str = "NIFTY"):
        self._lock = threading.Lock()
        self._data = {
            "mode": mode,  # "LIVE" | "REPLAY"
            "market": market,
            "day": day,
            "quantity": quantity,  # units per trade, for rupee P&L
            "status": "Starting...",
            "plan": None,
            "setups": [],
            "contracts": {},
            "candles": [],  # [{"time": "HH:MM", "atm_ce": close, ...}]
            "trades": [],
            "log": [],
            "updated": "",
        }

    def _touch(self) -> None:
        self._data["updated"] = datetime.now().strftime("%H:%M:%S")

    def set_status(self, status: str) -> None:
        with self._lock:
            self._data["status"] = status
            self._touch()

    def log(self, message: str) -> None:
        with self._lock:
            self._data["log"].append({"time": datetime.now().strftime("%H:%M:%S"), "text": message})
            self._touch()

    def set_plan(self, plan: DailyPlan, expiry: str, previous_day: str, contracts: dict[str, dict]) -> None:
        with self._lock:
            self._data["plan"] = {
                "index_close": plan.index_close,
                "previous_day": previous_day,
                "expiry": expiry,
                "reason": plan.reason,
                "attempts": [asdict(a) for a in plan.attempts],
                "final": asdict(plan.final) if plan.final else None,
            }
            self._data["contracts"] = {key: c["tradingsymbol"] for key, c in contracts.items()}
            self._data["setups"] = (
                [
                    {
                        "half": s.half,
                        "direction": s.direction,
                        "buy_strike": s.buy_strike,
                        "buy_type": s.buy_type,
                        "trigger": round(s.levels.trigger, 2),
                        "entry": s.levels.entry,
                        "stop_loss": s.levels.stop_loss,
                        "target": s.levels.target,
                    }
                    for s in trade_setups(plan.final)
                ]
                if plan.final
                else []
            )
            self._touch()

    def add_candle(self, when: datetime, bars: dict[str, Bar]) -> None:
        with self._lock:
            self._data["candles"].append({"time": when.strftime("%H:%M"), **{k: round(bars[k].close, 2) for k in CONTRACT_KEYS}})
            self._touch()

    def set_trades(self, trades: list[TradeResult]) -> None:
        with self._lock:
            self._data["trades"] = [asdict(t) for t in trades]
            self._touch()

    def to_json(self) -> bytes:
        with self._lock:
            return json.dumps(self._data).encode("utf-8")


def start_dashboard(state: DashboardState, port: int = DEFAULT_PORT) -> str:
    """Serves the dashboard in a background thread; returns its URL. Tries the
    next few ports if one is busy (e.g. a second bot window)."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/state"):
                body, content_type = state.to_json(), "application/json"
            elif self.path.startswith("/api/history"):
                history = {"days": _read(HISTORY_DIR / "days.csv"), "trades": _read(HISTORY_DIR / "trades.csv")}
                body, content_type = json.dumps(history).encode("utf-8"), "application/json"
            elif self.path in ("/", "/index.html"):
                body, content_type = PAGE.read_bytes(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # keep the console for bot messages
            pass

    for candidate in range(port, port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
        except OSError:
            continue
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{candidate}"
    raise SystemExit(f"Could not start the dashboard - ports {port}-{port + 9} are all in use.")
