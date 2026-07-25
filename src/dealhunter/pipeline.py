"""
Orchestrates one full hunt run: parse criteria -> fetch -> dedupe -> sold
check -> analyze -> score -> store -> notify -> health report. This is the
only module that wires the other pieces together; sources/analysis/storage/
notify all stay independently testable.
"""
from __future__ import annotations

import concurrent.futures
import time

import anthropic
import yaml

from config.settings import Settings
from dealhunter import progress as progress_tracker
from dealhunter.analysis.analyzer import analyze_listing
from dealhunter.analysis.dedup import find_duplicate
from dealhunter.analysis.scoring import compute_deal_score, compute_liquidity, qualifies_for_notification
from dealhunter.claude_client import make_client
from dealhunter.criteria_parser import ensure_parsed_criteria
from dealhunter.healthcheck import assess_source_staleness, overall_status, verify_credentials
from dealhunter.models import AnalysisResult, Finding, HealthReport, Listing, ListingStatus, SourceHealth, WatchItem
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
    full: bool = True,
) -> Finding:
    """Runs the Claude analysis + deterministic scoring for one listing.
    Shared by the live pipeline and scripts/dry_run.py so dry-run results
    are produced by the exact same code path as a real run.

    full=False runs the cheap first-photo-only pass (see run_hunt's
    two-phase scoring below); full=True (the default, used by dry_run.py
    and the dashboard's manual "full analysis" button) analyzes every
    available photo."""
    analysis: AnalysisResult = analyze_listing(client, model, listing, watch_item, full=full)
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
        analysis_depth="full" if full else "quick",
    )


# Cap per source per run so a big backlog of active listings can't turn one
# run into a burst of dozens of refresh calls - oldest-still-active listings
# are checked first, spreading the load across runs.
_MAX_REFRESH_CHECKS_PER_SOURCE = 25


def refresh_listings(
    settings: Settings, sources: dict[str, SourceAdapter], watchlist: list[WatchItem]
) -> tuple[int, int, list[Finding]]:
    """Re-checks previously-seen active listings: sold, and has the price
    changed. Sellers commonly cut prices on active eBay listings - without
    this, a finding's discount/deal score stays frozen at whatever the
    price was the moment it was first discovered, so a price cut that
    would newly clear a hunt's deal threshold is silently missed. Updates
    dedupe state and every stored Finding for that listing. Returns
    (sold_count, repriced_count, findings newly qualifying for
    notification because of a price cut - a finding already notified once
    isn't re-notified for a further drop)."""
    watch_items_by_id = {w.id: w for w in watchlist}
    enabled_ids = {w.id for w in watchlist if w.enabled}
    findings = findings_store.load_findings(settings.findings_path)
    findings_by_listing_id: dict[str, list[Finding]] = {}
    for f in findings:
        findings_by_listing_id.setdefault(f.listing.id, []).append(f)

    sold_count = 0
    repriced_count = 0
    newly_qualified: list[Finding] = []
    changed = False

    for source_name, source in sources.items():
        state = state_store.load_state(settings.state_dir, source_name)
        candidates = [
            (listing_id, entry)
            for listing_id, entry in state.items()
            if entry.get("status") == "active"
            and enabled_ids.intersection(entry.get("watch_item_ids", []))
            and listing_id in findings_by_listing_id
            # Skip listings the user dismissed everywhere they matched -
            # they're gone for good, so there's no point spending an API
            # call keeping their price/sold status current.
            and any(not f.dismissed for f in findings_by_listing_id[listing_id])
        ]
        candidates.sort(key=lambda kv: kv[1].get("first_seen", 0))

        for listing_id, _entry in candidates[:_MAX_REFRESH_CHECKS_PER_SOURCE]:
            related = findings_by_listing_id[listing_id]
            listing = related[0].listing
            try:
                refresh = source.refresh_listing(listing)
            except Exception:  # noqa: BLE001 - best-effort, never fail the run over this
                continue

            if refresh.sold:
                state_store.mark_sold(state, listing_id)
                for f in related:
                    f.listing.status = ListingStatus.SOLD
                sold_count += 1
                changed = True
                continue

            price_changed = (
                refresh.price != listing.price or refresh.shipping_price != listing.shipping_price
            )
            if not price_changed:
                continue

            changed = True
            repriced_count += 1
            for f in related:
                f.listing.price = refresh.price
                f.listing.shipping_price = refresh.shipping_price
                f.all_in_price = f.listing.all_in_price
                f.deal_score, f.discount = compute_deal_score(f.all_in_price, f.analysis)

                watch_item = watch_items_by_id.get(f.watch_item_id)
                now_qualifies = (
                    watch_item is not None
                    and f.duplicate_of is None
                    and qualifies_for_notification(f.analysis, f.discount, watch_item.discount_threshold)
                )
                if now_qualifies and not f.notified:
                    f.notified = True
                    newly_qualified.append(f)

        state_store.save_state(settings.state_dir, source_name, state)

    if changed:
        findings_store.save_findings(settings.findings_path, findings)
    return sold_count, repriced_count, newly_qualified


# Bounds worst-case run time predictably: a watch item with a very broad
# description (or one just added, so everything is "new") can't turn one
# run into hundreds of sequential Claude calls. Anything past this cap
# isn't lost - it's simply not marked seen, so it's picked up on a later
# run instead of blocking this one.
_MAX_NEW_LISTINGS_PER_RUN = 20

# Quick-pass analysis calls are independent, network-bound, and have no
# shared state, so they run concurrently instead of one at a time - the
# biggest lever for wall-clock run time. Kept modest to stay well clear of
# Anthropic rate limits on a personal-tier account.
_QUICK_PASS_WORKERS = 4


def run_hunt(settings: Settings, source_health_errors: dict[str, str] | None = None) -> HealthReport:
    """Runs one full hunt across the whole watchlist. source_health_errors,
    if provided, marks those sources as already-failed (e.g. from a prior
    verify_credentials() call) so we don't try to use them."""
    start = time.time()
    client = make_client(settings.anthropic_api_key)
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

    enabled_items = [w for w in watchlist if w.enabled]
    total_items = max(len(enabled_items), 1)

    for item_index, item in enumerate(enabled_items, start=1):
        category_def = categories.get(item.category)
        if category_def is None:
            continue

        progress_tracker.update(
            phase="fetching", detail=item.id, current=item_index - 1, total=total_items
        )

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
            # See _MAX_NEW_LISTINGS_PER_RUN - anything past this isn't
            # marked seen below, so it's simply picked up on a later run.
            listings = listings[:_MAX_NEW_LISTINGS_PER_RUN]
            comparable_count = 0
            try:
                comparable_count = source.comparable_count(item, category_def)
            except Exception:  # noqa: BLE001
                pass

            scorable = [lst for lst in listings if lst.status.value != "sold"]

            # Phase 1: run the cheap quick-pass analysis for every new
            # listing IN PARALLEL - each call is an independent, network-
            # bound Claude request with no shared state, so this is the
            # single biggest lever for wall-clock speed (previously fully
            # sequential). Bookkeeping that touches shared files (state,
            # findings.json) stays out of this phase and happens after, in
            # original order, in phase 2 below.
            quick_results: dict[str, Finding | Exception] = {}
            if scorable:
                with concurrent.futures.ThreadPoolExecutor(max_workers=_QUICK_PASS_WORKERS) as pool:
                    future_to_listing = {
                        pool.submit(
                            score_listing, client, settings.anthropic_model, lst, item, comparable_count, full=False
                        ): lst
                        for lst in scorable
                    }
                    done = 0
                    for future in concurrent.futures.as_completed(future_to_listing):
                        lst = future_to_listing[future]
                        done += 1
                        progress_tracker.update(
                            phase="analyzing",
                            detail=f"{item.id} ({source_name}) - listing {done}/{len(future_to_listing)}",
                            current=(item_index - 1) + done / max(len(future_to_listing), 1),
                            total=total_items,
                        )
                        try:
                            quick_results[lst.id] = future.result()
                        except Exception as exc:  # noqa: BLE001
                            quick_results[lst.id] = exc

            # Phase 2: sequential bookkeeping, in the original listing
            # order, so dedup against earlier findings from this same
            # batch (already written to findings.json by an earlier
            # iteration) still works correctly.
            for listing in listings:
                state_store.mark_seen(state, listing.id, item.id)
                source_health[source_name].new += 1

                if listing.status.value == "sold":
                    state_store.mark_sold(state, listing.id)
                    continue

                result = quick_results.get(listing.id)
                if isinstance(result, Exception):
                    source_health[source_name].errors.append(f"{listing.id}: {result}")
                    continue
                finding = result

                cleared_threshold = qualifies_for_notification(
                    finding.analysis, finding.discount, item.discount_threshold
                )
                if cleared_threshold:
                    # Worth a closer look now that the cheap pass says this
                    # is a real deal - fetch whatever extra photos this
                    # source has (a no-op for sources that already had them
                    # all) and re-analyze with everything available.
                    try:
                        listing.image_urls = source.fetch_additional_photos(listing)
                    except Exception:  # noqa: BLE001
                        pass
                    if len(listing.image_urls) > 1:
                        try:
                            finding = score_listing(
                                client, settings.anthropic_model, listing, item, comparable_count, full=True
                            )
                        except Exception:  # noqa: BLE001
                            pass  # keep the quick-pass finding if the deep dive fails

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

    progress_tracker.update(phase="checking sold/price changes", current=total_items, total=total_items)

    # Best-effort: re-check a bounded batch of previously-active listings for
    # sold status and price cuts, so the feed stops showing deals that are
    # gone and picks up drops that newly clear a hunt's threshold. Only asks
    # sources that didn't already fail credential/fetch checks.
    working_sources = {name: src for name, src in sources.items() if source_health[name].status != "error"}
    try:
        sold_detected, repriced_detected, newly_qualified = refresh_listings(settings, working_sources, watchlist)
    except Exception:  # noqa: BLE001 - never let this block the rest of the run
        sold_detected, repriced_detected, newly_qualified = 0, 0, []
    to_notify.extend(newly_qualified)

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
        sold_detected=sold_detected,
        repriced_detected=repriced_detected,
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
    progress_tracker.start()
    try:
        progress_tracker.update(phase="verifying credentials")
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
    except Exception as exc:
        progress_tracker.finish(error=str(exc))
        raise
    progress_tracker.finish()
    return cred_results, report
