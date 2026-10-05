"""
The day's real-money account, shared by the 4 bot processes through one JSON
file (.cache/live/account_<date>.json, written under a lock):

  - each bot registers the estimated cost of one lot once its plan is built;
  - at 09:20 the first bot to look reads the money available in Zerodha and
    splits it (live_money.allocate) - every bot then reads its own share;
  - every few seconds each bot reports its P&L (booked + open); when all the
    bots together have lost 50% of the morning money, the day is halted and
    every bot sells what it holds and stops buying;
  - a file named STOP in the project folder (stop_all.bat) halts the day too.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable, Optional

from history import folder_lock
from kite_auth import PROJECT_ROOT
from live_money import MAX_LOSS_FRACTION, PRIORITY, allocate

LIVE_DIR = PROJECT_ROOT / ".cache" / "live"
STOP_FILE = PROJECT_ROOT / "STOP"
ALLOCATE_AT = time(9, 20)  # owner, 2026-10-05: the money in the account before 09:30 is the day's money
ALLOCATE_LATEST = time(9, 28)  # from 09:20 the split waits for all 4 bots to register, but not past this


class SharedAccount:
    def __init__(self, day: date, folder: Path = LIVE_DIR, stop_file: Path = STOP_FILE):
        self.day = day
        self.folder = folder
        self.stop_file = stop_file
        self.path = folder / f"account_{day.isoformat()}.json"
        folder.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"date": self.day.isoformat(), "registered": {}, "capital": None, "allocation": None,
                "max_loss": None, "pnl": {}, "halted": None}

    def _save(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def _update(self, change: Callable[[dict], object]):
        with folder_lock(self.folder):
            data = self._load()
            result = change(data)
            self._save(data)
            return result

    def read(self) -> dict:
        with folder_lock(self.folder):
            return self._load()

    def register(self, bot: str, one_lot_cost: float) -> None:
        def change(data):
            data["registered"][bot] = round(one_lot_cost, 2)
        self._update(change)

    def allocate_if_due(self, now: datetime, read_capital: Callable[[], float]) -> Optional[dict]:
        """Splits the money once: from 09:20 when all 4 bots have registered, at 09:28 with whoever has.
        Returns the account once it has been split, else None."""
        if now.time() < ALLOCATE_AT:
            return None
        current = self.read()
        if current["allocation"] is not None:
            return current
        if len(current["registered"]) < len(PRIORITY) and now.time() < ALLOCATE_LATEST:
            return None
        capital = read_capital()  # outside the lock: a slow broker call must not block the other bots

        def change(data):
            if data["allocation"] is None:
                data["capital"] = round(capital, 2)
                data["allocation"] = {b: round(v, 2) for b, v in allocate(capital, data["registered"]).items()}
                data["max_loss"] = round(capital * MAX_LOSS_FRACTION, 2)
                data["allocated_at"] = now.strftime("%H:%M:%S")
            return data
        return self._update(change)

    def share(self, bot: str) -> Optional[float]:
        """This bot's money today; None before the split or when it got nothing."""
        allocation = self.read()["allocation"]
        return None if allocation is None else allocation.get(bot)

    def report(self, bot: str, booked: float, open_pnl: float, now: datetime) -> Optional[str]:
        """Records this bot's P&L; returns why the day is halted (now or earlier), else None."""
        def change(data):
            data["pnl"][bot] = {"booked": round(booked, 2), "open": round(open_pnl, 2), "at": now.strftime("%H:%M:%S")}
            total = sum(p["booked"] + p["open"] for p in data["pnl"].values())
            if data["halted"] is None and data["max_loss"] and total <= -data["max_loss"]:
                data["halted"] = (f"daily max loss: all bots together Rs {total:,.0f} - limit Rs -{data['max_loss']:,.0f} "
                                  f"(50% of Rs {data['capital']:,.0f})")
            return data["halted"]
        return self._update(change) or self._stop_requested()

    def halted(self) -> Optional[str]:
        return self.read()["halted"] or self._stop_requested()

    def halt(self, reason: str) -> None:
        def change(data):
            data["halted"] = data["halted"] or reason
        self._update(change)

    def _stop_requested(self) -> Optional[str]:
        return "STOP file found - stopped by the owner" if self.stop_file.exists() else None
