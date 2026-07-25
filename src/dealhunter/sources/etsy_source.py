"""
Etsy source - PHASE 2, not implemented in v1 (per project scope: "Etsy if
time allows, otherwise phase 2"). This stub exists so the pluggable-source
interface and the pipeline's "enabled sources" wiring already account for a
third source; wiring up the real Etsy Open API v3 later is additive (fill
in this file, register it in pipeline.py's SOURCE_REGISTRY) and doesn't
require touching reddit_source.py, ebay_source.py, or scoring.py.
"""
from __future__ import annotations

from config.settings import Settings
from dealhunter.models import Listing, ListingRefresh, WatchItem
from dealhunter.sources.base import SourceAdapter


class EtsySource(SourceAdapter):
    name = "etsy"

    def __init__(self, settings: Settings):
        self._settings = settings

    def verify_credentials(self) -> None:
        raise NotImplementedError(
            "Etsy source is not implemented yet (phase 2) - do not enable "
            "'etsy' in a watch item's category config until this is built."
        )

    def fetch_new(
        self, watch_item: WatchItem, category_def: dict, seen_ids: set[str]
    ) -> list[Listing]:
        raise NotImplementedError("Etsy source is not implemented yet (phase 2).")

    def refresh_listing(self, listing: Listing) -> ListingRefresh:
        raise NotImplementedError("Etsy source is not implemented yet (phase 2).")
