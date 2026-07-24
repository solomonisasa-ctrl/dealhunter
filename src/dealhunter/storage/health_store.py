"""Last-run health history (data/health.json) - what the dashboard's status
header and the healthcheck module read/write."""
from __future__ import annotations

import json
from pathlib import Path

from dealhunter.atomic_write import atomic_write_text
from dealhunter.models import HealthReport

_MAX_HISTORY = 50


def load_health_history(path: Path) -> list[HealthReport]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [HealthReport.model_validate(item) for item in raw]


def latest_health(path: Path) -> HealthReport | None:
    history = load_health_history(path)
    return history[-1] if history else None


def append_health(path: Path, report: HealthReport) -> list[HealthReport]:
    history = load_health_history(path)
    history.append(report)
    history = history[-_MAX_HISTORY:]
    raw = [r.model_dump(mode="json") for r in history]
    atomic_write_text(path, json.dumps(raw, indent=2))
    return history
