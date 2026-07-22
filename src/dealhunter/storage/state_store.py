"""
Dedupe / sold-tracking state, one JSON file per source under data/state/.
This is intentionally separate from findings storage: state is bookkeeping
(what have we already seen, is it sold yet) while findings are the curated,
user-facing output.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# Hard cap on how long a dedupe entry is kept, independent of any single
# watch item's lookback_days, so the state file doesn't grow unbounded even
# if a watch item is left with a very long lookback.
_MAX_RETENTION_DAYS = 120


def _path_for(state_dir: Path, source: str) -> Path:
    return state_dir / f"{source}_seen.json"


def load_state(state_dir: Path, source: str) -> dict[str, Any]:
    path = _path_for(state_dir, source)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state_dir: Path, source: str, state: dict[str, Any]) -> None:
    path = _path_for(state_dir, source)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def is_new(state: dict[str, Any], listing_id: str) -> bool:
    return listing_id not in state


def mark_seen(state: dict[str, Any], listing_id: str, watch_item_id: str) -> None:
    entry = state.setdefault(
        listing_id,
        {"first_seen": time.time(), "watch_item_ids": [], "status": "active"},
    )
    if watch_item_id not in entry["watch_item_ids"]:
        entry["watch_item_ids"].append(watch_item_id)


def mark_sold(state: dict[str, Any], listing_id: str) -> None:
    if listing_id in state:
        state[listing_id]["status"] = "sold"


def prune_old(state: dict[str, Any], max_age_days: int = _MAX_RETENTION_DAYS) -> dict[str, Any]:
    cutoff = time.time() - max_age_days * 86400
    return {k: v for k, v in state.items() if v.get("first_seen", 0) >= cutoff}
