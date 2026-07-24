"""
Offline tests for Reddit multi-image extraction - a gallery post has
several distinct photos (via gallery_data/media_metadata), not just one.
"""
from __future__ import annotations

from dealhunter.sources.reddit_source import _all_image_urls


class _FakeSubmission:
    def __init__(
        self,
        is_gallery=False,
        gallery_data=None,
        media_metadata=None,
        url=None,
        preview=None,
    ):
        self.is_gallery = is_gallery
        self.gallery_data = gallery_data
        self.media_metadata = media_metadata
        self.url = url
        self.preview = preview


def test_gallery_post_returns_all_images_in_order():
    submission = _FakeSubmission(
        is_gallery=True,
        gallery_data={"items": [{"media_id": "aaa"}, {"media_id": "bbb"}]},
        media_metadata={
            "aaa": {"s": {"u": "https://preview.redd.it/aaa.jpg?a=1&amp;b=2"}},
            "bbb": {"s": {"u": "https://preview.redd.it/bbb.jpg"}},
        },
    )
    urls = _all_image_urls(submission)
    assert urls == [
        "https://preview.redd.it/aaa.jpg?a=1&b=2",  # &amp; unescaped to &
        "https://preview.redd.it/bbb.jpg",
    ]


def test_single_direct_image_url():
    submission = _FakeSubmission(url="https://i.redd.it/abc123.jpg")
    assert _all_image_urls(submission) == ["https://i.redd.it/abc123.jpg"]


def test_preview_image_fallback():
    submission = _FakeSubmission(
        url="https://reddit.com/r/watchexchange/comments/abc/some_post/",
        preview={"images": [{"source": {"url": "https://preview.redd.it/xyz.jpg"}}]},
    )
    assert _all_image_urls(submission) == ["https://preview.redd.it/xyz.jpg"]


def test_no_image_returns_empty_list():
    submission = _FakeSubmission(url="https://reddit.com/r/watchexchange/comments/abc/text_post/")
    assert _all_image_urls(submission) == []


def test_gallery_flag_true_but_no_matching_metadata_falls_back():
    submission = _FakeSubmission(
        is_gallery=True,
        gallery_data={"items": [{"media_id": "missing"}]},
        media_metadata={},
        url="https://i.redd.it/fallback.png",
    )
    assert _all_image_urls(submission) == ["https://i.redd.it/fallback.png"]
