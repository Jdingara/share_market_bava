"""
Real-money layer, tested offline against a fake Zerodha (no network, no money):
money split and lots (live_money), the shared day account (live_account) and
the executor that turns engine decisions into orders (live_executor).
"""

import sys
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import live_executor
from broker import OrderState, tick
from live_account import SharedAccount
from live_executor import LiveExecutor, Trigger, Want
from live_money import allocate, lot_cost, lots_for

DAY = date(2026, 10, 26)
COSTS = {"SNIPER_SENSEX": 6000, "SNIPER_NIFTY": 8000, "HLC_SENSEX": 8000, "HLC_NIFTY": 10000}


# --- money split (owner, 2026-10-05) -----------------------------------------------


def test_one_lakh_is_split_four_ways():
    assert allocate(100_000, COSTS) == {b: 25_000 for b in COSTS}


def test_thirty_thousand_goes_three_ways_in_priority_order():
    # 4 parts of 7,500: only Sniper SENSEX affords a lot -> 3 parts of 10,000
    assert allocate(30_000, COSTS) == {"SNIPER_SENSEX": 10_000, "SNIPER_NIFTY": 10_000, "HLC_SENSEX": 10_000}


def test_fourteen_thousand_goes_to_the_first_bot_that_affords_it():
    assert allocate(14_000, COSTS) == {"SNIPER_SENSEX": 14_000}


def test_priority_skips_a_bot_too_expensive_for_its_part():
    costs = dict(COSTS, SNIPER_SENSEX=12_000)  # expensive SENSEX premium today
    assert allocate(20_000, costs) == {"SNIPER_NIFTY": 10_000, "HLC_SENSEX": 10_000}


def test_not_enough_for_any_lot():
    assert allocate(5_000, COSTS) == {}


def test_only_running_bots_share_the_money():
    assert allocate(40_000, {"SNIPER_NIFTY": 8000, "HLC_NIFTY": 10000}) == {"SNIPER_NIFTY": 20_000, "HLC_NIFTY": 20_000}


def test_lots_grow_with_money_up_to_the_maximum():
    assert lots_for(25_000, 300, 20, 15) == 4  # 1 SENSEX lot at 300 = 6,120 with the buffer
    assert lots_for(6_000, 300, 20, 15) == 0
    assert lots_for(10_000_000, 300, 20, 15) == 15
    assert lots_for(100_000, 150, 65, 5) == 5
    assert lot_cost(100, 65) == pytest.approx(6630)


# --- shared account ---------------------------------------------------------------


@pytest.fixture
def account(tmp_path):
    return SharedAccount(DAY, tmp_path / "live", tmp_path / "STOP")


def _at(hh, mm, ss=0):
    return datetime.combine(DAY, time(hh, mm, ss))


def test_split_waits_for_all_four_bots_until_0928(account):
    for bot in ("SNIPER_SENSEX", "SNIPER_NIFTY", "HLC_SENSEX"):
        account.register(bot, COSTS[bot])
    assert account.allocate_if_due(_at(9, 19), lambda: 100_000) is None
    assert account.allocate_if_due(_at(9, 20), lambda: 100_000) is None  # HLC NIFTY not registered yet
    split = account.allocate_if_due(_at(9, 28), lambda: 90_000)
    assert split["allocation"] == {"SNIPER_SENSEX": 30_000, "SNIPER_NIFTY": 30_000, "HLC_SENSEX": 30_000}
    assert split["max_loss"] == 45_000
    assert account.allocate_if_due(_at(9, 40), lambda: 1) == split  # only once a day
    assert account.share("HLC_NIFTY") is None


def test_split_at_0920_when_everyone_registered(account):
    for bot, cost in COSTS.items():
        account.register(bot, cost)
    assert account.allocate_if_due(_at(9, 20), lambda: 100_000)["allocation"]["HLC_NIFTY"] == 25_000


def test_day_halts_at_half_the_money_for_all_bots_together(account):
    for bot, cost in COSTS.items():
        account.register(bot, cost)
    account.allocate_if_due(_at(9, 20), lambda: 100_000)
    assert account.report("SNIPER_SENSEX", -30_000, 0, _at(11, 0)) is None
    assert account.report("SNIPER_NIFTY", -10_000, -9_000, _at(11, 1)) is None  # -49,000
    reason = account.report("HLC_SENSEX", 0, -1_500, _at(11, 2))  # -50,500
    assert reason and "max loss" in reason
    assert account.halted() == reason


def test_stop_file_halts_the_day(account, tmp_path):
    assert account.halted() is None
    (tmp_path / "STOP").write_text("")
    assert "STOP" in account.halted()


# --- executor with a fake Zerodha -----------------------------------------------------


class FakeBroker:
    """Limit orders fill at the last price when it is on the right side of the limit; SL sells fill at the
    trigger once the last price reaches it."""

    def __init__(self, prices, funds=1_000_000):
        self.prices = prices
        self.available = funds
        self.orders = {}
        self.log = []

    def ltp(self, symbols):
        return {s: self.prices[s] for s in symbols if s in self.prices}

    def funds(self):
        return self.available

    def _new(self, **order):
        order_id = str(len(self.orders) + 1)
        self.orders[order_id] = dict(order, status="TRIGGER PENDING" if order["type"] == "SL" else "OPEN", filled=0, avg=0.0)
        self.log.append((order["side"], order["type"], order["symbol"], order["qty"], order.get("trigger"), order["price"]))
        self._evaluate(order_id)
        return order_id

    def buy(self, symbol, qty, price):
        return self._new(side="BUY", type="LIMIT", symbol=symbol, qty=qty, price=price)

    def sell(self, symbol, qty, price):
        return self._new(side="SELL", type="LIMIT", symbol=symbol, qty=qty, price=price)

    def stop_sell(self, symbol, qty, trigger, price):
        return self._new(side="SELL", type="SL", symbol=symbol, qty=qty, price=price, trigger=trigger)

    def modify(self, order_id, price, trigger=None):
        order = self.orders[order_id]
        order["price"] = price
        if trigger is not None:
            order["trigger"] = trigger
        self.log.append(("MODIFY", order_id, price, trigger))
        self._evaluate(order_id)

    def cancel(self, order_id):
        order = self.orders[order_id]
        if order["status"] not in ("COMPLETE", "CANCELLED"):
            order["status"] = "CANCELLED"
        self.log.append(("CANCEL", order_id))

    def _evaluate(self, order_id):
        order = self.orders[order_id]
        last = self.prices[order["symbol"]]
        if order["status"] in ("COMPLETE", "CANCELLED", "REJECTED"):
            return
        if order["type"] == "SL":
            if last <= order["trigger"]:
                order.update(status="COMPLETE", filled=order["qty"], avg=order["trigger"])
        elif (order["side"] == "BUY" and order["price"] >= last) or (order["side"] == "SELL" and order["price"] <= last):
            order.update(status="COMPLETE", filled=order["qty"], avg=last)

    def state(self, order_id):
        self._evaluate(order_id)
        o = self.orders[order_id]
        return OrderState(o["status"], o["filled"], o["avg"])


class Clock:
    def __init__(self, when):
        self.when = when

    def __call__(self):
        return self.when


@pytest.fixture
def setup(tmp_path, account):
    for bot, cost in COSTS.items():
        account.register(bot, cost)
    prices = {"SENSEX26O2972000PE": 110.0, "SENSEX26O2972200CE": 90.0}
    broker = FakeBroker(prices)
    clock = Clock(_at(9, 20))
    messages = []

    def make(bot="SNIPER_SENSEX", lot=20, max_lots=15):
        return LiveExecutor(bot, lot, max_lots, broker, account, messages.append, tmp_path / "live",
                            tmp_path / "history" / "trades.csv", now=clock, sleep=lambda s: None)

    return make, broker, clock, messages, prices


PE = "SENSEX26O2972000PE"


def _allocated(executor, clock, capital=100_000):
    executor.broker.available = capital
    executor.tick()  # 09:20: money split
    assert executor.account.share(executor.bot) == capital / 4


def test_trigger_buy_then_target(setup):
    make, broker, clock, messages, prices = setup
    ex = make()
    _allocated(ex, clock)
    broker.available = 1_000_000
    clock.when = _at(9, 31)
    ex.sync(None, [Trigger(PE, "limit", 100, 81, 144), Trigger(PE, "stop", 121, 100, 169)], _at(9, 25))
    ex.tick()  # 110: neither level
    assert ex.position is None
    prices[PE] = 121.5
    clock.when = _at(9, 33, 10)
    ex.tick()  # runs up to 121 -> buy
    pos = ex.position
    qty = pos.qty
    assert pos.symbol == PE and pos.stop == 100 and pos.target == 169
    assert qty == 200 == 20 * lots_for(25_000, 121.5, 20, 15)  # 25,000 / (121.5 x 1.02 x 20) = 10 lots
    assert ("SELL", "SL", PE, qty, 100, tick(100 - 3.0)) in broker.log  # stop-loss rests at Zerodha
    prices[PE] = 170
    ex.tick()
    assert ex.position is None
    assert ex.booked == pytest.approx((170 - 121.5) * qty)
    assert any("SOLD" in m and "TARGET 169" in m for m in messages)
    assert (Path(ex.trade_log)).read_text().count("SNIPER_SENSEX") == 1


def test_stop_loss_order_fills_at_zerodha(setup):
    make, broker, clock, messages, prices = setup
    ex = make()
    _allocated(ex, clock)
    clock.when = _at(9, 31)
    ex.sync(Want(PE, _at(9, 30), 100, 144), [], _at(9, 30))  # engine bought on the 09:30 candle
    assert ex.position and ex.position.sl_order
    prices[PE] = 99
    ex.tick()
    assert ex.position is None
    assert ex.booked == pytest.approx((100 - 110) * 20 * lots_for(25_000, 110, 20, 15))
    assert any("STOPLOSS 100" in m for m in messages)


def test_engine_exit_sells_and_cancels_the_stop(setup):
    make, broker, clock, messages, prices = setup
    ex = make()
    _allocated(ex, clock)
    clock.when = _at(10, 1)
    ex.sync(Want(PE, _at(9, 55), 100, None), [], _at(9, 55))
    sl = ex.position.sl_order
    clock.when = _at(10, 5, 20)
    ex.sync(Want(PE, _at(9, 55), 100, None), [], _at(10, 0))
    assert ex.position is not None  # still held
    ex.sync(None, [], _at(10, 0))  # engine exited at the 10:00 candle close
    assert ex.position is None
    assert broker.orders[sl]["status"] == "CANCELLED"


def test_a_buy_the_engine_has_not_seen_yet_is_kept(setup):
    make, broker, clock, messages, prices = setup
    ex = make()
    _allocated(ex, clock)
    prices[PE] = 99
    clock.when = _at(10, 5, 5)
    ex.sync(None, [Trigger(PE, "limit", 100, 81, 144)], _at(9, 55))
    ex.tick()  # bought in the 10:05 candle
    assert ex.position is not None
    ex.sync(None, [Trigger(PE, "limit", 100, 81, 144)], _at(10, 0))  # 10:00 candle: engine still waiting
    assert ex.position is not None
    assert ex.triggers == []  # and no second buy
    ex.sync(Want(PE, _at(10, 5), 81, 144), [], _at(10, 5))  # engine catches up
    assert ex.position is not None and ex.fired is None


def test_catch_up_trades_are_never_bought(setup):
    make, broker, clock, messages, prices = setup
    ex = make()
    _allocated(ex, clock)
    clock.when = _at(10, 40)
    ex.sync(Want(PE, _at(9, 30), 100, 144, late=True), [], _at(10, 35))
    assert ex.position is None and not any(o[0] == "BUY" for o in broker.log)
    assert any("not bought" in m for m in messages)


def test_each_engine_trade_is_bought_once(setup):
    make, broker, clock, messages, prices = setup
    ex = make()
    _allocated(ex, clock)
    clock.when = _at(9, 31)
    want = Want(PE, _at(9, 30), 100, 144)
    ex.sync(want, [], _at(9, 30))
    prices[PE] = 99
    ex.tick()  # stopped out at Zerodha
    assert ex.position is None
    prices[PE] = 115
    ex.sync(want, [], _at(9, 35))  # engine (candle data) still thinks it is in - don't buy again
    assert ex.position is None
    assert sum(1 for o in broker.log if o[0] == "BUY") == 1


def test_no_money_no_trade(setup):
    make, broker, clock, messages, prices = setup
    ex = make()
    ex.broker.available = 5_000
    ex.tick()
    assert ex.account.share(ex.bot) is None
    clock.when = _at(9, 31)
    ex.sync(Want(PE, _at(9, 30), 100, 144), [], _at(9, 30))
    assert ex.position is None
    assert any("not enough money" in m for m in messages)


def test_zerodha_funds_cap_the_lots(setup):
    make, broker, clock, messages, prices = setup
    ex = make()
    _allocated(ex, clock)
    broker.available = 2_000  # money already used elsewhere - 1 lot at 110 needs 2,244
    clock.when = _at(9, 31)
    ex.sync(Want(PE, _at(9, 30), 100, 144), [], _at(9, 30))
    assert ex.position is None
    broker.available = 2 * lot_cost(110, 20) + 10
    ex.sync(Want(PE, _at(9, 40), 100, 144), [], _at(9, 40))
    assert ex.position.qty == 40


def test_trailing_stop_moves_the_order_up_only(setup):
    make, broker, clock, messages, prices = setup
    ex = make()
    _allocated(ex, clock)
    clock.when = _at(9, 31)
    ex.sync(Want(PE, _at(9, 30), 81, 144), [], _at(9, 30))
    sl = ex.position.sl_order
    prices[PE] = 130
    ex.sync(Want(PE, _at(9, 30), 100, 144), [], _at(9, 35))
    assert broker.orders[sl]["trigger"] == 100
    ex.sync(Want(PE, _at(9, 30), 81, 144), [], _at(9, 40))  # never down
    assert broker.orders[sl]["trigger"] == 100


def test_stop_that_filled_while_being_moved_is_booked(setup):
    make, broker, clock, messages, prices = setup
    ex = make()
    _allocated(ex, clock)
    clock.when = _at(9, 31)
    ex.sync(Want(PE, _at(9, 30), 100, 144), [], _at(9, 30))
    qty, sl = ex.position.qty, ex.position.sl_order
    broker.orders[sl].update(status="COMPLETE", filled=qty, avg=100.0)  # filled at Zerodha a moment ago

    def refuse(order_id, price, trigger=None):
        raise RuntimeError("Order cannot be modified as it is being processed")
    broker.modify = refuse
    prices[PE] = 125  # bounced back before the bot's next look
    ex.sync(Want(PE, _at(9, 30), 110, 144), [], _at(9, 35))  # engine trails the stop up
    assert ex.position is None
    assert ex.booked == pytest.approx((100 - 110) * qty)


def test_restart_keeps_the_position_and_does_not_buy_again(setup):
    make, broker, clock, messages, prices = setup
    ex = make()
    _allocated(ex, clock)
    clock.when = _at(9, 31)
    want = Want(PE, _at(9, 30), 100, 144)
    ex.sync(want, [], _at(9, 30))
    restarted = make()
    assert restarted.position is not None and restarted.position.sl_order == ex.position.sl_order
    restarted.sync(Want(PE, _at(9, 30), 100, 144, late=True), [], _at(9, 50))
    assert restarted.position is not None
    assert sum(1 for o in broker.log if o[0] == "BUY") == 1


def test_daily_max_loss_sells_everything_in_every_bot(setup):
    make, broker, clock, messages, prices = setup
    sniper = make()
    hlc = make("HLC_SENSEX")
    _allocated(sniper, clock)
    clock.when = _at(9, 31)
    sniper.sync(Want(PE, _at(9, 30), None, None), [], _at(9, 30))  # HLC-style: no premium stop
    hlc.tick()
    hlc.sync(Want("SENSEX26O2972200CE", _at(9, 30), None, None), [], _at(9, 30))
    qty = sniper.position.qty
    prices[PE] = 110 - 50_000 / qty - 1  # sniper alone loses more than 50% of 100,000
    sniper.tick()
    assert sniper.position is None and sniper.halted
    hlc.tick()
    assert hlc.position is None and hlc.halted
    hlc.sync(Want("SENSEX26O2972200CE", _at(9, 50), None, None), [], _at(9, 50))
    assert hlc.position is None  # no more buying today


def test_everything_sold_at_1501(setup):
    make, broker, clock, messages, prices = setup
    ex = make()
    _allocated(ex, clock)
    clock.when = _at(14, 50)
    ex.sync(Want(PE, _at(14, 45), None, None), [], _at(14, 45))
    clock.when = _at(15, 1)
    ex.tick()
    assert ex.position is None


def test_hlc_wants_premium_stop_index_stop_and_low_premium_order():
    import hlc_live

    chain = SimpleNamespace(by_key={(22450.0, s): {"tradingsymbol": f"NIFTY26O2722450{s}"} for s in ("CE", "PE")})
    trade = SimpleNamespace(strike=22450, side="PE", entry_time="2026-10-26T10:20:00", sl_premium=150.0, index_sl=None)
    engine = SimpleNamespace(open_trade=trade, pending=None)
    want, triggers = hlc_live.hlc_wants(engine, chain, _at(9, 0))
    assert (want.symbol, want.stop, want.target, want.late, triggers) == ("NIFTY26O2722450PE", 150.0, None, False, [])

    fib = SimpleNamespace(strike=22450, side="CE", entry_time="2026-10-26T09:30:00", sl_premium=0.0, index_sl=22400.0)
    want, _ = hlc_live.hlc_wants(SimpleNamespace(open_trade=fib, pending=None), chain, _at(10, 0))
    assert want.stop is None  # index stop: the engine exits at a candle close
    assert want.late  # entered before this restart - never bought

    order = dict(strike=22450.0, side="CE", stop=12.5, sl=9.8)
    want, triggers = hlc_live.hlc_wants(SimpleNamespace(open_trade=None, pending=order), chain, _at(9, 0))
    assert want is None and triggers == [Trigger("NIFTY26O2722450CE", "stop", 12.5, 9.8, None)]


def test_real_mode_needs_the_env_switch(monkeypatch):
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    with pytest.raises(SystemExit):
        live_executor.confirm_real_mode()
    monkeypatch.setenv("LIVE_TRADING", "yes")
    live_executor.confirm_real_mode()
