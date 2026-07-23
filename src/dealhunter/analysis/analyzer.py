"""
Per-listing Claude analysis: does it match the hunter's criteria, what's its
condition/authenticity/rarity, and what's it worth. This is the only place
that turns a Listing into an AnalysisResult - src/dealhunter/analysis/scoring.py
then turns that into a deterministic, auditable deal score.
"""
from __future__ import annotations

import anthropic

from dealhunter.claude_client import call_structured
from dealhunter.models import AnalysisResult, DemandTier, Listing, RiskLevel, WatchItem

_SYSTEM = (
    "You are a collectibles appraisal assistant helping a buyer evaluate a "
    "single marketplace listing against their hunt criteria. Be skeptical "
    "and specific: call out anything that looks like a red flag (mismatched "
    "serials, vague/stock photos, price far below market with no "
    "explanation, seller history concerns mentioned in the text, etc). Give "
    "an honest confidence score - if the listing text has too little detail "
    "to value the item, say so with low confidence rather than guessing "
    "precisely. Your output is shown to the buyer as a decision aid, not a "
    "professional appraisal.\n\n"
    "A photo of the listing may be included below the text. When it is, "
    "look closely for visual condition and authenticity cues - wear, "
    "scratches, mismatched parts, box/papers actually shown vs. only "
    "claimed, stock-photo vs. real-photo indicators - and fold what you see "
    "into condition_summary and authenticity_notes. If no photo is "
    "included, evaluate from the text alone and don't penalize confidence "
    "just for that."
)

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "matches_criteria": {
            "type": "boolean",
            "description": "Does this listing match the hunter's stated criteria (item type, condition floor, price ceiling, required accessories, etc)?",
        },
        "match_reasoning": {
            "type": "string",
            "description": "1-3 sentences explaining the matches_criteria verdict.",
        },
        "estimated_value": {
            "type": ["number", "null"],
            "description": "Your estimated fair market value in USD for this exact item in this condition, or null if there is not enough information to estimate.",
        },
        "confidence": {
            "type": "number",
            "description": "0 to 1: how confident you are in estimated_value. Low if the listing lacks detail, high if it closely matches well-known recent comps.",
        },
        "condition_summary": {
            "type": "string",
            "description": "1-2 sentence summary of the item's condition as described/shown.",
        },
        "authenticity_risk": {
            "type": "string",
            "enum": [r.value for r in RiskLevel],
            "description": "Overall authenticity/fraud risk level for this listing.",
        },
        "authenticity_notes": {
            "type": "string",
            "description": "Specific red flags observed, or why there are none.",
        },
        "rarity_notes": {
            "type": "string",
            "description": "Brief note on how rare/hard-to-find this specific reference/variant is.",
        },
        "demand_tier": {
            "type": "string",
            "enum": [t.value for t in DemandTier],
            "description": "Qualitative brand/model recognition and category demand tier.",
        },
        "demand_reasoning": {
            "type": "string",
            "description": "1-2 sentences on why you picked that demand tier.",
        },
    },
    "required": [
        "matches_criteria",
        "match_reasoning",
        "estimated_value",
        "confidence",
        "condition_summary",
        "authenticity_risk",
        "authenticity_notes",
        "rarity_notes",
        "demand_tier",
        "demand_reasoning",
    ],
}


def _build_text(listing: Listing, watch_item: WatchItem) -> str:
    price_str = (
        f"${listing.all_in_price:,.2f} all-in (item + shipping)"
        if listing.all_in_price is not None
        else "price not listed / make offer"
    )
    return (
        f"Hunter's criteria (plain English): {watch_item.description}\n"
        f"Structured criteria: {watch_item.parsed_criteria}\n\n"
        f"Listing source: {listing.source}\n"
        f"Title: {listing.title}\n"
        f"Price: {price_str}\n"
        f"Listing text:\n{listing.body}\n"
    )


def analyze_listing(
    client: anthropic.Anthropic,
    model: str,
    listing: Listing,
    watch_item: WatchItem,
) -> AnalysisResult:
    text = _build_text(listing, watch_item)

    if listing.image_url:
        # Listing photos are the single biggest signal for condition/
        # authenticity, but scraped image URLs sometimes 404 or block
        # hotlinking - fall back to text-only rather than losing the
        # listing entirely if the image call fails.
        content: str | list[dict] = [
            {"type": "text", "text": text},
            {"type": "image", "source": {"type": "url", "url": listing.image_url}},
        ]
        try:
            result = call_structured(
                client,
                model=model,
                system=_SYSTEM,
                user_content=content,
                tool_name="record_analysis",
                tool_description="Record the structured analysis of this listing.",
                input_schema=_INPUT_SCHEMA,
                max_tokens=1200,
            )
            return AnalysisResult.model_validate(result)
        except Exception:  # noqa: BLE001 - bad/unreachable image, retry text-only
            pass

    result = call_structured(
        client,
        model=model,
        system=_SYSTEM,
        user_content=text,
        tool_name="record_analysis",
        tool_description="Record the structured analysis of this listing.",
        input_schema=_INPUT_SCHEMA,
        max_tokens=1200,
    )
    return AnalysisResult.model_validate(result)
