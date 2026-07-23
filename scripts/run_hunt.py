#!/usr/bin/env python
"""
CLI entrypoint used by GitHub Actions (and for local testing) to run one
full hunt across the watchlist. See README.md for setup + local testing
instructions.

Usage:
    python scripts/run_hunt.py
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from config.settings import get_settings  # noqa: E402
from dealhunter import pipeline  # noqa: E402
from dealhunter.notify.ntfy import send_error_alert  # noqa: E402


def main() -> int:
    settings = get_settings()

    if pipeline.is_paused(settings):
        print("Hunting is paused (config/schedule.yaml: paused: true) - skipping.")
        return 0

    if not pipeline.due_for_run(settings):
        print("Not due yet per config/schedule.yaml poll_interval_minutes - skipping this trigger.")
        return 0

    try:
        cred_results, report = pipeline.run_hunt_checked(settings)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        send_error_alert(settings, str(exc))
        return 1

    print("Credential check:")
    for name, result in cred_results.items():
        print(f"  {name}: {result}")

    print(f"\nRun finished in {report.duration_seconds:.1f}s - status: {report.overall_status}")
    print(f"Findings recorded this run: {report.findings_count}")
    for name, health in report.sources.items():
        print(f"  {name}: fetched={health.fetched} new={health.new} status={health.status}")
        for err in health.errors:
            print(f"    ! {err}")

    return 0 if report.overall_status != "error" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - last-resort net so failures are never silent
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        try:
            settings = get_settings()
            send_error_alert(settings, f"Unhandled exception during hunt run:\n{tb[-1500:]}")
        except Exception:
            pass
        sys.exit(1)
