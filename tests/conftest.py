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


def pytest_configure(config):
    config.addinivalue_line("markers", "ride: owner's 09-10 normal-day mode (no target exit, trailing only)")
