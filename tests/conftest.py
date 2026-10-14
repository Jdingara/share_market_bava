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
    if "legacy_trailing" in request.keywords:  # the 28-09 .. 07-10 trailing rules (replaced 12-10)
        monkeypatch.setattr(sniper_engine, "FIRST_TSL_ON_TOUCH", True)
        monkeypatch.setattr(sniper_engine, "ALL_STOPS_ON_CLOSE", False)
        monkeypatch.setattr(sniper_engine, "TRAIL_BEFORE_TARGET", True)
        monkeypatch.setattr(sniper_engine, "SQUARE_LADDER_TSL", False)


def pytest_configure(config):
    config.addinivalue_line("markers", "ride: owner's 09-10 normal-day mode (no target exit, trailing only)")
    config.addinivalue_line("markers", "legacy_trailing: the trailing rules before 12-10 (cost on touch, TSL by touch)")
