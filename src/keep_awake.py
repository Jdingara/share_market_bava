"""
Keeps Windows from sleeping while a bot runs (owner, 2026-10-08: the laptop used
on 07-10 went to sleep during the day and the results were wrong).

Uses SetThreadExecutionState, so it only lasts while the calling process is alive;
the PC's own power settings are not changed. The screen may still turn off.
No-op on other systems.
"""

from __future__ import annotations

import sys

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def keep_awake() -> bool:
    """Ask Windows not to sleep until this process exits. True if the request was accepted."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED))
    except Exception:  # never stop a bot over this
        return False
