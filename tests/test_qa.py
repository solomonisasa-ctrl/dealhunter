"""
Offline tests for the follow-up Q&A feature: a fake Anthropic client (no
network calls, no forced tool call - this is free-form conversation)
verifies prior Q&A turns become a real multi-turn conversation, static
listing/analysis context lives in the system prompt, and a response
starting with a non-text block (e.g. ThinkingBlock) doesn't crash.
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
        self.type = "text"
        self.text = text


class _FakeThinkingBlock:
    """Stands in for anthropic's ThinkingBlock - has no .text attribute,
    which is exactly what used to crash answer_followup."""

    def __init__(self):
        self.type = "thinking"
        self.thinking = "reasoning about the question..."


class _FakeResponse:
    def __init__(self, content: list):
        self.content = content


class _FakeMessages:
    def __init__(self, answer: str, lead_with_thinking: bool = False):
        self.answer = answer
        self.lead_with_thinking = lead_with_thinking
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        blocks = [_FakeTextBlock(self.answer)]
        if self.lead_with_thinking:
            blocks = [_FakeThinkingBlock()] + blocks
        return _FakeResponse(blocks)


class _FakeClient:
    def __init__(self, answer: str = "This looks genuine to me.", lead_with_thinking: bool = False):
        self.messages = _FakeMessages(answer, lead_with_thinking=lead_with_thinking)


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


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    return next(b["text"] for b in content if b["type"] == "text")


def test_answer_followup_returns_text():
    client = _FakeClient(answer="Based on the photos, the crown looks original.")
    finding = make_finding()

    answer = answer_followup(client, "claude-sonnet-5", finding, "Does the crown look original?")

    assert answer == "Based on the photos, the crown looks original."
    assert len(client.messages.calls) == 1
    assert "tools" not in client.messages.calls[0]  # free-form, no forced tool call


def test_leading_thinking_block_does_not_crash():
    """Regression test: Claude can return a ThinkingBlock before the text
    block. answer_followup must find the text, not assume content[0]."""
    client = _FakeClient(answer="The bracelet looks period-correct.", lead_with_thinking=True)
    finding = make_finding()

    answer = answer_followup(client, "claude-sonnet-5", finding, "What about the bracelet?")

    assert answer == "The bracelet looks period-correct."


def test_static_context_lives_in_system_prompt_not_the_message():
    client = _FakeClient()
    finding = make_finding()

    answer_followup(client, "claude-sonnet-5", finding, "Is this a good price?")

    system = client.messages.calls[0]["system"]
    assert "Grand Seiko Shunbun" in system
    assert "excellent" in system  # prior condition_summary grounding

    last_message = client.messages.calls[0]["messages"][-1]
    assert last_message["role"] == "user"
    assert _content_text(last_message["content"]) == "Is this a good price?"
    # The question itself shouldn't need the listing title re-stated - it
    # lives in the system prompt now, not flattened into the user turn.
    assert "Grand Seiko Shunbun" not in _content_text(last_message["content"])


def test_prior_qa_becomes_real_conversation_turns():
    client = _FakeClient()
    finding = make_finding(
        qa_history=[
            QAEntry(question="Is it authentic?", answer="Likely yes."),
            QAEntry(question="Any box or papers?", answer="Not mentioned in the listing."),
        ]
    )

    answer_followup(client, "claude-sonnet-5", finding, "What about the bracelet?")

    messages = client.messages.calls[0]["messages"]
    assert len(messages) == 5  # 2 prior turns (4 messages) + the new question
    assert messages[0] == {"role": "user", "content": "Is it authentic?"}
    assert messages[1] == {"role": "assistant", "content": "Likely yes."}
    assert messages[2] == {"role": "user", "content": "Any box or papers?"}
    assert messages[3] == {"role": "assistant", "content": "Not mentioned in the listing."}
    assert messages[4]["role"] == "user"
    assert _content_text(messages[4]["content"]) == "What about the bracelet?"
