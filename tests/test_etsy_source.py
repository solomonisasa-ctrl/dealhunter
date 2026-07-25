"""
Offline tests for the Etsy source adapter: search query construction,
Money-object price conversion, lazy photo fetching, and sold/price refresh -
same monkeypatched-requests pattern as test_ebay_query.py, no network calls.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import dealhunter.sources.etsy_source as etsy_module
from dealhunter.models import Listing, WatchItem
from dealhunter.sources.etsy_source import EtsySource


class _FakeSettings:
    etsy_keystring = "test-keystring"
    etsy_shared_secret = "test-secret"


def make_watch_item(**overrides) -> WatchItem:
    defaults = dict(
        id="gs-shunbun",
        category="watches",
        description="Grand Seiko Shunbun, excellent condition, under $6000 shipped.",
        parsed_criteria={
            "search_keywords": [
                "Grand Seiko Shunbun",
                "Grand Seiko Shunbun Spring Equinox",
            ]
        },
    )
    defaults.update(overrides)
    return WatchItem(**defaults)


def _fake_listing_result(listing_id=111, amount=420000, divisor=100):
    return {
        "listing_id": listing_id,
        "title": "Grand Seiko Shunbun SBGA413",
        "url": "https://www.etsy.com/listing/111/grand-seiko-shunbun",
        "price": {"amount": amount, "divisor": divisor, "currency_code": "USD"},
        "description": "A beautiful Grand Seiko Shunbun.",
        "taxonomy_id": 1234,
    }


def test_verify_credentials_sends_colon_joined_api_key(monkeypatch):
    captured_headers = []

    def _fake_get(url, headers=None, params=None, timeout=None):
        captured_headers.append(headers)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(etsy_module.requests, "get", _fake_get)
    source = EtsySource(_FakeSettings())
    source.verify_credentials()

    assert captured_headers[0]["x-api-key"] == "test-keystring:test-secret"


def test_verify_credentials_raises_on_failure(monkeypatch):
    def _fake_get(url, headers=None, params=None, timeout=None):
        raise etsy_module.requests.RequestException("boom")

    monkeypatch.setattr(etsy_module.requests, "get", _fake_get)
    source = EtsySource(_FakeSettings())
    try:
        source.verify_credentials()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "Etsy credentials invalid" in str(exc)


def test_fetch_new_uses_only_first_keyword(monkeypatch):
    captured = []

    def _fake_get(url, headers=None, params=None, timeout=None):
        captured.append(params)
        resp = MagicMock()
        resp.json.return_value = {"results": [], "count": 0}
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(etsy_module.requests, "get", _fake_get)
    source = EtsySource(_FakeSettings())
    source.fetch_new(make_watch_item(), {"etsy": {}}, set())

    assert captured[0]["keywords"] == "Grand Seiko Shunbun"


def test_fetch_new_converts_money_and_skips_seen(monkeypatch):
    def _fake_get(url, headers=None, params=None, timeout=None):
        resp = MagicMock()
        resp.json.return_value = {
            "results": [_fake_listing_result(listing_id=111), _fake_listing_result(listing_id=222)],
            "count": 2,
        }
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(etsy_module.requests, "get", _fake_get)
    source = EtsySource(_FakeSettings())
    listings = source.fetch_new(make_watch_item(), {"etsy": {}}, seen_ids={"etsy:222"})

    assert len(listings) == 1  # etsy:222 already seen
    listing = listings[0]
    assert listing.id == "etsy:111"
    assert listing.source == "etsy"
    assert listing.price == 4200.0  # 420000 / 100
    assert listing.currency == "USD"
    assert listing.image_url is None  # not in the search payload
    assert listing.image_urls == []


def test_fetch_new_falls_back_to_description_without_keywords(monkeypatch):
    captured = []

    def _fake_get(url, headers=None, params=None, timeout=None):
        captured.append(params)
        resp = MagicMock()
        resp.json.return_value = {"results": [], "count": 0}
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(etsy_module.requests, "get", _fake_get)
    item = make_watch_item(parsed_criteria=None, description="a generic hunt")
    source = EtsySource(_FakeSettings())
    source.fetch_new(item, {"etsy": {}}, set())

    assert captured[0]["keywords"] == "a generic hunt"


def test_comparable_count_reads_the_count_field(monkeypatch):
    def _fake_get(url, headers=None, params=None, timeout=None):
        resp = MagicMock()
        resp.json.return_value = {"results": [], "count": 42}
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(etsy_module.requests, "get", _fake_get)
    source = EtsySource(_FakeSettings())
    count = source.comparable_count(make_watch_item(), {"etsy": {}})

    assert count == 42


def _make_listing(**overrides) -> Listing:
    defaults = dict(
        id="etsy:111",
        source="etsy",
        category="watches",
        title="Grand Seiko Shunbun",
        url="https://www.etsy.com/listing/111",
        price=4200.0,
    )
    defaults.update(overrides)
    return Listing(**defaults)


def test_fetch_additional_photos_sorts_by_rank_and_uses_fullsize_url(monkeypatch):
    def _fake_get(url, headers=None, params=None, timeout=None):
        resp = MagicMock()
        resp.json.return_value = {
            "results": [
                {"rank": 2, "url_fullxfull": "https://example.com/2.jpg"},
                {"rank": 1, "url_fullxfull": "https://example.com/1.jpg"},
            ]
        }
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(etsy_module.requests, "get", _fake_get)
    source = EtsySource(_FakeSettings())
    urls = source.fetch_additional_photos(_make_listing())

    assert urls == ["https://example.com/1.jpg", "https://example.com/2.jpg"]


def test_fetch_additional_photos_skips_call_if_already_has_multiple(monkeypatch):
    calls = []
    monkeypatch.setattr(etsy_module.requests, "get", lambda *a, **k: calls.append(1))

    source = EtsySource(_FakeSettings())
    listing = _make_listing(image_urls=["https://example.com/1.jpg", "https://example.com/2.jpg"])
    urls = source.fetch_additional_photos(listing)

    assert calls == []
    assert urls == ["https://example.com/1.jpg", "https://example.com/2.jpg"]


def test_refresh_listing_404_means_sold(monkeypatch):
    def _fake_get(url, headers=None, params=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 404
        return resp

    monkeypatch.setattr(etsy_module.requests, "get", _fake_get)
    source = EtsySource(_FakeSettings())
    result = source.refresh_listing(_make_listing())

    assert result.sold is True


def test_refresh_listing_sold_out_state_means_sold(monkeypatch):
    def _fake_get(url, headers=None, params=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"state": "sold_out", "price": {"amount": 100, "divisor": 1, "currency_code": "USD"}}
        return resp

    monkeypatch.setattr(etsy_module.requests, "get", _fake_get)
    source = EtsySource(_FakeSettings())
    result = source.refresh_listing(_make_listing())

    assert result.sold is True


def test_refresh_listing_active_returns_updated_price(monkeypatch):
    def _fake_get(url, headers=None, params=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "state": "active",
            "price": {"amount": 350000, "divisor": 100, "currency_code": "USD"},
        }
        return resp

    monkeypatch.setattr(etsy_module.requests, "get", _fake_get)
    source = EtsySource(_FakeSettings())
    result = source.refresh_listing(_make_listing(price=4200.0))

    assert result.sold is False
    assert result.price == 3500.0


def test_refresh_listing_network_error_keeps_existing_price(monkeypatch):
    def _fake_get(url, headers=None, params=None, timeout=None):
        raise etsy_module.requests.RequestException("boom")

    monkeypatch.setattr(etsy_module.requests, "get", _fake_get)
    source = EtsySource(_FakeSettings())
    result = source.refresh_listing(_make_listing(price=4200.0, shipping_price=15.0))

    assert result.sold is False
    assert result.price == 4200.0
    assert result.shipping_price == 15.0
