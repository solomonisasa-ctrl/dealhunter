"""Offline tests for pipeline.refresh_sold_status - no network calls, a fake
source adapter stands in for check_sold()."""
from __future__ import annotations

from dealhunter.models import (
    AnalysisResult,
    DemandTier,
    Finding,
    Listing,
    LiquidityAssessment,
    RiskLevel,
    WatchItem,
)
from dealhunter.pipeline import refresh_sold_status
from dealhunter.storage import findings_store, state_store


class _FakeSettings:
    def __init__(self, tmp_path):
        self.findings_path = tmp_path / "findings.json"
        self.state_dir = tmp_path
        (tmp_path).mkdir(parents=True, exist_ok=True)


class _FakeSource:
    def __init__(self, sold_ids: set[str]):
        self.sold_ids = sold_ids
        self.checked: list[str] = []

    def check_sold(self, listing: Listing) -> bool:
        self.checked.append(listing.id)
        return listing.id in self.sold_ids


def _make_finding(listing_id: str, watch_item_id: str) -> Finding:
    listing = Listing(
        id=listing_id,
        source="ebay",
        category="watches",
        title="Test watch",
        url=f"https://example.com/{listing_id}",
        price=500.0,
    )
    analysis = AnalysisResult(
        matches_criteria=True,
        match_reasoning="matches",
        estimated_value=600.0,
        confidence=0.7,
        condition_summary="good",
        authenticity_risk=RiskLevel.LOW,
        authenticity_notes="none",
        rarity_notes="common",
        demand_tier=DemandTier.MEDIUM,
        demand_reasoning="steady",
    )
    liquidity = LiquidityAssessment(
        rating=DemandTier.MEDIUM,
        comparable_count=1,
        algorithmic_tier=DemandTier.MEDIUM,
        claude_tier=DemandTier.MEDIUM,
        reasoning="test",
    )
    return Finding(
        id=f"{watch_item_id}:{listing_id}",
        listing=listing,
        watch_item_id=watch_item_id,
        analysis=analysis,
        deal_score=17,
        liquidity=liquidity,
        all_in_price=500.0,
        discount=0.17,
    )


def _seed(settings, listing_id: str, watch_item_id: str, source_name: str = "ebay"):
    finding = _make_finding(listing_id, watch_item_id)
    findings_store.append_finding(settings.findings_path, finding)
    state = state_store.load_state(settings.state_dir, source_name)
    state_store.mark_seen(state, listing_id, watch_item_id)
    state_store.save_state(settings.state_dir, source_name, state)
    return finding


def test_sold_listing_updates_state_and_finding(tmp_path):
    settings = _FakeSettings(tmp_path)
    _seed(settings, "ebay:1", "item-a")
    watchlist = [WatchItem(id="item-a", category="watches", description="anything")]
    source = _FakeSource(sold_ids={"ebay:1"})

    newly_sold = refresh_sold_status(settings, {"ebay": source}, watchlist)

    assert newly_sold == 1
    updated = findings_store.get_finding(settings.findings_path, "item-a:ebay:1")
    assert updated.listing.status == "sold"
    state = state_store.load_state(settings.state_dir, "ebay")
    assert state["ebay:1"]["status"] == "sold"


def test_still_active_listing_is_untouched(tmp_path):
    settings = _FakeSettings(tmp_path)
    _seed(settings, "ebay:1", "item-a")
    watchlist = [WatchItem(id="item-a", category="watches", description="anything")]
    source = _FakeSource(sold_ids=set())  # nothing sold

    newly_sold = refresh_sold_status(settings, {"ebay": source}, watchlist)

    assert newly_sold == 0
    updated = findings_store.get_finding(settings.findings_path, "item-a:ebay:1")
    assert updated.listing.status != "sold"


def test_disabled_watch_item_is_skipped(tmp_path):
    settings = _FakeSettings(tmp_path)
    _seed(settings, "ebay:1", "item-a")
    watchlist = [WatchItem(id="item-a", category="watches", description="anything", enabled=False)]
    source = _FakeSource(sold_ids={"ebay:1"})

    newly_sold = refresh_sold_status(settings, {"ebay": source}, watchlist)

    assert newly_sold == 0
    assert source.checked == []  # never even asked, since the hunt is disabled


def test_multiple_findings_for_same_listing_all_get_updated(tmp_path):
    """A listing can match more than one watch item - all its findings
    should flip to sold, not just one."""
    settings = _FakeSettings(tmp_path)
    _seed(settings, "ebay:1", "item-a")
    finding_b = _make_finding("ebay:1", "item-b")
    findings_store.append_finding(settings.findings_path, finding_b)
    state = state_store.load_state(settings.state_dir, "ebay")
    state_store.mark_seen(state, "ebay:1", "item-b")
    state_store.save_state(settings.state_dir, "ebay", state)

    watchlist = [
        WatchItem(id="item-a", category="watches", description="a"),
        WatchItem(id="item-b", category="watches", description="b"),
    ]
    source = _FakeSource(sold_ids={"ebay:1"})

    newly_sold = refresh_sold_status(settings, {"ebay": source}, watchlist)

    assert newly_sold == 1  # one physical listing, counted once
    assert findings_store.get_finding(settings.findings_path, "item-a:ebay:1").listing.status == "sold"
    assert findings_store.get_finding(settings.findings_path, "item-b:ebay:1").listing.status == "sold"


def test_checks_are_capped_and_oldest_first(tmp_path):
    settings = _FakeSettings(tmp_path)
    watchlist = [WatchItem(id="item-a", category="watches", description="anything")]
    for i in range(30):
        finding = _seed(settings, f"ebay:{i}", "item-a")
        # Stagger first_seen so ordering is deterministic (lower i = older).
        state = state_store.load_state(settings.state_dir, "ebay")
        state[f"ebay:{i}"]["first_seen"] = float(i)
        state_store.save_state(settings.state_dir, "ebay", state)

    source = _FakeSource(sold_ids=set())
    refresh_sold_status(settings, {"ebay": source}, watchlist)

    assert len(source.checked) == 25  # capped, not all 30
    assert source.checked == [f"ebay:{i}" for i in range(25)]  # oldest 25 first
