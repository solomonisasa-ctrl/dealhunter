"""
Per-listing Claude analysis: does it match the hunter's criteria, what's its
condition/authenticity/rarity, and what's it worth. This is the only place
that turns a Listing into an AnalysisResult - src/dealhunter/analysis/scoring.py
then turns that into a deterministic, auditable deal score.
"""
from __future__ import annotations

import anthropic

from dealhunter.claude_client import call_structured
from dealhunter.models import AnalysisResult, DemandTier, Finding, Listing, RiskLevel, WatchItem

# Bounds Claude cost/latency per listing - most listings don't need more
# than a handful of angles to assess condition/authenticity anyway.
_MAX_IMAGES_FULL = 4
# The cheap default pass every new listing gets: first photo only, so bad
# deals don't burn a multi-image call before anyone's decided they're
# worth a closer look. See pipeline.score_listing's `full` param.
_MAX_IMAGES_QUICK = 1

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
    "Be strict about matches_criteria, especially model/reference "
    "specificity: if the hunter names a specific model, reference number, "
    "or limited-edition name (e.g. a named limited edition), matches_criteria "
    "must be false unless the listing is that exact model/reference - a "
    "different model from the same brand or product line does NOT count as "
    "a match, no matter how similar or related it is. Only treat it as a "
    "match if the hunter's own description was itself generic (no specific "
    "model named).\n\n"
    "One or more photos of the listing may be included below the text. "
    "When present, look closely across all of them for visual condition and "
    "authenticity cues - wear, scratches, mismatched parts, box/papers "
    "actually shown vs. only claimed, stock-photo vs. real-photo indicators "
    "- and fold what you see into condition_summary and authenticity_notes. "
    "If no photo is included, evaluate from the text alone and don't "
    "penalize confidence just for that."
)

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "matches_criteria": {
            "type": "boolean",
            "description": "Does this listing match the hunter's stated criteria (item type, condition floor, price ceiling, required accessories, etc)? If the hunter named a specific model/reference/limited-edition, this must be false for any other model, even from the same brand.",
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


def _image_urls_for(listing: Listing, full: bool = True) -> list[str]:
    cap = _MAX_IMAGES_FULL if full else _MAX_IMAGES_QUICK
    urls = listing.image_urls or ([listing.image_url] if listing.image_url else [])
    return urls[:cap]


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
    full: bool = True,
) -> AnalysisResult:
    """full=False caps images at 1 (the cheap first pass every new listing
    gets); full=True sends up to _MAX_IMAGES_FULL (the deep dive, reserved
    for listings that already cleared their hunt's deal threshold or that
    the user explicitly asked to re-analyze)."""
    text = _build_text(listing, watch_item)
    image_urls = _image_urls_for(listing, full)

    if image_urls:
        # Listing photos are the single biggest signal for condition/
        # authenticity, but scraped image URLs sometimes 404 or block
        # hotlinking - fall back to text-only rather than losing the
        # listing entirely if the image call fails.
        content: str | list[dict] = [{"type": "text", "text": text}] + [
            {"type": "image", "source": {"type": "url", "url": url}} for url in image_urls
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


_QA_SYSTEM = (
    "You are a collectibles appraisal assistant. The buyer already had this "
    "listing analyzed and is now asking a follow-up question about it. "
    "Answer directly and concisely, grounded in the listing text/photos and "
    "your prior analysis below - don't just repeat the prior analysis "
    "verbatim, actually address what they're asking. If you don't have "
    "enough information to answer confidently, say so plainly rather than "
    "guessing. This is a decision aid, not a professional appraisal."
)


def _static_finding_context(finding: Finding) -> str:
    """Context that doesn't change turn to turn - listing text plus
    Claude's original structured analysis. Lives in the system prompt (see
    answer_followup) rather than being re-explained in every user message,
    so the actual messages list can be a real conversation."""
    listing = finding.listing
    analysis = finding.analysis
    price_str = (
        f"${finding.all_in_price:,.2f} all-in" if finding.all_in_price is not None else "price not listed"
    )
    return (
        f"Listing title: {listing.title}\n"
        f"Price: {price_str}\n"
        f"Listing text:\n{listing.body}\n\n"
        f"Your prior analysis of this listing:\n"
        f"- Matches criteria: {analysis.matches_criteria} ({analysis.match_reasoning})\n"
        f"- Estimated value: {analysis.estimated_value} (confidence {analysis.confidence})\n"
        f"- Condition: {analysis.condition_summary}\n"
        f"- Authenticity risk: {analysis.authenticity_risk.value} - {analysis.authenticity_notes}\n"
        f"- Rarity: {analysis.rarity_notes}\n"
        f"- Demand: {analysis.demand_tier.value} - {analysis.demand_reasoning}\n"
    )


def _first_text_block(content_blocks) -> str:
    """Claude's response can include non-text blocks (e.g. a ThinkingBlock)
    ahead of the actual answer - find the first real text block instead of
    assuming content[0] always is one."""
    for block in content_blocks:
        if getattr(block, "type", None) == "text":
            return block.text
    raise RuntimeError("Claude's response had no text content block")


def answer_followup(
    client: anthropic.Anthropic,
    model: str,
    finding: Finding,
    question: str,
) -> str:
    """Free-form (not tool-forced) follow-up answer about an already-scored
    finding. The listing/analysis context lives in the system prompt (it's
    static); every prior Q&A turn plus the new question is sent as real
    alternating user/assistant messages, so this is an actual back-and-
    forth conversation rather than a flattened transcript re-explained on
    every call."""
    system = f"{_QA_SYSTEM}\n\n{_static_finding_context(finding)}"

    messages: list[dict] = []
    for qa in finding.qa_history:
        messages.append({"role": "user", "content": qa.question})
        messages.append({"role": "assistant", "content": qa.answer})

    image_urls = _image_urls_for(finding.listing)
    new_content: str | list[dict] = (
        [{"type": "text", "text": question}]
        + [{"type": "image", "source": {"type": "url", "url": url}} for url in image_urls]
        if image_urls
        else question
    )
    messages.append({"role": "user", "content": new_content})

    response = client.messages.create(
        model=model,
        max_tokens=600,
        system=system,
        messages=messages,
    )
    return _first_text_block(response.content)
