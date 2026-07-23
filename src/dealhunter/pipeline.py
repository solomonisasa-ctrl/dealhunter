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
from dealhunter.analysis.dedup import find_duplicate
from dealhunter.analysis.scoring import compute_deal_score, compute_liquidity, qualifies_for_notification
from dealhunter.criteria_parser import ensure_parsed_criteria
from dealhunter.healthcheck import assess_source_staleness, overall_status, verify_credentials
from dealhunter.models import AnalysisResult, Finding, HealthReport, Listing, SourceHealth, WatchItem
from dealhunter.notify.ntfy import send_deal_digest, send_error_alert
from dealhunter.schedule_store import load_paused, load_poll_interval_minutes
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


def active_source_names(categories: dict) -> set[str]:
    """Source names referenced by at least one category - e.g. if no
    category has a 'reddit' block, we shouldn't build/health-check/alert on
    a Reddit source nobody is configured to use yet."""
    return {
        name
        for category_def in categories.values()
        for name in SOURCE_REGISTRY
        if name in category_def
    }


def build_sources(settings: Settings, categories: dict) -> dict[str, SourceAdapter]:
    active = active_source_names(categories)
    return {name: cls(settings) for name, cls in SOURCE_REGISTRY.items() if name in active}


def load_categories(settings: Settings) -> dict:
    return yaml.safe_load(settings.categories_path.read_text(encoding="utf-8")) or {}


def is_paused(settings: Settings) -> bool:
    """Whether hunting is paused entirely, per config/schedule.yaml. Like
    due_for_run(), only gates the scheduled/CLI entrypoint - 'Refresh now'
    bypasses this on purpose, since clicking it is an explicit override."""
    return load_paused(settings.schedule_path)


def due_for_run(settings: Settings) -> bool:
    """Whether enough time has passed since the last completed run, per the
    user-configurable config/schedule.yaml. Only gates the scheduled/CLI
    entrypoint (scripts/run_hunt.py) - the dashboard's manual 'Refresh now'
    button calls run_hunt_checked() directly and bypasses this on purpose."""
    interval_minutes = load_poll_interval_minutes(settings.schedule_path)
    latest = health_store.latest_health(settings.health_path)
    if latest is None:
        return True
    elapsed_minutes = (time.time() - latest.timestamp) / 60
    return elapsed_minutes >= interval_minutes


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
    sources = build_sources(settings, categories)
    source_health_errors = source_health_errors or {}

    watchlist = load_watchlist(settings.watchlist_path)
    watchlist_changed = False

    source_health: dict[str, SourceHealth] = {
        name: SourceHealth(status="error", errors=[err]) if (err := source_health_errors.get(name)) else SourceHealth()
        for name in sources
    }
    findings_count = 0
    # Collected across the WHOLE run (every watch item, every source) so a
    # single poll that turns up several deals sends one notification, not
    # one per listing - see notify.ntfy.send_deal_digest.
    to_notify: list[Finding] = []

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

                # Cross-source/repost duplicate check: the same physical item
                # posted to more than one source (or reposted) shouldn't
                # double-notify. Still stored either way, for audit history.
                recent = findings_store.recent_findings_for_item(settings.findings_path, item.id, within_days=7)
                duplicate = find_duplicate(listing, recent)
                if duplicate is not None:
                    finding.duplicate_of = duplicate.id

                if finding.duplicate_of is None and qualifies_for_notification(
                    finding.analysis, finding.discount, item.discount_threshold
                ):
                    finding.notified = True

                findings_store.append_finding(settings.findings_path, finding)
                findings_count += 1

                if finding.notified:
                    to_notify.append(finding)

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

    if to_notify:
        send_deal_digest(settings, to_notify)

    if report.overall_status == "error":
        error_lines = [f"{name}: {'; '.join(h.errors)}" for name, h in source_health.items() if h.errors]
        send_error_alert(settings, "\n".join(error_lines) or "Unknown error during hunt run.")

    return report


def run_hunt_checked(settings: Settings) -> tuple[dict[str, str], HealthReport]:
    """Verifies credentials, then runs one full hunt. Raises RuntimeError if
    the Anthropic key itself is invalid - nothing can run without it. Other
    source credential failures are recorded and those sources are skipped
    for this run instead of aborting entirely. Shared by scripts/run_hunt.py
    (the cron/CLI path) and the dashboard's 'Refresh now' button, so both
    trigger paths behave identically."""
    categories = load_categories(settings)
    sources = build_sources(settings, categories)
    cred_results = verify_credentials(settings, list(sources.values()))

    if cred_results.get("anthropic", "").startswith("error"):
        raise RuntimeError(f"Anthropic API key invalid, aborting run: {cred_results['anthropic']}")

    source_errors = {
        name: result
        for name, result in cred_results.items()
        if name in sources and result.startswith("error")
    }
    report = run_hunt(settings, source_health_errors=source_errors)
    return cred_results, report
