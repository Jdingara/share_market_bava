"""Owner, 2026-10-12: per-trade sizing - the allotment's lots, cut to the day's loss limit."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sizing import risk_left, size_qty


def test_money_caps_the_lots():
    # Rs 1,00,000 at premium 100, lot 65 -> 15 lots; SL 10 away -> risk allows 11 lots of 650 -> 11
    assert size_qty(100_000, 7_500, 65, 100, 90) == 11 * 65
    # tiny risk -> money decides: Rs 1L / (100 x 65) = 15 lots
    assert size_qty(100_000, 7_500, 65, 100, 99.5) == 15 * 65


def test_loss_limit_caps_the_lots_12_10_hlc_sensex():
    # entry 529.30, SL 427.40 (101.9 away), lot 20, limit Rs 10,000 -> 4 lots = 80 qty (loss ~Rs 8,150)
    assert size_qty(175_000, 10_000, 20, 529.30, 427.40) == 80


def test_no_lot_fits_and_used_up_limit():
    assert size_qty(100_000, 1_000, 65, 100, 70) == 0
    assert risk_left(7_500, -8_000) < 0 and risk_left(7_500, 20_000) == 7_500


def test_shared_pool_keeps_sensex_money_back_from_nifty(tmp_path):
    """Owner, 12-10: one Rs 5 lakh pool, SENSEX first - NIFTY gets what's left after the flat SENSEX bots' allotments."""
    from sizing import CapitalLedger

    path = tmp_path / "capital.json"
    nifty, sniper_sx, hlc_sx = (CapitalLedger(path, b) for b in ("sniper_NIFTY", "sniper_SENSEX", "hlc_SENSEX"))
    assert nifty.available(100_000) == 200_000  # 5L - SENSEX reserves (1.25L + 1.75L)
    hlc_sx.hold(150_000)  # HLC SENSEX in a trade with 1.5L
    assert nifty.available(100_000) == 225_000  # its unused 25k is free now; Sniper SENSEX's 1.25L still kept back
    assert sniper_sx.available(125_000) == 125_000
    nifty.hold(225_000)
    assert sniper_sx.available(125_000) == 125_000  # SENSEX still gets its full allotment
    hlc_sx.release()
    assert CapitalLedger(path, "hlc_NIFTY").available(100_000) == 0  # everything left is SENSEX's reserve
