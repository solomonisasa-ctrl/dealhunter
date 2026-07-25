"""
Offline tests for eBay search query construction: verifies fetch_new and
comparable_count send only the single most specific keyword, not all
parsed keywords blended together (which was diluting eBay's search
relevance toward the bare brand name and pulling in unrelated models).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import dealhunter.sources.ebay_source as ebay_module
from dealhunter.models import WatchItem
from dealhunter.sources.ebay_source import EbaySource


class _FakeSettings:
    ebay_client_id = "test-id"
    ebay_client_secret = "test-secret"


def _fake_post(*args, **kwargs):
    resp = MagicMock()
    resp.json.return_value = {"access_token": "tok", "expires_in": 7200}
    resp.raise_for_status.return_value = None
    return resp


def _fake_get_factory(captured: list):
    def _fake_get(url, headers=None, params=None, timeout=None):
        captured.append(params)
        resp = MagicMock()
        resp.json.return_value = {"itemSummaries": [], "total": 0}
        resp.raise_for_status.return_value = None
        return resp

    return _fake_get


def make_watch_item(**overrides) -> WatchItem:
    defaults = dict(
        id="gs-shunbun",
        category="watches",
        description="Grand Seiko Shunbun, excellent condition, box and papers, under $6000 shipped.",
        parsed_criteria={
            "search_keywords": [
                "Grand Seiko Shunbun",
                "Grand Seiko Shunbun Spring Equinox",
                "GS Shunbun limited edition",
                "Grand Seiko Shunbun box papers",
                "Shunbun Grand Seiko watch",
            ]
        },
    )
    defaults.update(overrides)
    return WatchItem(**defaults)


def test_fetch_new_uses_only_first_keyword(monkeypatch):
    captured: list = []
    monkeypatch.setattr(ebay_module.requests, "post", _fake_post)
    monkeypatch.setattr(ebay_module.requests, "get", _fake_get_factory(captured))

    source = EbaySource(_FakeSettings())
    source.fetch_new(make_watch_item(), {"ebay": {"category_ids": ["31387"]}}, set())

    assert len(captured) == 1
    assert captured[0]["q"] == "Grand Seiko Shunbun"


def test_comparable_count_uses_only_first_keyword(monkeypatch):
    captured: list = []
    monkeypatch.setattr(ebay_module.requests, "post", _fake_post)
    monkeypatch.setattr(ebay_module.requests, "get", _fake_get_factory(captured))

    source = EbaySource(_FakeSettings())
    source.comparable_count(make_watch_item(), {"ebay": {"category_ids": ["31387"]}})

    assert len(captured) == 1
    assert captured[0]["q"] == "Grand Seiko Shunbun"


def test_fetch_new_falls_back_to_description_without_keywords(monkeypatch):
    captured: list = []
    monkeypatch.setattr(ebay_module.requests, "post", _fake_post)
    monkeypatch.setattr(ebay_module.requests, "get", _fake_get_factory(captured))

    item = make_watch_item(parsed_criteria=None, description="a generic hunt")
    source = EbaySource(_FakeSettings())
    source.fetch_new(item, {"ebay": {}}, set())

    assert captured[0]["q"] == "a generic hunt"


def test_raw_search_count_uses_the_raw_description_as_the_query(monkeypatch):
    captured: list = []

    def _fake_get(url, headers=None, params=None, timeout=None):
        captured.append(params)
        resp = MagicMock()
        resp.json.return_value = {"itemSummaries": [], "total": 187}
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(ebay_module.requests, "post", _fake_post)
    monkeypatch.setattr(ebay_module.requests, "get", _fake_get)

    source = EbaySource(_FakeSettings())
    count = source.raw_search_count("vintage omega constellation", ["31387"])

    assert count == 187
    assert captured[0]["q"] == "vintage omega constellation"


def test_raw_search_count_empty_query_returns_zero_without_a_call(monkeypatch):
    calls = []
    monkeypatch.setattr(ebay_module.requests, "post", _fake_post)
    monkeypatch.setattr(ebay_module.requests, "get", lambda *a, **k: calls.append(1))

    source = EbaySource(_FakeSettings())
    count = source.raw_search_count("   ", [])

    assert count == 0
    assert calls == []


def test_fetch_new_does_not_eagerly_fetch_additional_photos(monkeypatch):
    """Regression test: fetching extra photos for every new listing (a
    separate per-item API call each) was real added latency paid even for
    listings that turn out to be bad deals. fetch_new should make exactly
    one request (the search) no matter how many items come back."""
    call_count = {"n": 0}

    def _fake_get(url, headers=None, params=None, timeout=None):
        call_count["n"] += 1
        resp = MagicMock()
        resp.json.return_value = {
            "itemSummaries": [
                {
                    "itemId": "v1|111|0",
                    "title": "Grand Seiko Shunbun",
                    "itemWebUrl": "https://ebay.com/itm/111",
                    "price": {"value": "4200.00", "currency": "USD"},
                    "image": {"imageUrl": "https://example.com/primary.jpg"},
                }
            ],
            "total": 1,
        }
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(ebay_module.requests, "post", _fake_post)
    monkeypatch.setattr(ebay_module.requests, "get", _fake_get)

    source = EbaySource(_FakeSettings())
    listings = source.fetch_new(make_watch_item(), {"ebay": {"category_ids": ["31387"]}}, set())

    assert call_count["n"] == 1  # only the search - no per-item detail call
    assert len(listings) == 1
    assert listings[0].image_url == "https://example.com/primary.jpg"
    assert listings[0].image_urls == []  # not fetched yet


def test_fetch_additional_photos_fetches_the_full_set(monkeypatch):
    def _fake_get(url, headers=None, params=None, timeout=None):
        resp = MagicMock()
        resp.json.return_value = {
            "image": {"imageUrl": "https://example.com/1.jpg"},
            "additionalImages": [
                {"imageUrl": "https://example.com/2.jpg"},
                {"imageUrl": "https://example.com/3.jpg"},
            ],
        }
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(ebay_module.requests, "post", _fake_post)
    monkeypatch.setattr(ebay_module.requests, "get", _fake_get)

    from dealhunter.models import Listing

    listing = Listing(
        id="ebay:v1|111|0",
        source="ebay",
        category="watches",
        title="Grand Seiko Shunbun",
        url="https://ebay.com/itm/111",
        price=4200.0,
        image_url="https://example.com/1.jpg",
    )
    source = EbaySource(_FakeSettings())
    urls = source.fetch_additional_photos(listing)

    assert urls == [
        "https://example.com/1.jpg",
        "https://example.com/2.jpg",
        "https://example.com/3.jpg",
    ]


def test_fetch_additional_photos_skips_the_call_if_already_has_multiple(monkeypatch):
    calls = []
    monkeypatch.setattr(ebay_module.requests, "post", _fake_post)
    monkeypatch.setattr(ebay_module.requests, "get", lambda *a, **k: calls.append(1))

    from dealhunter.models import Listing

    listing = Listing(
        id="ebay:v1|111|0",
        source="ebay",
        category="watches",
        title="Grand Seiko Shunbun",
        url="https://ebay.com/itm/111",
        price=4200.0,
        image_url="https://example.com/1.jpg",
        image_urls=["https://example.com/1.jpg", "https://example.com/2.jpg"],
    )
    source = EbaySource(_FakeSettings())
    urls = source.fetch_additional_photos(listing)

    assert calls == []  # already had more than one - no network call needed
    assert urls == ["https://example.com/1.jpg", "https://example.com/2.jpg"]
