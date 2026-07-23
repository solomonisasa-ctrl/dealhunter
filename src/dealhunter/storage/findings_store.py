"""
Findings history (data/findings.json) - the curated output the dashboard and
liquidity-comp counting both read from. A flat JSON array, newest last.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from dealhunter.models import Finding

# Hard cap so the findings file (committed to git by CI) doesn't grow forever.
_MAX_FINDINGS = 2000


def load_findings(path: Path) -> list[Finding]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Finding.model_validate(item) for item in raw]


def save_findings(path: Path, findings: list[Finding]) -> None:
    trimmed = findings[-_MAX_FINDINGS:]
    raw = [f.model_dump(mode="json") for f in trimmed]
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")


def append_finding(path: Path, finding: Finding) -> list[Finding]:
    findings = load_findings(path)
    findings.append(finding)
    save_findings(path, findings)
    return findings


def get_finding(path: Path, finding_id: str) -> Finding | None:
    for f in load_findings(path):
        if f.id == finding_id:
            return f
    return None


def recent_comparable_count(
    path: Path, watch_item_id: str, lookback_days: int
) -> int:
    """How many past findings for this watch item are within the lookback
    window - used as the algorithmic half of the liquidity signal."""
    cutoff = time.time() - lookback_days * 86400
    findings = load_findings(path)
    return sum(
        1
        for f in findings
        if f.watch_item_id == watch_item_id and f.created_at >= cutoff
    )


def recent_findings_for_item(
    path: Path, watch_item_id: str, within_days: int
) -> list[Finding]:
    """Recent findings for this watch item, excluding ones already marked
    as a duplicate of something else - dedup matching should always link
    back to the canonical original, not chain through a duplicate."""
    cutoff = time.time() - within_days * 86400
    findings = load_findings(path)
    return [
        f
        for f in findings
        if f.watch_item_id == watch_item_id
        and f.created_at >= cutoff
        and f.duplicate_of is None
    ]
