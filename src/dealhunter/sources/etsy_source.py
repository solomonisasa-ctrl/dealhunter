"""
Etsy source via the official Open API v3.

Auth: public read endpoints (search, single listing, listing images) only
need the app's API key - no OAuth user-consent flow, since none of this
touches private/shop data. As of Feb 2026 Etsy requires the x-api-key
header to be "<keystring>:<shared_secret>" (colon-separated), not just the
bare keystring older docs describe - get both from etsy.com/developers/your-apps.

IMPORTANT LIMITATION: search results don't include images or full
descriptions - those live behind per-listing endpoints, fetched lazily the
same way ebay_source.py does (see fetch_additional_photos), so most
listings (which never clear the quick-pass deal threshold) never pay for
the extra calls.
"""
from __future__ import annotations

import requests

from config.settings import Settings
from dealhunter.models import Listing, ListingRefresh, ListingStatus, WatchItem
from dealhunter.sources.base import SourceAdapter

_BASE_URL = "https://openapi.etsy.com/v3/application"
_PING_URL = f"{_BASE_URL}/openapi-ping"
_SEARCH_URL = f"{_BASE_URL}/listings/active"
_LISTING_URL = _BASE_URL + "/listings/{listing_id}"
_LISTING_IMAGES_URL = _BASE_URL + "/listings/{listing_id}/images"

# Listing states that mean "no longer buyable" - anything else (active) we
# treat as still live. sold_out is Etsy's actual "sold" state for listings
# with quantity 1; expired/inactive/draft also mean it's gone from view.
_UNAVAILABLE_STATES = {"sold_out", "expired", "inactive", "draft"}


def _money_to_float(money: dict | None) -> float | None:
    """Etsy prices are {"amount": int, "divisor": int, "currency_code": str} -
    the actual price is amount / divisor, not the raw amount."""
    if not money:
        return None
    amount = money.get("amount")
    divisor = money.get("divisor") or 1
    if amount is None:
        return None
    return amount / divisor


class EtsySource(SourceAdapter):
    name = "etsy"

    def __init__(self, settings: Settings):
        self._settings = settings

    def _headers(self) -> dict:
        return {"x-api-key": f"{self._settings.etsy_keystring}:{self._settings.etsy_shared_secret}"}

    def verify_credentials(self) -> None:
        try:
            resp = requests.get(_PING_URL, headers=self._headers(), timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Etsy credentials invalid: {exc}") from exc

    def _search(self, query: str, taxonomy_id: int | None, limit: int = 25) -> dict:
        params: dict = {"keywords": query, "limit": str(limit)}
        if taxonomy_id:
            params["taxonomy_id"] = str(taxonomy_id)
        resp = requests.get(_SEARCH_URL, headers=self._headers(), params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def fetch_new(
        self, watch_item: WatchItem, category_def: dict, seen_ids: set[str]
    ) -> list[Listing]:
        keywords = (watch_item.parsed_criteria or {}).get("search_keywords") or [
            watch_item.description
        ]
        # Single most specific keyword phrase, not all of them blended -
        # same reasoning as ebay_source.py: blending dilutes relevance
        # toward whatever word repeats across phrases (usually the brand).
        query = keywords[0] if keywords else watch_item.description
        taxonomy_id = category_def.get("etsy", {}).get("taxonomy_id")
        try:
            data = self._search(query, taxonomy_id)
        except requests.RequestException:
            return []

        listings: list[Listing] = []
        for item in data.get("results", []):
            listing_id_raw = item.get("listing_id")
            if not listing_id_raw:
                continue
            listing_id = f"etsy:{listing_id_raw}"
            if listing_id in seen_ids:
                continue
            listing = Listing(
                id=listing_id,
                source=self.name,
                category=watch_item.category,
                title=item.get("title", ""),
                url=item.get("url", ""),
                price=_money_to_float(item.get("price")),
                shipping_price=None,  # not in the search payload - shipping varies by destination
                currency=(item.get("price") or {}).get("currency_code", "USD"),
                body=item.get("description", "") or item.get("title", ""),
                posted_at=None,
                status=ListingStatus.ACTIVE,
                raw={"taxonomy_id": item.get("taxonomy_id")},
            )
            # Unlike eBay, whose search results include one free thumbnail,
            # Etsy's search payload has NO image at all - every listing
            # needs a separate call just to get a single photo. Fetched
            # eagerly here (not lazily like the eBay's *additional* photos)
            # so quick-pass analysis has a photo to look at, and the
            # dashboard doesn't show a misleading "no image" for a listing
            # that actually has plenty on the real Etsy page.
            photos = self.fetch_additional_photos(listing)
            listing.image_urls = photos
            listing.image_url = photos[0] if photos else None
            listings.append(listing)
        return listings

    def fetch_additional_photos(self, listing: Listing) -> list[str]:
        """All photos for one listing, via the per-listing images endpoint -
        the search-result payload has none at all. Best-effort: falls back
        to whatever's already on the listing on any failure."""
        if len(listing.image_urls) > 1:
            return listing.image_urls
        fallback = listing.image_urls or ([listing.image_url] if listing.image_url else [])
        listing_id = listing.id.split(":", 1)[1]
        try:
            resp = requests.get(
                _LISTING_IMAGES_URL.format(listing_id=listing_id), headers=self._headers(), timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException:
            return fallback

        images = sorted(data.get("results", []), key=lambda img: img.get("rank") or 0)
        urls = [img["url_fullxfull"] for img in images if img.get("url_fullxfull")]
        return urls or fallback

    def refresh_listing(self, listing: Listing) -> ListingRefresh:
        listing_id = listing.id.split(":", 1)[1]
        try:
            resp = requests.get(
                _LISTING_URL.format(listing_id=listing_id), headers=self._headers(), timeout=15
            )
            if resp.status_code == 404:
                return ListingRefresh(sold=True)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException:
            # Unknown - don't guess sold, and don't lose the price we already have.
            return ListingRefresh(sold=False, price=listing.price, shipping_price=listing.shipping_price)

        if data.get("state") in _UNAVAILABLE_STATES:
            return ListingRefresh(sold=True)

        price = _money_to_float(data.get("price")) or listing.price
        return ListingRefresh(sold=False, price=price, shipping_price=listing.shipping_price)

    def comparable_count(self, watch_item: WatchItem, category_def: dict) -> int:
        """PROXY liquidity signal: count of currently-active Etsy listings
        matching the same search - Etsy doesn't expose sold-through data
        via the public API, so this is active-listing volume, not true
        sold-through data (same caveat as ebay_source.py's version)."""
        keywords = (watch_item.parsed_criteria or {}).get("search_keywords") or [
            watch_item.description
        ]
        taxonomy_id = category_def.get("etsy", {}).get("taxonomy_id")
        query = keywords[0] if keywords else watch_item.description
        try:
            data = self._search(query, taxonomy_id, limit=1)
        except requests.RequestException:
            return 0
        return int(data.get("count", 0))
