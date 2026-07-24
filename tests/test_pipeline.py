"""Offline tests for pipeline.score_listing's quick/full analysis split -
same fake-client pattern as test_analyzer.py, no network calls."""
from __future__ import annotations

from dealhunter.models import DemandTier, Listing, RiskLevel, WatchItem
from dealhunter.pipeline import score_listing

_CANNED_ANALYSIS = {
    "matches_criteria": True,
    "match_reasoning": "looks right",
    "estimated_value": 1000.0,
    "confidence": 0.8,
    "condition_summary": "good",
    "authenticity_risk": RiskLevel.LOW.value,
    "authenticity_notes": "none obvious",
    "rarity_notes": "common",
    "demand_tier": DemandTier.MEDIUM.value,
    "demand_reasoning": "steady demand",
}


class _FakeBlock:
    def __init__(self, tool_name: str, input_dict: dict):
        self.type = "tool_use"
        self.name = tool_name
        self.input = input_dict


class _FakeResponse:
    def __init__(self, tool_name: str, input_dict: dict):
        self.content = [_FakeBlock(tool_name, input_dict)]


class _FakeMessages:
    def __init__(self):
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(kwargs["tools"][0]["name"], _CANNED_ANALYSIS)


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


def _make_listing() -> Listing:
    urls = [f"https://example.com/{i}.jpg" for i in range(4)]
    return Listing(
        id="ebay:v1|123|0",
        source="ebay",
        category="watches",
        title="Test watch",
        url="https://example.com/listing",
        price=700.0,
        image_url=urls[0],
        image_urls=urls,
        body="A watch for sale.",
    )


def _make_watch_item() -> WatchItem:
    return WatchItem(id="test-item", category="watches", description="any watch under $1000")


def test_quick_pass_marks_analysis_depth_quick_and_sends_one_image():
    client = _FakeClient()
    finding = score_listing(client, "claude-sonnet-5", _make_listing(), _make_watch_item(), 0, full=False)

    assert finding.analysis_depth == "quick"
    sent_content = client.messages.calls[0]["messages"][0]["content"]
    image_blocks = [b for b in sent_content if b["type"] == "image"]
    assert len(image_blocks) == 1


def test_full_pass_marks_analysis_depth_full_and_sends_all_images():
    client = _FakeClient()
    finding = score_listing(client, "claude-sonnet-5", _make_listing(), _make_watch_item(), 0, full=True)

    assert finding.analysis_depth == "full"
    sent_content = client.messages.calls[0]["messages"][0]["content"]
    image_blocks = [b for b in sent_content if b["type"] == "image"]
    assert len(image_blocks) == 4


def test_default_is_full_analysis():
    client = _FakeClient()
    finding = score_listing(client, "claude-sonnet-5", _make_listing(), _make_watch_item(), 0)

    assert finding.analysis_depth == "full"
