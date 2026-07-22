"""
Turns a WatchItem's plain-English description into structured search
criteria via Claude - no fixed keyword lists. Runs once per watch item (the
result is cached on WatchItem.parsed_criteria and persisted to
config/watchlist.yaml) rather than on every listing.
"""
from __future__ import annotations

import anthropic

from dealhunter.claude_client import call_structured
from dealhunter.models import WatchItem

_SYSTEM = (
    "You extract structured search criteria from a collector's plain-English "
    "description of what they're hunting for. Be conservative: only fill in "
    "a field if the text clearly supports it, otherwise leave it null. Do "
    "not invent brands, models, or numbers that aren't implied by the text."
)


def _input_schema(fields: list[str]) -> dict:
    properties = {
        field: {
            "type": ["string", "number", "boolean", "null"],
            "description": f"Extracted '{field}' value, or null if not specified.",
        }
        for field in fields
    }
    properties["search_keywords"] = {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "3-8 short keyword phrases well-suited for searching marketplace "
            "titles/listings for this item (brand, model, nicknames, etc.)."
        ),
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["search_keywords"],
    }


def parse_criteria(
    client: anthropic.Anthropic,
    model: str,
    description: str,
    structured_fields: list[str],
) -> dict:
    return call_structured(
        client,
        model=model,
        system=_SYSTEM,
        user_content=(
            f"Plain-English hunt description:\n\n{description}\n\n"
            f"Extract these fields: {', '.join(structured_fields)}. Also "
            "produce search_keywords."
        ),
        tool_name="record_search_criteria",
        tool_description="Record structured search criteria extracted from the description.",
        input_schema=_input_schema(structured_fields),
    )


def ensure_parsed_criteria(
    client: anthropic.Anthropic,
    model: str,
    item: WatchItem,
    structured_fields: list[str],
) -> tuple[WatchItem, bool]:
    """Returns (possibly-updated item, changed). Only calls Claude if
    parsed_criteria is missing, so re-running a hunt doesn't re-parse it."""
    if item.parsed_criteria:
        return item, False
    criteria = parse_criteria(client, model, item.description, structured_fields)
    updated = item.model_copy(update={"parsed_criteria": criteria})
    return updated, True
