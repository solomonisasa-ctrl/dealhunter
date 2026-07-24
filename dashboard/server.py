#!/usr/bin/env python
"""
Local-only dashboard. Run with:
    uvicorn dashboard.server:app --reload --port 8420
Then open http://127.0.0.1:8420

Reads data/findings.json and data/health.json directly off disk (updated by
GitHub Actions commits + your `git pull`), and reads/writes
config/watchlist.yaml directly (safe since this only ever runs on your own
machine, never deployed as a shared server).
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from config.settings import get_settings  # noqa: E402
from dealhunter import pipeline  # noqa: E402
from dealhunter import progress as progress_tracker  # noqa: E402
from dealhunter.analysis.analyzer import answer_followup  # noqa: E402
from dealhunter.analysis.scoring import qualifies_for_notification  # noqa: E402
from dealhunter.claude_client import make_client  # noqa: E402
from dealhunter.models import QAEntry, WatchItem  # noqa: E402
from dealhunter.pipeline import load_categories  # noqa: E402
from dealhunter.sources.ebay_source import EbaySource  # noqa: E402
from dealhunter.schedule_store import (  # noqa: E402
    load_paused,
    load_poll_interval_minutes,
    save_paused,
    save_poll_interval_minutes,
)
from dealhunter.storage import findings_store, health_store  # noqa: E402
from dealhunter.watchlist_store import (  # noqa: E402
    delete_watch_item,
    load_watchlist,
    upsert_watch_item,
)

app = FastAPI(title="Deal Hunter Dashboard")
settings = get_settings()

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/api/findings")
def api_findings(watch_item_id: str | None = None, sort: str = "date", show_all: bool = False):
    findings = findings_store.load_findings(settings.findings_path)
    watchlist_by_id = {w.id: w for w in load_watchlist(settings.watchlist_path)}

    # Always drop findings for watch items that no longer exist - deleting
    # a hunt should remove its listings from the feed, not just hide the
    # watch item itself.
    findings = [f for f in findings if f.watch_item_id in watchlist_by_id]

    if not show_all:
        # Default view is "deals you can still buy", not "everything
        # analyzed": hide duplicates, sold-out listings, and anything that
        # didn't actually match the hunter's criteria or clear their
        # discount threshold. discount_threshold is looked up live so
        # editing it later re-filters existing findings with no backfill
        # needed. Sold listings stay visible under "Show all" (with a Sold
        # badge) since they're still useful for auditing past finds.
        findings = [
            f
            for f in findings
            if f.duplicate_of is None
            and f.listing.status != "sold"
            and qualifies_for_notification(
                f.analysis, f.discount, watchlist_by_id[f.watch_item_id].discount_threshold
            )
        ]

    if watch_item_id:
        findings = [f for f in findings if f.watch_item_id == watch_item_id]
    if sort == "score":
        findings.sort(key=lambda f: f.deal_score, reverse=True)
    elif sort == "price":
        findings.sort(key=lambda f: (f.all_in_price is None, f.all_in_price))
    else:
        findings.sort(key=lambda f: f.created_at, reverse=True)
    return [f.model_dump(mode="json") for f in findings]


@app.get("/api/findings/{finding_id:path}")
def api_finding_detail(finding_id: str):
    finding = findings_store.get_finding(settings.findings_path, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding.model_dump(mode="json")


@app.post("/api/findings/{finding_id:path}/ask")
def api_ask_finding(finding_id: str, payload: dict):
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    finding = findings_store.get_finding(settings.findings_path, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")

    client = make_client(settings.anthropic_api_key)
    try:
        answer = answer_followup(client, settings.anthropic_model, finding, question)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))

    finding.qa_history.append(QAEntry(question=question, answer=answer))
    findings_store.update_finding(settings.findings_path, finding)
    return finding.model_dump(mode="json")


@app.post("/api/findings/{finding_id:path}/full-analysis")
def api_full_analysis(finding_id: str):
    """Manual deep-dive: re-analyzes a finding with every available photo,
    for a listing that only got the cheap first-photo-only pass (either it
    didn't clear its hunt's deal threshold automatically, or the user just
    wants a closer look before spending on it)."""
    finding = findings_store.get_finding(settings.findings_path, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    if finding.analysis_depth == "full":
        return finding.model_dump(mode="json")

    watch_item = next(
        (w for w in load_watchlist(settings.watchlist_path) if w.id == finding.watch_item_id), None
    )
    if watch_item is None:
        raise HTTPException(status_code=404, detail="Watch item for this finding no longer exists")

    client = make_client(settings.anthropic_api_key)
    try:
        updated = pipeline.score_listing(
            client,
            settings.anthropic_model,
            finding.listing,
            watch_item,
            finding.liquidity.comparable_count,
            full=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))

    updated.id = finding.id
    updated.duplicate_of = finding.duplicate_of
    updated.notified = finding.notified
    updated.qa_history = finding.qa_history
    updated.created_at = finding.created_at

    findings_store.update_finding(settings.findings_path, updated)
    return updated.model_dump(mode="json")


@app.get("/api/watchlist")
def api_get_watchlist():
    return [item.model_dump(mode="json") for item in load_watchlist(settings.watchlist_path)]


@app.post("/api/watchlist")
def api_upsert_watch_item(item: WatchItem):
    items = upsert_watch_item(settings.watchlist_path, item)
    return [i.model_dump(mode="json") for i in items]


@app.delete("/api/watchlist/{item_id}")
def api_delete_watch_item(item_id: str):
    items = delete_watch_item(settings.watchlist_path, item_id)
    return [i.model_dump(mode="json") for i in items]


@app.get("/api/watchlist/preview-match-count")
def api_preview_match_count(description: str, category: str = "watches"):
    """Cheap heads-up for the Add/Edit hunt form: how many active eBay
    listings currently match this raw description, with no Claude call
    involved. eBay's search matching is fuzzy (not a strict phrase match),
    so this is a rough relative signal - broader descriptions return bigger
    numbers - not a precise prediction of next-run Claude usage."""
    categories = load_categories(settings)
    category_def = categories.get(category, {})
    category_ids = category_def.get("ebay", {}).get("category_ids", [])
    try:
        count = EbaySource(settings).raw_search_count(description, category_ids)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))
    return {"count": count}


@app.get("/api/categories")
def api_categories():
    return load_categories(settings)


@app.get("/api/health")
def api_health():
    history = health_store.load_health_history(settings.health_path)
    latest = history[-1].model_dump(mode="json") if history else None
    return {"latest": latest, "unpushed_config_changes": _has_unpushed_config_changes()}


def _has_unpushed_config_changes() -> bool:
    """Read-only `git status` check - never auto-commits or pushes. Used to
    show a reminder banner so scheduled runs actually pick up your edits
    (watchlist, category, or schedule config)."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", "config/"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


@app.get("/api/schedule")
def api_get_schedule():
    return {
        "poll_interval_minutes": load_poll_interval_minutes(settings.schedule_path),
        "paused": load_paused(settings.schedule_path),
    }


@app.post("/api/schedule")
def api_set_schedule(payload: dict):
    if "poll_interval_minutes" in payload:
        save_poll_interval_minutes(settings.schedule_path, int(payload["poll_interval_minutes"]))
    if "paused" in payload:
        save_paused(settings.schedule_path, bool(payload["paused"]))
    return {
        "poll_interval_minutes": load_poll_interval_minutes(settings.schedule_path),
        "paused": load_paused(settings.schedule_path),
    }


@app.post("/api/run-now")
def api_run_now():
    """Triggers an immediate hunt run in the background, bypassing the
    poll-interval gate - that's the whole point of a manual refresh. Runs
    off the request thread since a full hunt can take minutes; the
    dashboard polls /api/run-status for live progress instead of blocking
    on this response."""
    if progress_tracker.snapshot().get("running"):
        raise HTTPException(status_code=409, detail="A refresh is already running.")

    def _run():
        try:
            pipeline.run_hunt_checked(settings)
        except Exception:  # noqa: BLE001 - already recorded on progress_tracker by run_hunt_checked
            pass

    threading.Thread(target=_run, daemon=True).start()
    return {"started": True}


@app.get("/api/run-status")
def api_run_status():
    return progress_tracker.snapshot()


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
