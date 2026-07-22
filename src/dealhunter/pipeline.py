"""
Orchestrates one full hunt run: parse criteria -> fetch -> dedupe -> sold
check -> analyze -> score -> store -> notify -> health report. This is the
only module that wires the other pieces together; sources/analysis/storage/
notify all stay independently testable.
"""
from __future__ import annotations

import time

import anthropic
import yaml

from config.settings import Settings
from dealhunter.analysis.analyzer import analyze_listing
from dealhunter.analysis.scoring import compute_deal_score, compute_liquidity, qualifies_for_notification
from dealhunter.criteria_parser import ensure_parsed_criteria
from dealhunter.healthcheck import assess_source_staleness, overall_status
from dealhunter.models import AnalysisResult, Finding, HealthReport, Listing, SourceHealth, WatchItem
from dealhunter.notify.ntfy import send_deal_alert, send_error_alert
from dealhunter.sources.base import SourceAdapter
from dealhunter.sources.ebay_source import EbaySource
from dealhunter.sources.reddit_source import RedditSource
from dealhunter.storage import findings_store, health_store, state_store
from dealhunter.watchlist_store import load_watchlist, save_watchlist

# Etsy intentionally excluded (phase 2 - see sources/etsy_source.py). Adding
# it later is a one-line addition here plus filling in the source class.
SOURCE_REGISTRY: dict[str, type[SourceAdapter]] = {
    "reddit": RedditSource,
    "ebay": EbaySource,
}


def build_sources(settings: Settings) -> dict[str, SourceAdapter]:
    return {name: cls(settings) for name, cls in SOURCE_REGISTRY.items()}


def load_categories(settings: Settings) -> dict:
    return yaml.safe_load(settings.categories_path.read_text(encoding="utf-8")) or {}


def score_listing(
    client: anthropic.Anthropic,
    model: str,
    listing: Listing,
    watch_item: WatchItem,
    comparable_count: int,
) -> Finding:
    """Runs the Claude analysis + deterministic scoring for one listing.
    Shared by the live pipeline and scripts/dry_run.py so dry-run results
    are produced by the exact same code path as a real run."""
    analysis: AnalysisResult = analyze_listing(client, model, listing, watch_item)
    deal_score, discount = compute_deal_score(listing.all_in_price, analysis)
    liquidity = compute_liquidity(comparable_count, analysis)
    return Finding(
        id=f"{watch_item.id}:{listing.id}",
        listing=listing,
        watch_item_id=watch_item.id,
        analysis=analysis,
        deal_score=deal_score,
        liquidity=liquidity,
        all_in_price=listing.all_in_price,
        discount=discount,
    )


def run_hunt(settings: Settings, source_health_errors: dict[str, str] | None = None) -> HealthReport:
    """Runs one full hunt across the whole watchlist. source_health_errors,
    if provided, marks those sources as already-failed (e.g. from a prior
    verify_credentials() call) so we don't try to use them."""
    start = time.time()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    categories = load_categories(settings)
    sources = build_sources(settings)
    source_health_errors = source_health_errors or {}

    watchlist = load_watchlist(settings.watchlist_path)
    watchlist_changed = False

    source_health: dict[str, SourceHealth] = {
        name: SourceHealth(status="error", errors=[err]) if (err := source_health_errors.get(name)) else SourceHealth()
        for name in sources
    }
    findings_count = 0

    for item in watchlist:
        if not item.enabled:
            continue
        category_def = categories.get(item.category)
        if category_def is None:
            continue

        item, changed = ensure_parsed_criteria(client, settings.anthropic_model, item, category_def.get("structured_fields", []))
        if changed:
            watchlist_changed = True
            watchlist = [item if w.id == item.id else w for w in watchlist]

        for source_name, source in sources.items():
            if source_health[source_name].status == "error":
                continue
            if source_name not in category_def:
                continue  # this category doesn't use this source

            state = state_store.load_state(settings.state_dir, source_name)
            # Seen is scoped to THIS watch item, not global to the source:
            # the same listing (e.g. a Grand Seiko post) can legitimately
            # match more than one watch item, and each should get its own
            # analysis/finding rather than only whichever item ran first.
            seen_ids = {
                lid for lid, entry in state.items() if item.id in entry.get("watch_item_ids", [])
            }

            try:
                listings = source.fetch_new(item, category_def, seen_ids)
            except Exception as exc:  # noqa: BLE001
                source_health[source_name].status = "error"
                source_health[source_name].errors.append(str(exc))
                continue

            source_health[source_name].fetched += len(listings)
            comparable_count = 0
            try:
                comparable_count = source.comparable_count(item, category_def)
            except Exception:  # noqa: BLE001
                pass

            for listing in listings:
                state_store.mark_seen(state, listing.id, item.id)
                source_health[source_name].new += 1

                if listing.status.value == "sold":
                    state_store.mark_sold(state, listing.id)
                    continue

                try:
                    finding = score_listing(client, settings.anthropic_model, listing, item, comparable_count)
                except Exception as exc:  # noqa: BLE001
                    source_health[source_name].errors.append(f"{listing.id}: {exc}")
                    continue

                findings_store.append_finding(settings.findings_path, finding)
                findings_count += 1

                if qualifies_for_notification(finding.analysis, finding.discount, item.discount_threshold):
                    send_deal_alert(settings, finding)
                    finding.notified = True

            state = state_store.prune_old(state)
            state_store.save_state(settings.state_dir, source_name, state)

    if watchlist_changed:
        save_watchlist(settings.watchlist_path, watchlist)

    for name, health in source_health.items():
        if health.status != "error" and health.errors:
            health.status = "warning"

    history = health_store.load_health_history(settings.health_path)
    for name, health in source_health.items():
        if health.status == "ok" and assess_source_staleness(history, name, health.new):
            health.status = "warning"
            health.errors.append(
                f"No new listings from {name} in the last several runs - "
                "worth checking subreddit/category config is still correct."
            )

    report = HealthReport(
        duration_seconds=time.time() - start,
        sources=source_health,
        findings_count=findings_count,
    )
    report.overall_status = overall_status(source_health)
    health_store.append_health(settings.health_path, report)

    if report.overall_status == "error":
        error_lines = [f"{name}: {'; '.join(h.errors)}" for name, h in source_health.items() if h.errors]
        send_error_alert(settings, "\n".join(error_lines) or "Unknown error during hunt run.")

    return report
