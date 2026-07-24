"""
Health checks: credential validation before a run starts, and run-sanity
checks after (did sources actually return data, not just "ran without
throwing"). Both feed data/health.json, which the dashboard's status header
reads and which gates the ntfy error notification.
"""
from __future__ import annotations

import requests

from config.settings import Settings
from dealhunter.claude_client import make_client
from dealhunter.models import HealthReport, SourceHealth
from dealhunter.sources.base import SourceAdapter

# How many consecutive prior runs with zero new listings before we flag a
# source as suspicious (rather than just "quiet") in the health report.
_STALE_RUN_THRESHOLD = 5


def verify_credentials(settings: Settings, sources: list[SourceAdapter]) -> dict[str, str]:
    """Returns {name: "ok" | "error: <message>"} for every enabled source
    plus anthropic/ntfy. Does not raise - callers decide what to do with a
    failure (run_hunt.py aborts and sends an ntfy error alert)."""
    results: dict[str, str] = {}

    for source in sources:
        try:
            source.verify_credentials()
            results[source.name] = "ok"
        except Exception as exc:  # noqa: BLE001 - report and continue
            results[source.name] = f"error: {exc}"

    try:
        make_client(settings.anthropic_api_key).models.list(limit=1)
        results["anthropic"] = "ok"
    except Exception as exc:  # noqa: BLE001
        results["anthropic"] = f"error: {exc}"

    try:
        resp = requests.head(f"{settings.ntfy_server}/{settings.ntfy_topic}", timeout=10)
        results["ntfy"] = "ok" if resp.status_code < 500 else f"error: HTTP {resp.status_code}"
    except requests.RequestException as exc:
        results["ntfy"] = f"error: {exc}"

    return results


def assess_source_staleness(
    history: list[HealthReport], source_name: str, current_new: int
) -> bool:
    """True if this source has now gone _STALE_RUN_THRESHOLD+ consecutive
    runs finding zero new listings - a signal something may be silently
    broken (wrong subreddit name, expired search criteria, etc) even though
    no exception was raised."""
    if current_new > 0:
        return False
    recent = history[-_STALE_RUN_THRESHOLD:]
    if len(recent) < _STALE_RUN_THRESHOLD:
        return False
    return all(r.sources.get(source_name, SourceHealth()).new == 0 for r in recent)


def overall_status(sources: dict[str, SourceHealth]) -> str:
    statuses = [s.status for s in sources.values()]
    if "error" in statuses:
        return "error"
    if "warning" in statuses:
        return "warning"
    return "ok"
