"""Unit tests for the category-driven junk-listing pre-filter."""
from dealhunter.junk_filter import is_junk_listing
from dealhunter.models import Listing


def _listing(title: str) -> Listing:
    return Listing(
        id="src:1",
        source="test",
        category="watches",
        title=title,
        url="https://example.com/1",
        price=100.0,
    )


_WATCHES_CATEGORY = {
    "junk_title_phrases": [
        "strap for",
        "band for",
        "bracelet for",
        "compatible with",
        "watch print",
        "sunglasses",
    ]
}


def test_real_watch_listing_is_not_junk():
    listing = _listing("Cartier Santos 100 Steel Auto Silver Dial Strap Watch W20126X8")
    assert is_junk_listing(listing, _WATCHES_CATEGORY) is False


def test_strap_accessory_is_junk():
    listing = _listing("Leather Strap for Cartier Santos 100 Watch - 20mm/23mm")
    assert is_junk_listing(listing, _WATCHES_CATEGORY) is True


def test_bracelet_accessory_is_junk():
    listing = _listing("Bracelet for Cartier Santos WSSA0009 WSSA0018 Repair")
    assert is_junk_listing(listing, _WATCHES_CATEGORY) is True


def test_compatible_with_phrasing_is_junk():
    listing = _listing("Compatible with alligator watch straps for Cartier Santos")
    assert is_junk_listing(listing, _WATCHES_CATEGORY) is True


def test_sunglasses_is_junk():
    listing = _listing("Authentic Cartier Santos-Dumont Sunglasses Made in France")
    assert is_junk_listing(listing, _WATCHES_CATEGORY) is True


def test_art_print_is_junk():
    listing = _listing("Cartier Santos WSSA0018 Watch Print, Luxury Timepiece Wall Art")
    assert is_junk_listing(listing, _WATCHES_CATEGORY) is True


def test_case_insensitive_matching():
    listing = _listing("STRAP FOR Cartier Santos - Genuine Leather")
    assert is_junk_listing(listing, _WATCHES_CATEGORY) is True


def test_no_phrases_configured_never_flags_junk():
    listing = _listing("Leather Strap for Cartier Santos 100 Watch")
    assert is_junk_listing(listing, {}) is False


def test_only_flags_the_configured_category_phrases():
    """A category with no junk_title_phrases configured (e.g. a future
    category that hasn't set any up yet) never filters anything - this is
    opt-in per category, not a global blocklist."""
    sneakers_category = {"junk_title_phrases": ["shoelaces only", "poster print"]}
    listing = _listing("Leather Strap for Cartier Santos 100 Watch")
    assert is_junk_listing(listing, sneakers_category) is False
