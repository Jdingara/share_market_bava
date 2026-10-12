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

import math


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
