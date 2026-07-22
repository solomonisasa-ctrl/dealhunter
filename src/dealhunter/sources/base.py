"""
Common interface every marketplace source implements. The pipeline only
talks to sources through this interface, so adding a new marketplace (or
swapping eBay's liquidity proxy for real sold-comp data later) never touches
pipeline.py or scoring.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from dealhunter.models import Listing, WatchItem


class SourceAdapter(ABC):
    name: str

    @abstractmethod
    def verify_credentials(self) -> None:
        """Raise an exception if credentials are missing/invalid. Used by
        healthcheck.py before a run starts."""

    @abstractmethod
    def fetch_new(
        self, watch_item: WatchItem, category_def: dict, seen_ids: set[str]
    ) -> list[Listing]:
        """Fetch recent listings for this watch item, skipping ids already
        in seen_ids. Should not raise on a single bad listing - skip it and
        keep going; only raise for a source-wide failure (auth, network)."""

    @abstractmethod
    def check_sold(self, listing: Listing) -> bool:
        """Best-effort check of whether a previously-seen listing is now
        sold/removed (flair/comment scan on Reddit, status field on eBay)."""

    def comparable_count(self, watch_item: WatchItem, category_def: dict) -> int:
        """Algorithmic liquidity signal: how many comparable items has this
        source seen recently. Default 0 for sources that don't implement one
        (e.g. Etsy stub) - overridden by reddit_source/ebay_source."""
        return 0
