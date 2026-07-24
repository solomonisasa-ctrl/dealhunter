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
