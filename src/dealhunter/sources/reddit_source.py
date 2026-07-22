"""
Reddit source via PRAW (official API, read-only application auth - no
username/password needed since we only ever read public listings).
"""
from __future__ import annotations

import re
import time

import praw
import prawcore

from config.settings import Settings
from dealhunter.models import Listing, ListingStatus, WatchItem
from dealhunter.sources.base import SourceAdapter

_PRICE_RE = re.compile(r"\$\s?([\d][\d,]*(?:\.\d{1,2})?)")
_SOLD_MARKERS = ("sold", "complete")


def _extract_price(text: str) -> float | None:
    """Best-effort $-amount extraction from a listing title/body. Reddit
    listings are free text, not structured data, so this is a heuristic,
    not a guarantee - the dashboard always shows the original listing link
    so you can verify the real price."""
    matches = _PRICE_RE.findall(text or "")
    if not matches:
        return None
    amounts = [float(m.replace(",", "")) for m in matches]
    return max(amounts)


def _looks_sold(title: str, flair: str | None) -> bool:
    haystack = f"{title} {flair or ''}".lower()
    return any(marker in haystack for marker in _SOLD_MARKERS)


class RedditSource(SourceAdapter):
    name = "reddit"

    def __init__(self, settings: Settings):
        self._settings = settings
        self.reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )

    def verify_credentials(self) -> None:
        try:
            # Cheap read-only call that requires a valid app-only token.
            next(self.reddit.subreddit("announcements").hot(limit=1))
        except (prawcore.exceptions.ResponseException, prawcore.exceptions.OAuthException) as exc:
            raise RuntimeError(f"Reddit credentials invalid: {exc}") from exc

    def fetch_new(
        self, watch_item: WatchItem, category_def: dict, seen_ids: set[str]
    ) -> list[Listing]:
        subreddits = category_def.get("reddit", {}).get("subreddits", [])
        if not subreddits:
            return []
        cutoff = time.time() - watch_item.lookback_days * 86400
        listings: list[Listing] = []
        for sub_name in subreddits:
            try:
                subreddit = self.reddit.subreddit(sub_name)
                for submission in subreddit.new(limit=100):
                    if submission.created_utc < cutoff:
                        break  # .new() is reverse-chronological
                    listing_id = f"reddit:{submission.id}"
                    if listing_id in seen_ids:
                        continue
                    text = f"{submission.title}\n{submission.selftext or ''}"
                    status = (
                        ListingStatus.SOLD
                        if _looks_sold(submission.title, submission.link_flair_text)
                        else ListingStatus.ACTIVE
                    )
                    listings.append(
                        Listing(
                            id=listing_id,
                            source=self.name,
                            category=watch_item.category,
                            title=submission.title,
                            url=f"https://reddit.com{submission.permalink}",
                            price=_extract_price(text),
                            shipping_price=None,
                            image_url=_first_image_url(submission),
                            body=submission.selftext or "",
                            posted_at=submission.created_utc,
                            status=status,
                            raw={"subreddit": sub_name, "flair": submission.link_flair_text},
                        )
                    )
            except (prawcore.exceptions.ResponseException, prawcore.exceptions.PrawcoreException):
                # One bad subreddit shouldn't kill the whole run; let the
                # caller's healthcheck/pipeline record the overall fetch
                # count and decide if it's suspiciously low.
                continue
        return listings

    def check_sold(self, listing: Listing) -> bool:
        try:
            submission = self.reddit.submission(url=listing.url)
            return _looks_sold(submission.title, submission.link_flair_text)
        except prawcore.exceptions.PrawcoreException:
            return False

    def comparable_count(self, watch_item: WatchItem, category_def: dict) -> int:
        keywords = (watch_item.parsed_criteria or {}).get("search_keywords") or []
        if not keywords:
            return 0
        subreddits = "+".join(category_def.get("reddit", {}).get("subreddits", []))
        if not subreddits:
            return 0
        query = " OR ".join(keywords[:5])
        cutoff = time.time() - watch_item.lookback_days * 86400
        count = 0
        try:
            for submission in self.reddit.subreddit(subreddits).search(
                query, time_filter="month", limit=50
            ):
                if submission.created_utc >= cutoff:
                    count += 1
        except prawcore.exceptions.PrawcoreException:
            return count
        return count


def _first_image_url(submission) -> str | None:
    url = getattr(submission, "url", None)
    if url and any(url.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
        return url
    preview = getattr(submission, "preview", None)
    if preview:
        try:
            return preview["images"][0]["source"]["url"]
        except (KeyError, IndexError):
            return None
    return None
