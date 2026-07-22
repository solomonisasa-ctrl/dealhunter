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
from dealhunter import healthcheck, pipeline  # noqa: E402
from dealhunter.notify.ntfy import send_error_alert  # noqa: E402


def main() -> int:
    settings = get_settings()
    sources = pipeline.build_sources(settings)

    cred_results = healthcheck.verify_credentials(settings, list(sources.values()))
    print("Credential check:")
    for name, result in cred_results.items():
        print(f"  {name}: {result}")

    if cred_results.get("anthropic", "").startswith("error"):
        message = f"Anthropic API key invalid, aborting run: {cred_results['anthropic']}"
        print(message, file=sys.stderr)
        send_error_alert(settings, message)
        return 1

    source_errors = {
        name: result
        for name, result in cred_results.items()
        if name in sources and result.startswith("error")
    }

    report = pipeline.run_hunt(settings, source_health_errors=source_errors)

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
