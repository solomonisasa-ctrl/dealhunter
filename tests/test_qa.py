"""
Offline tests for the follow-up Q&A feature: a fake Anthropic client (no
network calls, no forced tool call - this is free-form conversation)
verifies the question and prior Q&A history reach the prompt correctly.
"""
from __future__ import annotations

from dealhunter.analysis.analyzer import answer_followup
from dealhunter.models import (
    AnalysisResult,
    DemandTier,
    Finding,
    Listing,
    LiquidityAssessment,
    QAEntry,
    RiskLevel,
)


class _FakeTextBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeResponse:
    def __init__(self, text: str):
        self.content = [_FakeTextBlock(text)]


class _FakeMessages:
    def __init__(self, answer: str):
        self.answer = answer
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self.answer)


class _FakeClient:
    def __init__(self, answer: str = "This looks genuine to me."):
        self.messages = _FakeMessages(answer)


def make_finding(qa_history=None) -> Finding:
    listing = Listing(
        id="ebay:v1|1",
        source="ebay",
        category="watches",
        title="Grand Seiko Shunbun",
        url="https://example.com/x",
        price=4200.0,
    )
    analysis = AnalysisResult(
        matches_criteria=True,
        match_reasoning="matches",
        estimated_value=5200.0,
        confidence=0.5,
        condition_summary="excellent",
        authenticity_risk=RiskLevel.MEDIUM,
        authenticity_notes="no reference number given",
        rarity_notes="limited edition",
        demand_tier=DemandTier.HIGH,
        demand_reasoning="strong collector demand",
    )
    liquidity = LiquidityAssessment(
        rating=DemandTier.LOW,
        comparable_count=1,
        algorithmic_tier=DemandTier.LOW,
        claude_tier=DemandTier.HIGH,
        reasoning="test",
    )
    return Finding(
        id="gs-shunbun:ebay:v1|1",
        listing=listing,
        watch_item_id="gs-shunbun",
        analysis=analysis,
        deal_score=57,
        liquidity=liquidity,
        all_in_price=4200.0,
        discount=0.19,
        qa_history=qa_history or [],
    )


def _sent_text(client: _FakeClient) -> str:
    sent = client.messages.calls[0]["messages"][0]["content"]
    if isinstance(sent, str):
        return sent
    return next(b["text"] for b in sent if b["type"] == "text")


def test_answer_followup_returns_text():
    client = _FakeClient(answer="Based on the photos, the crown looks original.")
    finding = make_finding()

    answer = answer_followup(client, "claude-sonnet-5", finding, "Does the crown look original?")

    assert answer == "Based on the photos, the crown looks original."
    assert len(client.messages.calls) == 1
    assert "tools" not in client.messages.calls[0]  # free-form, no forced tool call


def test_answer_followup_includes_question_and_listing_context():
    client = _FakeClient()
    finding = make_finding()

    answer_followup(client, "claude-sonnet-5", finding, "Is this a good price?")

    text = _sent_text(client)
    assert "Is this a good price?" in text
    assert "Grand Seiko Shunbun" in text
    assert "excellent" in text  # prior condition_summary grounding


def test_answer_followup_includes_prior_qa_history():
    client = _FakeClient()
    finding = make_finding(qa_history=[QAEntry(question="Is it authentic?", answer="Likely yes.")])

    answer_followup(client, "claude-sonnet-5", finding, "What about the bracelet?")

    text = _sent_text(client)
    assert "Is it authentic?" in text
    assert "Likely yes." in text
    assert "What about the bracelet?" in text
