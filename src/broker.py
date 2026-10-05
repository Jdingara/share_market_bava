"""
Real Zerodha orders (Kite Connect). The only module that places, changes or
cancels orders - the strategy engines never import it.

All orders are intraday (MIS): if the bot dies, Zerodha squares positions off
itself near the close, so nothing is carried overnight by mistake. Buys and
sells are LIMIT orders priced a little through the market (no MARKET orders);
the stop-loss is an SL (stop-limit) sell order resting at Zerodha, so a
position stays protected even if the laptop sleeps.
"""

from __future__ import annotations

import time as time_module
from dataclasses import dataclass
from pathlib import Path

from history import folder_lock

TICK = 0.05  # NFO and BFO option tick size
LTP_MIN_GAP_SECONDS = 1.05  # Kite's quote APIs allow 1 request/second per account - shared by all 4 bots
DONE = ("COMPLETE", "REJECTED", "CANCELLED")


def tick(price: float) -> float:
    """Rounded to the exchange's 0.05 tick, never below one tick."""
    return max(TICK, round(round(price / TICK) * TICK, 2))


@dataclass(frozen=True)
class OrderState:
    status: str  # Kite: OPEN, TRIGGER PENDING, COMPLETE, REJECTED, CANCELLED, ...
    filled: int
    average: float
    message: str = ""

    @property
    def done(self) -> bool:
        return self.status in DONE


class KiteBroker:
    def __init__(self, kite, exchange: str, tag: str, throttle_dir: Path):
        self.kite = kite
        self.exchange = exchange  # NFO (NIFTY options) or BFO (SENSEX options)
        self.tag = tag[:20]  # Kite: up to 20 characters, shows on every order in the order book
        self.throttle_dir = throttle_dir
        throttle_dir.mkdir(parents=True, exist_ok=True)

    # --- market data / funds ---

    def ltp(self, symbols: list[str]) -> dict[str, float]:
        keys = [f"{self.exchange}:{s}" for s in dict.fromkeys(symbols)]
        with folder_lock(self.throttle_dir):  # one quote request per ~second across all bot processes
            stamp = self.throttle_dir / "last_ltp"
            last = float(stamp.read_text()) if stamp.exists() else 0.0
            wait = last + LTP_MIN_GAP_SECONDS - time_module.time()
            if wait > 0:
                time_module.sleep(wait)
            try:
                data = self.kite.ltp(keys)
            finally:
                stamp.write_text(str(time_module.time()))
        return {key.split(":", 1)[1]: float(value["last_price"]) for key, value in data.items()}

    def funds(self) -> float:
        """Money available for trading right now (Kite equity segment, which covers F&O)."""
        return float(self.kite.margins("equity")["net"])

    # --- orders ---

    def _place(self, side: str, symbol: str, qty: int, order_type: str, price: float, trigger: float | None = None) -> str:
        params = dict(variety="regular", exchange=self.exchange, tradingsymbol=symbol, transaction_type=side,
                      quantity=int(qty), product="MIS", order_type=order_type, price=tick(price), validity="DAY",
                      tag=self.tag)
        if trigger is not None:
            params["trigger_price"] = tick(trigger)
        return str(self.kite.place_order(**params))

    def buy(self, symbol: str, qty: int, price: float) -> str:
        return self._place("BUY", symbol, qty, "LIMIT", price)

    def sell(self, symbol: str, qty: int, price: float) -> str:
        return self._place("SELL", symbol, qty, "LIMIT", price)

    def stop_sell(self, symbol: str, qty: int, trigger: float, price: float) -> str:
        """Stop-loss: sells (limit `price`) once the price trades at/below `trigger`."""
        return self._place("SELL", symbol, qty, "SL", price, trigger)

    def modify(self, order_id: str, price: float, trigger: float | None = None) -> None:
        params = dict(variety="regular", order_id=order_id, price=tick(price))
        if trigger is not None:
            params["trigger_price"] = tick(trigger)
        self.kite.modify_order(**params)

    def cancel(self, order_id: str) -> None:
        self.kite.cancel_order(variety="regular", order_id=order_id)

    def state(self, order_id: str) -> OrderState:
        last = self.kite.order_history(order_id)[-1]
        return OrderState(str(last["status"]), int(last.get("filled_quantity") or 0),
                          float(last.get("average_price") or 0.0), str(last.get("status_message") or ""))
