"""append_finding must upsert by id, not blindly append - two runs (e.g.
local testing and a scheduled run) discovering the same not-yet-seen
listing before their state files sync shouldn't leave duplicate entries."""
from dealhunter.models import (
    AnalysisResult,
    DemandTier,
    Finding,
    Listing,
    LiquidityAssessment,
    RiskLevel,
)
from dealhunter.storage import findings_store


def make_finding(finding_id: str, deal_score: int = 20) -> Finding:
    listing = Listing(
        id="ebay:v1|123|0",
        source="ebay",
        category="watches",
        title="Omega Constellation",
        url="https://example.com/x",
        price=1000.0,
    )
    analysis = AnalysisResult(
        matches_criteria=True,
        match_reasoning="matches",
        estimated_value=1200.0,
        confidence=0.6,
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
        id=finding_id,
        listing=listing,
        watch_item_id="item",
        analysis=analysis,
        deal_score=deal_score,
        liquidity=liquidity,
        all_in_price=1000.0,
        discount=0.2,
    )


def test_append_finding_with_new_id_appends(tmp_path):
    path = tmp_path / "findings.json"
    findings_store.append_finding(path, make_finding("item:a"))
    result = findings_store.append_finding(path, make_finding("item:b"))
    assert [f.id for f in result] == ["item:a", "item:b"]


def test_append_finding_with_existing_id_replaces_not_duplicates(tmp_path):
    path = tmp_path / "findings.json"
    findings_store.append_finding(path, make_finding("item:a", deal_score=20))
    result = findings_store.append_finding(path, make_finding("item:a", deal_score=45))

    assert len(result) == 1
    assert result[0].deal_score == 45


def test_append_finding_replace_preserves_original_position(tmp_path):
    path = tmp_path / "findings.json"
    findings_store.append_finding(path, make_finding("item:a"))
    findings_store.append_finding(path, make_finding("item:b"))
    result = findings_store.append_finding(path, make_finding("item:a", deal_score=99))

    assert [f.id for f in result] == ["item:a", "item:b"]
    assert result[0].deal_score == 99
