"""Step 6: Scrape music news RSS feeds and match against tracked artists."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import quote

import feedparser

from config import NEWS_RSS_FEEDS, NEWS_GOOGLE_TOP_N, NEWS_RATE_LIMIT
from models import NewsAlert
from utils import get_session, save_json, load_json, http_retry, RateLimiter

logger = logging.getLogger("artist_pipeline.step6")

rate_limiter = RateLimiter(1.0 / NEWS_RATE_LIMIT)


def _parse_published(entry: dict) -> Optional[str]:
    """Parse published date from feedparser entry to ISO 8601."""
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                dt = datetime(*parsed[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except (TypeError, ValueError):
                pass
    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                return dt.isoformat()
            except (TypeError, ValueError):
                pass
    return datetime.now(timezone.utc).isoformat()


def _build_artist_lookup(artists: list[dict]) -> dict[str, dict]:
    """Build a case-insensitive name -> artist dict for matching.

    Keys are lowercase artist names. Values are dicts with name + spotify_id.
    Also creates entries for significant sub-names (e.g. "Bad Bunny" from
    "Bad Bunny" stays as-is, but multi-word names get the full match).
    """
    lookup = {}
    for a in artists:
        name = a["name"]
        lower = name.lower()
        lookup[lower] = {"name": name, "spotify_id": a["spotify_id"]}
    return lookup


def _match_artists(text: str, lookup: dict[str, dict]) -> list[dict]:
    """Find all tracked artists mentioned in text. Returns list of matches."""
    text_lower = text.lower()
    matches = []
    seen = set()
    for key, info in lookup.items():
        # Skip very short names (3 chars or less) — too many false positives
        if len(key) <= 3:
            continue
        if key in text_lower and info["spotify_id"] not in seen:
            matches.append(info)
            seen.add(info["spotify_id"])
    return matches


@http_retry
def _fetch_feed(session, url: str) -> str:
    """Fetch raw RSS feed XML."""
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def _scrape_publication_feeds(session, lookup: dict[str, dict]) -> list[dict]:
    """Scrape all publication RSS feeds and match articles to artists."""
    alerts = []
    for source, url in NEWS_RSS_FEEDS.items():
        rate_limiter.wait()
        logger.info(f"Fetching {source} RSS feed...")
        try:
            xml = _fetch_feed(session, url)
            feed = feedparser.parse(xml)
        except Exception as e:
            logger.warning(f"Failed to fetch {source}: {e}")
            continue

        count = 0
        for entry in feed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", entry.get("description", ""))
            search_text = f"{title} {summary}"
            matches = _match_artists(search_text, lookup)
            if not matches:
                continue

            alert = NewsAlert(
                title=title,
                url=entry.get("link", ""),
                source=source,
                published=_parse_published(entry),
                matched_artists=[m["name"] for m in matches],
                matched_spotify_ids=[m["spotify_id"] for m in matches],
            )
            alerts.append(alert.to_dict())
            count += 1

        logger.info(f"  {source}: {len(feed.entries)} items, {count} matched")
    return alerts


def _scrape_google_news(session, artists: list[dict]) -> list[dict]:
    """Fetch Google News RSS for top N artists."""
    alerts = []
    top_artists = artists[:NEWS_GOOGLE_TOP_N]
    for a in top_artists:
        rate_limiter.wait()
        name = a["name"]
        query = quote(f'"{name}" music')
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        logger.info(f"Google News: {name}")

        try:
            xml = _fetch_feed(session, url)
            feed = feedparser.parse(xml)
        except Exception as e:
            logger.warning(f"Failed Google News for {name}: {e}")
            continue

        for entry in feed.entries[:5]:  # limit to 5 per artist
            alert = NewsAlert(
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                source="Google News",
                published=_parse_published(entry),
                matched_artists=[name],
                matched_spotify_ids=[a["spotify_id"]],
            )
            alerts.append(alert.to_dict())

        logger.info(f"  {name}: {min(len(feed.entries), 5)} articles")
    return alerts


def run() -> list[dict]:
    """Scrape news feeds, match to artists, save to JSON."""
    logger.info("Step 6: Scraping news RSS feeds...")
    artists = load_json("kworb_seed.json")
    lookup = _build_artist_lookup(artists)
    session = get_session()
    fetched_at = datetime.now(timezone.utc).isoformat()

    # Scrape both sources
    pub_alerts = _scrape_publication_feeds(session, lookup)
    google_alerts = _scrape_google_news(session, artists)

    # Merge and deduplicate by URL
    all_alerts = pub_alerts + google_alerts
    seen_urls = set()
    deduped = []
    for alert in all_alerts:
        if alert["url"] not in seen_urls:
            seen_urls.add(alert["url"])
            alert["fetched_at"] = fetched_at
            deduped.append(alert)

    # Sort by published date (newest first)
    deduped.sort(key=lambda a: a.get("published", ""), reverse=True)

    logger.info(f"Total news alerts: {len(deduped)} (from {len(all_alerts)} before dedup)")
    save_json(deduped, "news_alerts.json")
    return deduped


if __name__ == "__main__":
    from utils import setup_logging
    setup_logging()
    run()
