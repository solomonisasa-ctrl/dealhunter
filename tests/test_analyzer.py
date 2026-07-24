"""
Offline tests for the multimodal analyzer: a fake Anthropic client (no
network calls) verifies image blocks are sent when a listing has a photo,
and that a failed image-enabled call falls back to a text-only retry.
"""
from __future__ import annotations

from dealhunter.analysis.analyzer import analyze_listing
from dealhunter.models import DemandTier, Listing, RiskLevel, WatchItem

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
    def __init__(self, fail_first: bool = False):
        self.fail_first = fail_first
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("simulated bad image URL")
        return _FakeResponse(kwargs["tools"][0]["name"], _CANNED_ANALYSIS)


class _FakeClient:
    def __init__(self, fail_first: bool = False):
        self.messages = _FakeMessages(fail_first=fail_first)


def _make_listing(image_url: str | None, image_urls: list[str] | None = None) -> Listing:
    return Listing(
        id="reddit:abc123",
        source="reddit",
        category="watches",
        title="Test watch listing",
        url="https://example.com/listing",
        price=900.0,
        image_url=image_url,
        image_urls=image_urls or [],
        body="A watch for sale.",
    )


def _make_watch_item() -> WatchItem:
    return WatchItem(id="test-item", category="watches", description="any watch under $1000")


def test_no_image_sends_plain_text_content():
    client = _FakeClient()
    listing = _make_listing(image_url=None)
    result = analyze_listing(client, "claude-sonnet-5", listing, _make_watch_item())

    assert result.matches_criteria is True
    assert len(client.messages.calls) == 1
    sent_content = client.messages.calls[0]["messages"][0]["content"]
    assert isinstance(sent_content, str)


def test_image_url_included_as_content_block():
    client = _FakeClient()
    listing = _make_listing(image_url="https://example.com/photo.jpg")
    result = analyze_listing(client, "claude-sonnet-5", listing, _make_watch_item())

    assert result.estimated_value == 1000.0
    assert len(client.messages.calls) == 1
    sent_content = client.messages.calls[0]["messages"][0]["content"]
    assert isinstance(sent_content, list)
    types = [block["type"] for block in sent_content]
    assert "image" in types
    image_block = next(b for b in sent_content if b["type"] == "image")
    assert image_block["source"]["url"] == "https://example.com/photo.jpg"


def test_failed_image_call_falls_back_to_text_only():
    client = _FakeClient(fail_first=True)
    listing = _make_listing(image_url="https://example.com/broken.jpg")
    result = analyze_listing(client, "claude-sonnet-5", listing, _make_watch_item())

    # First call (with image) raised and was swallowed; second call (text-only) succeeded.
    assert result.matches_criteria is True
    assert len(client.messages.calls) == 2
    first_content = client.messages.calls[0]["messages"][0]["content"]
    second_content = client.messages.calls[1]["messages"][0]["content"]
    assert isinstance(first_content, list)  # the failed image attempt
    assert isinstance(second_content, str)  # the successful text-only retry


def test_multiple_images_all_included_as_content_blocks():
    client = _FakeClient()
    listing = _make_listing(
        image_url="https://example.com/1.jpg",
        image_urls=[
            "https://example.com/1.jpg",
            "https://example.com/2.jpg",
            "https://example.com/3.jpg",
        ],
    )
    analyze_listing(client, "claude-sonnet-5", listing, _make_watch_item())

    sent_content = client.messages.calls[0]["messages"][0]["content"]
    image_blocks = [b for b in sent_content if b["type"] == "image"]
    assert len(image_blocks) == 3
    assert [b["source"]["url"] for b in image_blocks] == [
        "https://example.com/1.jpg",
        "https://example.com/2.jpg",
        "https://example.com/3.jpg",
    ]


def test_images_capped_at_four():
    client = _FakeClient()
    urls = [f"https://example.com/{i}.jpg" for i in range(7)]
    listing = _make_listing(image_url=urls[0], image_urls=urls)
    analyze_listing(client, "claude-sonnet-5", listing, _make_watch_item())

    sent_content = client.messages.calls[0]["messages"][0]["content"]
    image_blocks = [b for b in sent_content if b["type"] == "image"]
    assert len(image_blocks) == 4


def test_quick_pass_sends_only_first_photo():
    client = _FakeClient()
    urls = [f"https://example.com/{i}.jpg" for i in range(4)]
    listing = _make_listing(image_url=urls[0], image_urls=urls)
    analyze_listing(client, "claude-sonnet-5", listing, _make_watch_item(), full=False)

    sent_content = client.messages.calls[0]["messages"][0]["content"]
    image_blocks = [b for b in sent_content if b["type"] == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["url"] == urls[0]


def test_full_pass_is_the_default():
    client = _FakeClient()
    urls = [f"https://example.com/{i}.jpg" for i in range(4)]
    listing = _make_listing(image_url=urls[0], image_urls=urls)
    # Not passing `full` at all should behave like full=True, for backward
    # compatibility with dry_run.py and existing callers.
    analyze_listing(client, "claude-sonnet-5", listing, _make_watch_item())

    sent_content = client.messages.calls[0]["messages"][0]["content"]
    image_blocks = [b for b in sent_content if b["type"] == "image"]
    assert len(image_blocks) == 4
