"""
Position sizing (owner, 2026-10-12): use the whole Rs 5 lakh, but keep each bot's losses under control.

Each bot has an allotment (money it may put into one trade) and a daily loss limit. A trade's quantity is the
most whole lots that
  * the allotment can buy at the entry price, and
  * keep (entry - SL) x qty within what is left of today's loss limit.
No lot fits -> no trade. Once a bot's losses for the day reach its limit it takes no more trades.

    Sniper NIFTY  Rs 1,00,000 / loss Rs 7,500     HLC NIFTY  Rs 1,00,000 / loss Rs 7,500
    Sniper SENSEX Rs 1,25,000 / loss Rs 10,000    HLC SENSEX Rs 1,75,000 / loss Rs 10,000
"""

from __future__ import annotations

import json
import math
from contextlib import contextmanager
from pathlib import Path


def size_qty(allocation: float, risk_left: float, lot: int, entry: float, stop: float) -> int:
    """Quantity in whole lots (0 = skip the trade)."""
    if allocation <= 0 or risk_left <= 0 or lot <= 0 or entry <= 0:
        return 0
    lots_by_money = math.floor(allocation / (entry * lot))
    per_unit_risk = max(entry - stop, 0.05)
    lots_by_risk = math.floor(risk_left / (per_unit_risk * lot))
    return max(min(lots_by_money, lots_by_risk), 0) * lot


def risk_left(max_loss: float, realized_rupees: float) -> float:
    """What is left of today's loss limit: profits don't raise it, losses use it up."""
    return max_loss + min(0.0, realized_rupees)


# --- Shared Rs 5 lakh pool, SENSEX first (owner, 2026-10-12) ---------------------------------------------------
#
# The four bots run as separate processes, so the money in use is kept in a small ledger file per day. A SENSEX
# bot may use up to its allotment out of whatever is free. A NIFTY bot gets what is free AFTER keeping the full
# allotment back for each SENSEX bot that isn't in a trade - so SENSEX always has its money, and NIFTY can use
# more than Rs 1 lakh whenever SENSEX doesn't need it.

POOL = 500_000
SENSEX_BOTS = {"sniper_SENSEX": 125_000, "hlc_SENSEX": 175_000}


class CapitalLedger:
    def __init__(self, path: Path, bot: str):
        self.path, self.bot = Path(path), bot

    @contextmanager
    def _locked(self):
        from history import folder_lock  # same lock helper the history files use

        with folder_lock(self.path.parent):
            yield

    def _read(self) -> dict:
        try:
            return {k: float(v) for k, v in json.loads(self.path.read_text()).items()}
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1))

    def available(self, allotment: float) -> float:
        """Money this bot may put into its next trade."""
        with self._locked():
            data = self._read()
        data.pop(self.bot, None)  # a bot opening a trade holds nothing
        free = POOL - sum(data.values())
        if self.bot in SENSEX_BOTS:
            return max(0.0, min(allotment, free))
        reserve = sum(a for b, a in SENSEX_BOTS.items() if data.get(b, 0) <= 0)
        return max(0.0, free - reserve)

    def hold(self, amount: float) -> None:
        with self._locked():
            data = self._read()
            data[self.bot] = round(amount, 2)
            self._write(data)

    def release(self) -> None:
        self.hold(0.0)
