"""In-memory progress tracking for a running hunt, so the dashboard's
"Refresh now" button can show real progress instead of an indefinite
spinner. Local-only, single-process, not persisted - the GitHub Actions
cron path (scripts/run_hunt.py) calls the same pipeline functions that
update this, but nothing there ever reads it back, so it's a harmless
no-op outside the dashboard."""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_state: dict = {"running": False}


def start() -> None:
    with _lock:
        _state.clear()
        _state.update(
            running=True,
            phase="starting",
            detail="",
            current=0,
            total=1,
            error=None,
            started_at=time.time(),
        )


def update(phase: str, detail: str = "", current: int = 0, total: int = 1) -> None:
    """No-ops if nothing called start() first - keeps this safe to call
    unconditionally from pipeline code regardless of caller (dashboard vs.
    the GitHub Actions/CLI path, which never starts a progress session)."""
    with _lock:
        if not _state.get("running"):
            return
        _state.update(phase=phase, detail=detail, current=current, total=max(total, 1))


def finish(error: str | None = None) -> None:
    with _lock:
        if not _state:
            return
        _state.update(running=False, phase="done", error=error)


def snapshot() -> dict:
    with _lock:
        return dict(_state)
