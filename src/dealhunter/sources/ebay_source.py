"""
eBay source via the official Browse API (OAuth client-credentials flow).

IMPORTANT LIMITATION: the Browse API only returns ACTIVE listings. Real sold-
listing data lives behind eBay's Marketplace Insights API, which eBay grants
selectively and isn't guaranteed for a personal developer account (confirmed
with the user - see plan). Until/unless that access is granted, comparable_count
below is a PROXY liquidity signal built from active-listing search-result
counts, not true sold-through data. If Marketplace Insights access is granted
later, only this file needs to change - swap comparable_count (and optionally
check_sold) to call it instead; scoring.py and pipeline.py are unaffected.
"""
from __future__ import annotations

import base64
import time

import requests

from config.settings import Settings
from dealhunter.models import Listing, ListingStatus, WatchItem
from dealhunter.sources.base import SourceAdapter

_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_ITEM_URL = "https://api.ebay.com/buy/browse/v1/item/{item_id}"
_SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbaySource(SourceAdapter):
    name = "ebay"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        creds = f"{self._settings.ebay_client_id}:{self._settings.ebay_client_secret}"
        basic = base64.b64encode(creds.encode()).decode()
        resp = requests.post(
            _OAUTH_URL,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": _SCOPE},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + payload.get("expires_in", 7200)
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        }

    def verify_credentials(self) -> None:
        try:
            self._token = None  # force a fresh token fetch
            self._get_token()
        except requests.RequestException as exc:
            raise RuntimeError(f"eBay credentials invalid: {exc}") from exc

    def _search(self, query: str, category_ids: list[str], limit: int = 50) -> dict:
        params = {"q": query, "limit": str(limit)}
        if category_ids:
            params["category_ids"] = ",".join(category_ids)
        resp = requests.get(_SEARCH_URL, headers=self._headers(), params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def fetch_new(
        self, watch_item: WatchItem, category_def: dict, seen_ids: set[str]
    ) -> list[Listing]:
        keywords = (watch_item.parsed_criteria or {}).get("search_keywords") or [
            watch_item.description
        ]
        category_ids = category_def.get("ebay", {}).get("category_ids", [])
        query = " ".join(keywords[:6])
        try:
            data = self._search(query, category_ids)
        except requests.RequestException:
            return []

        listings: list[Listing] = []
        for item in data.get("itemSummaries", []):
            item_id = item.get("itemId")
            if not item_id:
                continue
            listing_id = f"ebay:{item_id}"
            if listing_id in seen_ids:
                continue
            price = item.get("price", {})
            shipping_options = item.get("shippingOptions", [])
            shipping_cost = None
            if shipping_options:
                shipping_cost_val = shipping_options[0].get("shippingCost", {}).get("value")
                shipping_cost = float(shipping_cost_val) if shipping_cost_val else None
            listings.append(
                Listing(
                    id=listing_id,
                    source=self.name,
                    category=watch_item.category,
                    title=item.get("title", ""),
                    url=item.get("itemWebUrl", ""),
                    price=float(price["value"]) if price.get("value") else None,
                    shipping_price=shipping_cost,
                    currency=price.get("currency", "USD"),
                    image_url=(item.get("image") or {}).get("imageUrl"),
                    body=item.get("shortDescription", "") or item.get("title", ""),
                    posted_at=None,
                    status=ListingStatus.ACTIVE,
                    raw={"condition": item.get("condition")},
                )
            )
        return listings

    def check_sold(self, listing: Listing) -> bool:
        item_id = listing.id.split(":", 1)[1]
        try:
            resp = requests.get(
                _ITEM_URL.format(item_id=item_id), headers=self._headers(), timeout=15
            )
            if resp.status_code == 404:
                return True
            resp.raise_for_status()
            return False
        except requests.RequestException:
            return False

    def comparable_count(self, watch_item: WatchItem, category_def: dict) -> int:
        """PROXY liquidity signal: count of currently-active eBay listings
        matching the same search - see module docstring for why this isn't
        true sold-through data."""
        keywords = (watch_item.parsed_criteria or {}).get("search_keywords") or [
            watch_item.description
        ]
        category_ids = category_def.get("ebay", {}).get("category_ids", [])
        query = " ".join(keywords[:6])
        try:
            data = self._search(query, category_ids, limit=1)
        except requests.RequestException:
            return 0
        return int(data.get("total", 0))
