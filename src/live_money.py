"""
Real-money sizing rules (owner, 2026-10-05). Pure functions - no broker, no files.

Money: whatever is available in the Zerodha account in the morning (read at
09:20) is shared between the bots, in the owner's priority order:

    1. Sniper SENSEX   2. Sniper NIFTY   3. HLC SENSEX   4. HLC NIFTY

Split: try 4 equal parts, then 3, then 2, then 1 - the first split where every
chosen bot (picked in priority order, skipping bots too expensive for a part)
can buy at least 1 lot. More money -> more lots, up to each market's maximum
(NIFTY 5 lots = 325, SENSEX 15 lots = 300). Not even 1 lot -> no trade.

Daily max loss: 50% of the morning money, for all bots together.
"""

from __future__ import annotations

import math

PRIORITY = ("SNIPER_SENSEX", "SNIPER_NIFTY", "HLC_SENSEX", "HLC_NIFTY")
MAX_LOSS_FRACTION = 0.5
PRICE_BUFFER = 0.02  # sizing leaves room to buy a little above the reference price


def lot_cost(price: float, lot_size: int) -> float:
    """Money needed for one lot at `price`, with the buying buffer."""
    return price * (1 + PRICE_BUFFER) * lot_size


def allocate(capital: float, lot_costs: dict[str, float]) -> dict[str, float]:
    """{bot: money} for the bots that trade today. `lot_costs`: each running bot's estimated cost of one lot."""
    bots = [b for b in PRIORITY if b in lot_costs]
    for parts in range(len(bots), 0, -1):
        share = capital / parts
        chosen = [b for b in bots if lot_costs[b] <= share][:parts]
        if len(chosen) == parts:
            return {b: share for b in chosen}
    return {}


def lots_for(money: float, price: float, lot_size: int, max_lots: int) -> int:
    """How many lots `money` buys at `price` (0 if not even one), capped at the market's maximum."""
    if money <= 0 or price <= 0:
        return 0
    return max(0, min(max_lots, math.floor(money / lot_cost(price, lot_size))))
