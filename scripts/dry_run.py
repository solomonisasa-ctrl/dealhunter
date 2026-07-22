#!/usr/bin/env python
"""
Self-test / dry-run mode: scores fixtures/sample_listings.json through the
exact same Claude analysis + deterministic scoring code the live pipeline
uses (dealhunter.pipeline.score_listing), WITHOUT touching real state,
findings, or sending notifications. Use this to sanity-check scoring logic
changes, or to check a new watch item's plain-English description parses
the way you expect, before trusting it live.

Requires a valid ANTHROPIC_API_KEY (it makes real Claude calls) but never
touches Reddit/eBay or writes to data/.

Usage:
    python scripts/dry_run.py
    python scripts/dry_run.py --fixtures path/to/other_fixtures.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

import anthropic  # noqa: E402

from config.settings import get_settings  # noqa: E402
from dealhunter.criteria_parser import ensure_parsed_criteria  # noqa: E402
from dealhunter.models import Listing, WatchItem  # noqa: E402
from dealhunter.pipeline import load_categories, score_listing  # noqa: E402

_DIVIDER = "-" * 72


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        default=str(REPO_ROOT / "fixtures" / "sample_listings.json"),
        help="Path to a sample_listings.json-shaped fixture file.",
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "dry_run_output.json"),
        help="Where to write the full JSON report (not committed to git).",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set - dry run needs a real key to call Claude.", file=sys.stderr)
        return 1

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    categories = load_categories(settings)
    fixtures = json.loads(Path(args.fixtures).read_text(encoding="utf-8"))

    results = []
    for i, fixture in enumerate(fixtures, start=1):
        watch_item = WatchItem.model_validate(fixture["watch_item"])
        listing = Listing.model_validate(fixture["listing"])
        comparable_count = fixture.get("comparable_count", 0)
        category_def = categories.get(watch_item.category, {})

        print(f"\n{_DIVIDER}\n[{i}/{len(fixtures)}] {listing.title}")
        if fixture.get("_note"):
            print(f"  ({fixture['_note']})")

        watch_item, _ = ensure_parsed_criteria(
            client, settings.anthropic_model, watch_item, category_def.get("structured_fields", [])
        )
        finding = score_listing(client, settings.anthropic_model, listing, watch_item, comparable_count)

        print(f"  Price (all-in): ${finding.all_in_price:,.2f}" if finding.all_in_price else "  Price: n/a")
        print(f"  Deal score: {finding.deal_score}/100 ({finding.score_color})")
        print(f"  Discount: {finding.discount * 100:.0f}%" if finding.discount is not None else "  Discount: n/a")
        print(f"  Liquidity: {finding.liquidity.rating.value} - {finding.liquidity.reasoning}")
        print(f"  Matches criteria: {finding.analysis.matches_criteria} - {finding.analysis.match_reasoning}")
        print(f"  Estimated value: ${finding.analysis.estimated_value:,.2f} (confidence {finding.analysis.confidence:.2f})" if finding.analysis.estimated_value else "  Estimated value: n/a")
        print(f"  Condition: {finding.analysis.condition_summary}")
        print(f"  Authenticity risk: {finding.analysis.authenticity_risk.value} - {finding.analysis.authenticity_notes}")
        print(f"  Rarity notes: {finding.analysis.rarity_notes}")

        results.append(finding.model_dump(mode="json"))

    Path(args.output).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n{_DIVIDER}\nFull report written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
