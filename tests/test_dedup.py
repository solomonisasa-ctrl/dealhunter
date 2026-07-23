from dealhunter.analysis.dedup import find_duplicate, is_likely_duplicate, price_close, title_similarity
from dealhunter.models import (
    AnalysisResult,
    DemandTier,
    Finding,
    Listing,
    LiquidityAssessment,
    RiskLevel,
)


def make_listing(**overrides) -> Listing:
    defaults = dict(
        id="reddit:abc123",
        source="reddit",
        category="watches",
        title="Omega Constellation 35mm steel box only $950 shipped",
        url="https://example.com/a",
        price=950.0,
        shipping_price=0.0,
    )
    defaults.update(overrides)
    return Listing(**defaults)


def make_finding(listing: Listing, **overrides) -> Finding:
    analysis = AnalysisResult(
        matches_criteria=True,
        match_reasoning="matches",
        estimated_value=1000.0,
        confidence=0.8,
        condition_summary="good",
        authenticity_risk=RiskLevel.LOW,
        authenticity_notes="none",
        rarity_notes="common",
        demand_tier=DemandTier.MEDIUM,
        demand_reasoning="steady",
    )
    liquidity = LiquidityAssessment(
        rating=DemandTier.MEDIUM,
        comparable_count=2,
        algorithmic_tier=DemandTier.MEDIUM,
        claude_tier=DemandTier.MEDIUM,
        reasoning="test",
    )
    defaults = dict(
        id=f"test-item:{listing.id}",
        listing=listing,
        watch_item_id="test-item",
        analysis=analysis,
        deal_score=60,
        liquidity=liquidity,
        all_in_price=listing.all_in_price,
        discount=0.05,
    )
    defaults.update(overrides)
    return Finding(**defaults)


def test_title_similarity_identical():
    assert title_similarity("Omega Constellation", "Omega Constellation") == 1.0


def test_title_similarity_case_and_whitespace_insensitive():
    assert title_similarity("Omega  Constellation ", "omega constellation") == 1.0


def test_title_similarity_different_items_is_low():
    assert title_similarity("Omega Constellation 35mm steel", "Vostok Amphibia 710") < 0.4


def test_price_close_within_tolerance():
    assert price_close(950.0, 1000.0) is True  # ~5% apart


def test_price_close_outside_tolerance():
    assert price_close(700.0, 1000.0) is False  # 30% apart


def test_price_close_none_is_never_close():
    assert price_close(None, 1000.0) is False
    assert price_close(950.0, None) is False


def test_price_close_both_zero():
    assert price_close(0.0, 0.0) is True


def test_is_likely_duplicate_same_item_cross_source():
    a = make_listing(id="reddit:abc123", source="reddit", price=950.0, title="Omega Constellation 35mm steel box only $950 shipped")
    b = make_listing(id="ebay:v1|999", source="ebay", price=975.0, title="Omega Constellation 35mm Steel - Box Included")
    assert is_likely_duplicate(a, b) is True


def test_is_likely_duplicate_different_category():
    a = make_listing(category="watches")
    b = make_listing(category="sneakers", id="ebay:v1|1")
    assert is_likely_duplicate(a, b) is False


def test_is_likely_duplicate_different_price():
    a = make_listing(price=950.0)
    b = make_listing(id="ebay:v1|1", price=1500.0)
    assert is_likely_duplicate(a, b) is False


def test_is_likely_duplicate_different_item_similar_price():
    a = make_listing(price=950.0, title="Omega Constellation 35mm steel box only $950 shipped")
    b = make_listing(id="ebay:v1|1", price=960.0, title="Vostok Amphibia 710 automatic all original")
    assert is_likely_duplicate(a, b) is False


def test_find_duplicate_matches_among_candidates():
    original_listing = make_listing(id="reddit:abc123", source="reddit", price=950.0)
    other_listing = make_listing(id="reddit:zzz999", source="reddit", price=70.0, title="Vostok Amphibia 710 all original")
    candidates = [make_finding(other_listing), make_finding(original_listing)]

    new_listing = make_listing(id="ebay:v1|999", source="ebay", price=975.0, title="Omega Constellation 35mm Steel - Box Included")
    match = find_duplicate(new_listing, candidates)

    assert match is not None
    assert match.listing.id == "reddit:abc123"


def test_find_duplicate_never_matches_itself():
    listing = make_listing(id="reddit:abc123")
    candidates = [make_finding(listing)]
    assert find_duplicate(listing, candidates) is None


def test_find_duplicate_returns_none_when_no_match():
    other_listing = make_listing(id="reddit:zzz999", price=70.0, title="Vostok Amphibia 710 all original")
    candidates = [make_finding(other_listing)]

    new_listing = make_listing(id="ebay:v1|999", price=950.0, title="Omega Constellation 35mm Steel")
    assert find_duplicate(new_listing, candidates) is None
