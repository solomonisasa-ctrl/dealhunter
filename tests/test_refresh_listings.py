"""Offline tests for pipeline.refresh_listings - no network calls, a fake
source adapter stands in for refresh_listing()."""
from __future__ import annotations

from dealhunter.models import (
    AnalysisResult,
    DemandTier,
    Finding,
    Listing,
    ListingRefresh,
    LiquidityAssessment,
    RiskLevel,
    WatchItem,
)
from dealhunter.pipeline import refresh_listings
from dealhunter.storage import findings_store, state_store


class _FakeSettings:
    def __init__(self, tmp_path):
        self.findings_path = tmp_path / "findings.json"
        self.state_dir = tmp_path
        (tmp_path).mkdir(parents=True, exist_ok=True)


class _FakeSource:
    def __init__(self, sold_ids: set[str] = frozenset(), prices: dict[str, float] | None = None):
        self.sold_ids = sold_ids
        self.prices = prices or {}
        self.checked: list[str] = []

    def refresh_listing(self, listing: Listing) -> ListingRefresh:
        self.checked.append(listing.id)
        if listing.id in self.sold_ids:
            return ListingRefresh(sold=True)
        new_price = self.prices.get(listing.id, listing.price)
        return ListingRefresh(sold=False, price=new_price, shipping_price=listing.shipping_price)


def _make_finding(
    listing_id: str, watch_item_id: str, price: float = 500.0, estimated_value: float = 600.0
) -> Finding:
    listing = Listing(
        id=listing_id,
        source="ebay",
        category="watches",
        title="Test watch",
        url=f"https://example.com/{listing_id}",
        price=price,
    )
    analysis = AnalysisResult(
        matches_criteria=True,
        match_reasoning="matches",
        estimated_value=estimated_value,
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
    discount = (estimated_value - price) / estimated_value
    return Finding(
        id=f"{watch_item_id}:{listing_id}",
        listing=listing,
        watch_item_id=watch_item_id,
        analysis=analysis,
        deal_score=round(discount * 100),
        liquidity=liquidity,
        all_in_price=price,
        discount=discount,
    )


def _seed(settings, listing_id: str, watch_item_id: str, source_name: str = "ebay", **kwargs):
    finding = _make_finding(listing_id, watch_item_id, **kwargs)
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

    sold, repriced, newly_qualified = refresh_listings(settings, {"ebay": source}, watchlist)

    assert sold == 1
    assert repriced == 0
    assert newly_qualified == []
    updated = findings_store.get_finding(settings.findings_path, "item-a:ebay:1")
    assert updated.listing.status == "sold"
    state = state_store.load_state(settings.state_dir, "ebay")
    assert state["ebay:1"]["status"] == "sold"


def test_still_active_unchanged_price_is_untouched(tmp_path):
    settings = _FakeSettings(tmp_path)
    _seed(settings, "ebay:1", "item-a", price=500.0)
    watchlist = [WatchItem(id="item-a", category="watches", description="anything")]
    source = _FakeSource()  # same price, nothing sold

    sold, repriced, newly_qualified = refresh_listings(settings, {"ebay": source}, watchlist)

    assert (sold, repriced, newly_qualified) == (0, 0, [])
    updated = findings_store.get_finding(settings.findings_path, "item-a:ebay:1")
    assert updated.listing.status != "sold"
    assert updated.all_in_price == 500.0


def test_disabled_watch_item_is_skipped(tmp_path):
    settings = _FakeSettings(tmp_path)
    _seed(settings, "ebay:1", "item-a")
    watchlist = [WatchItem(id="item-a", category="watches", description="anything", enabled=False)]
    source = _FakeSource(sold_ids={"ebay:1"})

    sold, _repriced, _newly = refresh_listings(settings, {"ebay": source}, watchlist)

    assert sold == 0
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

    sold, _repriced, _newly = refresh_listings(settings, {"ebay": source}, watchlist)

    assert sold == 1  # one physical listing, counted once
    assert findings_store.get_finding(settings.findings_path, "item-a:ebay:1").listing.status == "sold"
    assert findings_store.get_finding(settings.findings_path, "item-b:ebay:1").listing.status == "sold"


def test_checks_are_capped_and_oldest_first(tmp_path):
    settings = _FakeSettings(tmp_path)
    watchlist = [WatchItem(id="item-a", category="watches", description="anything")]
    for i in range(30):
        _seed(settings, f"ebay:{i}", "item-a")
        # Stagger first_seen so ordering is deterministic (lower i = older).
        state = state_store.load_state(settings.state_dir, "ebay")
        state[f"ebay:{i}"]["first_seen"] = float(i)
        state_store.save_state(settings.state_dir, "ebay", state)

    source = _FakeSource()
    refresh_listings(settings, {"ebay": source}, watchlist)

    assert len(source.checked) == 25  # capped, not all 30
    assert source.checked == [f"ebay:{i}" for i in range(25)]  # oldest 25 first


def test_price_drop_updates_discount_and_deal_score(tmp_path):
    settings = _FakeSettings(tmp_path)
    # $500 vs $600 estimated value = 17% under market, deal_score 17.
    _seed(settings, "ebay:1", "item-a", price=500.0, estimated_value=600.0)
    watchlist = [WatchItem(id="item-a", category="watches", description="anything")]
    source = _FakeSource(prices={"ebay:1": 400.0})  # price cut to $400

    sold, repriced, _newly = refresh_listings(settings, {"ebay": source}, watchlist)

    assert sold == 0
    assert repriced == 1
    updated = findings_store.get_finding(settings.findings_path, "item-a:ebay:1")
    assert updated.all_in_price == 400.0
    assert updated.listing.price == 400.0
    # (600 - 400) / 600 = 33.3% under market now.
    assert round(updated.discount, 2) == 0.33
    assert updated.deal_score == 33


def test_price_cut_that_clears_threshold_flags_for_notification(tmp_path):
    settings = _FakeSettings(tmp_path)
    # Starts at 17% under market (deal_score 17), below a 30% threshold - not notified yet.
    finding = _seed(settings, "ebay:1", "item-a", price=500.0, estimated_value=600.0)
    assert finding.notified is False
    watchlist = [WatchItem(id="item-a", category="watches", description="anything", discount_threshold=0.30)]
    source = _FakeSource(prices={"ebay:1": 350.0})  # now (600-350)/600 = 41.7% under market

    _sold, _repriced, newly_qualified = refresh_listings(settings, {"ebay": source}, watchlist)

    assert len(newly_qualified) == 1
    assert newly_qualified[0].id == "item-a:ebay:1"
    updated = findings_store.get_finding(settings.findings_path, "item-a:ebay:1")
    assert updated.notified is True


def test_already_notified_finding_is_not_re_flagged_on_a_further_drop(tmp_path):
    settings = _FakeSettings(tmp_path)
    finding = _make_finding("ebay:1", "item-a", price=300.0, estimated_value=600.0)
    finding.notified = True  # already qualified and notified once
    findings_store.append_finding(settings.findings_path, finding)
    state = state_store.load_state(settings.state_dir, "ebay")
    state_store.mark_seen(state, "ebay:1", "item-a")
    state_store.save_state(settings.state_dir, "ebay", state)

    watchlist = [WatchItem(id="item-a", category="watches", description="anything", discount_threshold=0.30)]
    source = _FakeSource(prices={"ebay:1": 250.0})  # drops further, still qualifies

    _sold, repriced, newly_qualified = refresh_listings(settings, {"ebay": source}, watchlist)

    assert repriced == 1  # price/score still updated
    assert newly_qualified == []  # but no duplicate notification
    updated = findings_store.get_finding(settings.findings_path, "item-a:ebay:1")
    assert updated.all_in_price == 250.0
