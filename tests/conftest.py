"""Shared test setup."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture(autouse=True)
def sniper_target_mode(monkeypatch, request):
    """Most Sniper tests check the target rules (still used on a buyer's day). The owner's 09-10 normal-day mode
    (no target exit, trailing only, 2 trades) is tested explicitly by tests marked `ride`."""
    import sniper_engine

    if "ride" not in request.keywords:
        monkeypatch.setattr(sniper_engine, "RIDE_NORMAL_DAYS", False)
    if "atm_confirm" not in request.keywords:  # the 19-10 ATM-confirm square entry has its own tests
        monkeypatch.setattr(sniper_engine, "ATM_CONFIRM_SQUARE_ENTRY", False)
    if "legacy_trailing" in request.keywords:  # the 28-09 .. 07-10 trailing rules (replaced 12-10)
        monkeypatch.setattr(sniper_engine, "FIRST_TSL_ON_TOUCH", True)
        monkeypatch.setattr(sniper_engine, "ALL_STOPS_ON_CLOSE", False)
        monkeypatch.setattr(sniper_engine, "TRAIL_BEFORE_TARGET", True)
        monkeypatch.setattr(sniper_engine, "SQUARE_LADDER_TSL", False)
    import orb_engine
    if "orb_retest" not in request.keywords:  # the 22-10 ORB 0.75 retest entry has its own test
        monkeypatch.setattr(orb_engine, "RETEST_075", False)
    # the 23-10 ORB 0.5-0.618 zone + confirmation (switched off later that day) has its own test
    monkeypatch.setattr(orb_engine, "ZONE_CONFIRM", "orb_zone" in request.keywords)
    monkeypatch.setattr(orb_engine, "ZONE_TOUCH", "orb_zone_touch" in request.keywords)  # 23-10 rule, off since 24-10
    if "orb_tsl" not in request.keywords:  # the 22-10 ORB 50/100-point target + TSL has its own test
        monkeypatch.setattr(orb_engine, "TARGET_TSL", False)


def pytest_configure(config):
    config.addinivalue_line("markers", "ride: owner's 09-10 normal-day mode (no target exit, trailing only)")
    config.addinivalue_line("markers", "orb_tsl: owner's 22-10 ORB target 50/100 points then TSL 20/50")
    config.addinivalue_line("markers", "orb_zone_touch: owner's 23-10 ORB entry on the touch of the zone's 0.5")
    config.addinivalue_line("markers", "orb_zone: owner's 23-10 ORB 0.5-0.618 zone + confirmation candle")
    config.addinivalue_line("markers", "orb_retest: owner's 22-10 ORB retest of the first candle's 0.75")
    config.addinivalue_line("markers", "atm_confirm: owner's 19-10 ATM-confirm square entry")
    config.addinivalue_line("markers", "legacy_trailing: the trailing rules before 12-10 (cost on touch, TSL by touch)")
