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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from config.settings import get_settings  # noqa: E402
from dealhunter.models import WatchItem  # noqa: E402
from dealhunter.pipeline import load_categories  # noqa: E402
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
def api_findings(watch_item_id: str | None = None, sort: str = "date"):
    findings = findings_store.load_findings(settings.findings_path)
    if watch_item_id:
        findings = [f for f in findings if f.watch_item_id == watch_item_id]
    if sort == "score":
        findings.sort(key=lambda f: f.deal_score, reverse=True)
    else:
        findings.sort(key=lambda f: f.created_at, reverse=True)
    return [f.model_dump(mode="json") for f in findings]


@app.get("/api/findings/{finding_id:path}")
def api_finding_detail(finding_id: str):
    finding = findings_store.get_finding(settings.findings_path, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding.model_dump(mode="json")


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


@app.get("/api/categories")
def api_categories():
    return load_categories(settings)


@app.get("/api/health")
def api_health():
    history = health_store.load_health_history(settings.health_path)
    latest = history[-1].model_dump(mode="json") if history else None
    return {"latest": latest, "unpushed_watchlist_changes": _has_unpushed_watchlist_changes()}


def _has_unpushed_watchlist_changes() -> bool:
    """Read-only `git status` check - never auto-commits or pushes. Used to
    show a reminder banner so scheduled runs actually pick up your edits."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", "config/watchlist.yaml"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
