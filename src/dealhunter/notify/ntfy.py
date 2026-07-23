"""ntfy.sh push notifications: deal alerts and separate error/health alerts
so a failed run is never silent."""
from __future__ import annotations

import requests

from config.settings import Settings
from dealhunter.models import Finding

_DISCLAIMER = (
    "AI-generated estimate, not a professional appraisal - do your own "
    "diligence before buying/reselling."
)

_SCORE_PRIORITY = {"green": "5", "yellow": "3", "red": "3"}
_SCORE_TAG = {"green": "moneybag", "yellow": "thinking", "red": "small_red_triangle_down"}


def _post(settings: Settings, *, title: str, message: str, priority: str, tags: str, click: str | None = None) -> None:
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": tags,
    }
    if click:
        headers["Click"] = click
    try:
        requests.post(
            f"{settings.ntfy_server}/{settings.ntfy_topic}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=10,
        )
    except requests.RequestException:
        # Notification delivery failing shouldn't crash the run - the health
        # report already records run-level errors for the next dashboard load.
        pass


def send_deal_alert(settings: Settings, finding: Finding) -> None:
    color = finding.score_color
    price_str = f"${finding.all_in_price:,.2f}" if finding.all_in_price else "price n/a"
    value_str = (
        f"${finding.analysis.estimated_value:,.2f}" if finding.analysis.estimated_value else "n/a"
    )
    discount_str = f"{finding.discount * 100:.0f}% under est. value" if finding.discount else ""
    message = (
        f"Deal score: {finding.deal_score}/100 ({color}) | Liquidity: {finding.liquidity.rating.value}\n"
        f"Price: {price_str} vs est. value {value_str} ({discount_str})\n"
        f"Condition: {finding.analysis.condition_summary}\n"
        f"Authenticity: {finding.analysis.authenticity_risk.value} - {finding.analysis.authenticity_notes}\n\n"
        f"{_DISCLAIMER}"
    )
    _post(
        settings,
        title=f"[{finding.deal_score}] {finding.listing.title[:80]}",
        message=message,
        priority=_SCORE_PRIORITY.get(color, "3"),
        tags=_SCORE_TAG.get(color, "mag"),
        click=finding.listing.url,
    )


def send_deal_digest(settings: Settings, findings: list[Finding]) -> None:
    """One notification for every qualifying finding from a single run - a
    poll that turns up several deals at once shouldn't mean several pings.
    Delegates to send_deal_alert's richer single-finding format when
    there's only one; otherwise sends one combined message."""
    if not findings:
        return
    if len(findings) == 1:
        send_deal_alert(settings, findings[0])
        return

    ranked = sorted(findings, key=lambda f: f.deal_score, reverse=True)
    best_color = ranked[0].score_color

    max_lines = 8
    lines = []
    for f in ranked[:max_lines]:
        price_str = f"${f.all_in_price:,.2f}" if f.all_in_price else "price n/a"
        lines.append(f"[{f.deal_score}] {f.listing.title[:70]} - {price_str}\n{f.listing.url}")
    remaining = len(ranked) - max_lines
    if remaining > 0:
        lines.append(f"...+{remaining} more - check the dashboard for the rest.")
    message = "\n\n".join(lines) + f"\n\n{_DISCLAIMER}"

    # No single Click target makes sense for a multi-item digest - each
    # listing's URL is inline in the message body instead, which ntfy
    # clients auto-linkify.
    _post(
        settings,
        title=f"{len(findings)} new deals found (top score {ranked[0].deal_score})",
        message=message,
        priority=_SCORE_PRIORITY.get(best_color, "3"),
        tags=_SCORE_TAG.get(best_color, "mag"),
    )


def send_error_alert(settings: Settings, message: str) -> None:
    _post(
        settings,
        title="Deal Hunter run failed",
        message=message,
        priority="4",
        tags="warning,rotating_light",
    )
