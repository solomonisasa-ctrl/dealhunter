from dealhunter.models import (
    AnalysisResult,
    DemandTier,
    Finding,
    Listing,
    LiquidityAssessment,
    RiskLevel,
)
from dealhunter.notify import ntfy


class _FakeSettings:
    ntfy_server = "https://ntfy.sh"
    ntfy_topic = "test-topic"


def make_finding(deal_score: int, title: str, price: float, listing_id: str) -> Finding:
    listing = Listing(
        id=listing_id,
        source="reddit",
        category="watches",
        title=title,
        url=f"https://example.com/{listing_id}",
        price=price,
    )
    analysis = AnalysisResult(
        matches_criteria=True,
        match_reasoning="matches",
        estimated_value=price * 1.4,
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
    return Finding(
        id=f"item:{listing_id}",
        listing=listing,
        watch_item_id="item",
        analysis=analysis,
        deal_score=deal_score,
        liquidity=liquidity,
        all_in_price=price,
        discount=0.3,
        notified=True,
    )


def test_send_deal_digest_empty_list_sends_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(ntfy.requests, "post", lambda *a, **k: calls.append((a, k)))
    ntfy.send_deal_digest(_FakeSettings(), [])
    assert calls == []


def test_send_deal_digest_single_finding_uses_rich_single_format(monkeypatch):
    calls = []
    monkeypatch.setattr(ntfy.requests, "post", lambda *a, **k: calls.append((a, k)))
    finding = make_finding(85, "Omega Constellation", 950.0, "abc123")

    ntfy.send_deal_digest(_FakeSettings(), [finding])

    assert len(calls) == 1
    _, kwargs = calls[0]
    headers = kwargs["headers"]
    assert "Click" in headers  # single-finding format links straight to the listing
    assert headers["Click"] == finding.listing.url
    assert str(finding.deal_score) in headers["Title"]


def test_send_deal_digest_multiple_findings_sends_exactly_one_combined_message(monkeypatch):
    calls = []
    monkeypatch.setattr(ntfy.requests, "post", lambda *a, **k: calls.append((a, k)))
    findings = [
        make_finding(60, "Vostok Amphibia", 70.0, "vostok1"),
        make_finding(90, "Grand Seiko Shunbun", 4200.0, "gs1"),
        make_finding(75, "Omega Constellation", 950.0, "omega1"),
    ]

    ntfy.send_deal_digest(_FakeSettings(), findings)

    assert len(calls) == 1  # exactly one push for all three findings
    _, kwargs = calls[0]
    headers = kwargs["headers"]
    message = kwargs["data"].decode("utf-8")

    assert "3 new deals found" in headers["Title"]
    assert "90" in headers["Title"]  # top score called out in the title
    assert "Click" not in headers  # no single URL makes sense for a digest
    for f in findings:
        assert f.listing.title[:20] in message
        assert f.listing.url in message
    # Highest-scoring finding should appear before the lowest in the body.
    assert message.index("Grand Seiko") < message.index("Vostok")
