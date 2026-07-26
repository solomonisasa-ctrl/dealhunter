"""
Cheap, category-driven pre-filter for obviously-wrong item types
(accessories, replacement parts, art/media, unrelated products) that a
marketplace's keyword search can surface just because they mention the
same brand/model text as the actual collectible - e.g. a "strap for
Cartier Santos" or a "Cartier Santos watch print" showing up in a search
for "Cartier Santos".

Applied once, source-agnostically, in pipeline.py before any listing
reaches Claude - saves an analysis call on something that was never going
to match, and keeps the "Show all" audit view free of obvious junk.
Driven entirely by config/categories.yaml's per-category
`junk_title_phrases`, so it works for any category (not just watches) with
no source- or category-specific code - a future "sneakers" category just
defines its own phrase list.
"""
from __future__ import annotations

from dealhunter.models import Listing


def is_junk_listing(listing: Listing, category_def: dict) -> bool:
    """True if the listing's title matches one of this category's known
    junk phrases. Phrases should be multi-word and specific on purpose -
    "strap for" rather than bare "strap" - so a genuine listing that
    happens to mention a related word (e.g. "comes with a leather strap")
    isn't excluded by mistake."""
    phrases = category_def.get("junk_title_phrases") or []
    title = listing.title.lower()
    return any(phrase.lower() in title for phrase in phrases)
