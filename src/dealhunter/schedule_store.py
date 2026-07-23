"""
User-programmable poll frequency + pause switch (config/schedule.yaml).
Decouples "how often does GitHub Actions check in" (fixed at ~5 min, see
.github/workflows/hunt.yml) from "how often do we actually do work" and
"should we do any work at all right now" - both changeable from the
dashboard without touching workflow YAML. Same load/save-yaml shape as
watchlist_store.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_POLL_INTERVAL_MINUTES = 5
DEFAULT_PAUSED = False
_MIN_POLL_INTERVAL_MINUTES = 1

_HEADER_COMMENT = """\
# How often Deal Hunter actually does work when triggered, and whether it
# should run at all right now.
#
# The GitHub Actions workflow (.github/workflows/hunt.yml) checks in every
# 5 minutes - the practical floor GitHub's scheduler supports - but each
# check-in only does real work (polling, Claude calls) if `paused` is false
# AND at least poll_interval_minutes have passed since the last completed
# run. Set paused: true to stop all polling entirely (e.g. while waiting on
# Reddit/eBay API access) without touching the workflow or your watchlist.
#
# Edit here by hand, or use the dashboard's controls (write here directly).
# Either way, local runs see the change immediately - the scheduled GitHub
# Actions run needs `git push` before it does too.
"""


def _load_raw(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _save_raw(path: Path, data: dict[str, Any]) -> None:
    body = yaml.safe_dump(data, sort_keys=False)
    path.write_text(_HEADER_COMMENT + body, encoding="utf-8")


def load_poll_interval_minutes(path: Path) -> int:
    minutes = _load_raw(path).get("poll_interval_minutes", DEFAULT_POLL_INTERVAL_MINUTES)
    return max(_MIN_POLL_INTERVAL_MINUTES, int(minutes))


def save_poll_interval_minutes(path: Path, minutes: int) -> int:
    minutes = max(_MIN_POLL_INTERVAL_MINUTES, int(minutes))
    data = _load_raw(path)
    data["poll_interval_minutes"] = minutes
    _save_raw(path, data)
    return minutes


def load_paused(path: Path) -> bool:
    return bool(_load_raw(path).get("paused", DEFAULT_PAUSED))


def save_paused(path: Path, paused: bool) -> bool:
    paused = bool(paused)
    data = _load_raw(path)
    data["paused"] = paused
    _save_raw(path, data)
    return paused
