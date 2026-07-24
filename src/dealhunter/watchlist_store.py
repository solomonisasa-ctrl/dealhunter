"""Load/save the plain-English watchlist (config/watchlist.yaml)."""
from __future__ import annotations

from pathlib import Path

import yaml

from dealhunter.models import WatchItem

_HEADER_COMMENT = """\
# Your hunts, in plain English. Edit by hand or via the dashboard's
# "Watchlist" tab (which writes back to this file).
#
# Fields:
#   id                  - stable short id, used in state/findings files. Don't
#                          reuse an id for a different hunt.
#   category             - must match a key in config/categories.yaml
#   description           - plain English. This is what gets sent to Claude to
#                            extract structured search criteria - no fixed
#                            keyword lists.
#   discount_threshold     - minimum (estimated_value - price) / estimated_value
#                            required to trigger a notification. Optional -
#                            leave blank/null to notify on any match
#                            regardless of price vs. market value.
#   lookback_days            - how far back to look for liquidity comps and how
#                              long dedupe/sold-state is retained. Default 30.
#   enabled                    - set to false to pause a hunt without deleting it.
#   parsed_criteria             - filled in automatically by criteria_parser.py
#                                  the first time this hunt runs; safe to leave
#                                  blank when you add a new item by hand.

"""


def load_watchlist(path: Path) -> list[WatchItem]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [WatchItem.model_validate(item) for item in raw]


def save_watchlist(path: Path, items: list[WatchItem]) -> None:
    raw = [item.model_dump(mode="json") for item in items]
    body = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
    path.write_text(_HEADER_COMMENT + body, encoding="utf-8")


def upsert_watch_item(path: Path, item: WatchItem) -> list[WatchItem]:
    items = load_watchlist(path)
    for i, existing in enumerate(items):
        if existing.id == item.id:
            items[i] = item
            break
    else:
        items.append(item)
    save_watchlist(path, items)
    return items


def delete_watch_item(path: Path, item_id: str) -> list[WatchItem]:
    items = [i for i in load_watchlist(path) if i.id != item_id]
    save_watchlist(path, items)
    return items
