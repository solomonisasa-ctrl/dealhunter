"""
Common interface every marketplace source implements. The pipeline only
talks to sources through this interface, so adding a new marketplace (or
swapping eBay's liquidity proxy for real sold-comp data later) never touches
pipeline.py or scoring.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from dealhunter.models import Listing, ListingRefresh, WatchItem


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
    def refresh_listing(self, listing: Listing) -> ListingRefresh:
        """Best-effort re-check of a previously-seen listing: is it now
        sold/removed, and has its price changed since we first saw it
        (sellers commonly cut prices on active listings - without this,
        a stored finding's discount/score stays frozen at the original
        price forever). Implementations that can't cheaply re-check price
        should still detect sold and echo the listing's existing price."""

    def comparable_count(self, watch_item: WatchItem, category_def: dict) -> int:
        """Algorithmic liquidity signal: how many comparable items has this
        source seen recently. Default 0 for sources that don't implement one
        (e.g. Etsy stub) - overridden by reddit_source/ebay_source."""
        return 0

    def fetch_additional_photos(self, listing: Listing) -> list[str]:
        """All photos for this listing, fetching more if this source can
        cheaply do so and hasn't already. Default: just return what's
        already on the listing - overridden by ebay_source, where the
        search-result payload only has one photo and the rest live behind
        a separate per-item call that's only worth paying for once a
        listing is actually getting a full (not quick) analysis."""
        return listing.image_urls or ([listing.image_url] if listing.image_url else [])
