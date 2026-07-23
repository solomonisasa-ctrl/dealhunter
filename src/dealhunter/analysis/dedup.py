"""
Cross-source/cross-post duplicate detection: the same physical item posted
to more than one source (or reposted) shouldn't score as two unrelated
findings or double-notify. This is a deterministic heuristic, not another
Claude call - same auditable, free, instant style as analysis/scoring.py.
"""
from __future__ import annotations

import difflib
import re

from dealhunter.models import Finding, Listing

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(title: str) -> str:
    return _WHITESPACE_RE.sub(" ", title.strip().lower())


def title_similarity(a: str, b: str) -> float:
    """0-1 similarity between two listing titles, using stdlib difflib on
    normalized (lowercased, whitespace-collapsed) text."""
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def price_close(a: float | None, b: float | None, tolerance: float = 0.15) -> bool:
    """True if two all-in prices are within `tolerance` fraction of each
    other. Two listings with no price on one side can't be compared, so
    that's not considered close."""
    if a is None or b is None:
        return False
    if a == 0 or b == 0:
        return a == b
    return abs(a - b) / max(a, b) <= tolerance


def is_likely_duplicate(
    a: Listing,
    b: Listing,
    title_threshold: float = 0.55,
    price_tolerance: float = 0.15,
) -> bool:
    """Heuristic match for 'probably the same physical item': same
    category, similar price, and similar title. Deliberately conservative
    (both signals required) to avoid hiding genuinely different listings."""
    if a.category != b.category:
        return False
    if not price_close(a.all_in_price, b.all_in_price, price_tolerance):
        return False
    return title_similarity(a.title, b.title) >= title_threshold


def find_duplicate(listing: Listing, candidates: list[Finding]) -> Finding | None:
    """First candidate Finding whose listing looks like the same physical
    item as `listing`, or None. Candidates should already be filtered to
    the same watch item and a reasonable recency window by the caller."""
    for candidate in candidates:
        if candidate.listing.id == listing.id:
            continue  # never match a listing against itself
        if is_likely_duplicate(listing, candidate.listing):
            return candidate
    return None
