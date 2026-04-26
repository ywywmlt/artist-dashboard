"""Step 1: Scrape kworb.net top artists by Spotify monthly listeners."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup

from config import KWORB_URL, KWORB_PAGE_COUNT
from models import ArtistSeed
from utils import get_session, save_json, http_retry, append_listener_snapshot

logger = logging.getLogger("artist_pipeline.step1")


def _kworb_page_url(page: int) -> str:
    """Build the kworb URL for a given 1-indexed page (page 1 has no suffix)."""
    if page <= 1:
        return KWORB_URL
    return KWORB_URL.replace("listeners.html", f"listeners{page}.html")


@http_retry
def fetch_kworb_page(session, page: int = 1) -> str:
    """Fetch one kworb.net listeners page (1-indexed)."""
    resp = session.get(_kworb_page_url(page), timeout=30)
    resp.raise_for_status()
    # kworb serves UTF-8 but without a charset header — requests would otherwise
    # guess Latin-1 and mangle accented names (Tiësto → TiÃ«sto, Beyoncé → BeyoncÃ©).
    resp.encoding = "utf-8"
    return resp.text


def parse_listeners(text: str) -> int:
    """Parse listener count string like '102,345,678' to int."""
    return int(text.replace(",", "").strip())


def parse_change(text: str) -> Optional[int]:
    """Parse daily change like '+123,456' or '-45,678' to int."""
    text = text.strip()
    if not text or text == "--":
        return None
    return int(text.replace(",", "").replace("+", ""))


def extract_spotify_id(href: str) -> Optional[str]:
    """Extract Spotify ID from href like 'artist/0du5cEVh5yTK9QJze8zA0C_songs.html'."""
    match = re.search(r"artist/([A-Za-z0-9]+)_songs\.html", href)
    return match.group(1) if match else None


def _append_custom_artists(artists: list[dict], scraped_at: str) -> list[dict]:
    """Append user-added custom artists not already in the kworb seed."""
    try:
        from db import get_all_custom_artist_ids
        custom_ids = get_all_custom_artist_ids()
    except Exception as e:
        logger.debug(f"No custom artists loaded: {e}")
        return artists

    existing_ids = {a["spotify_id"] for a in artists}
    added = 0
    for sid, name in custom_ids:
        if sid in existing_ids:
            continue
        artists.append(ArtistSeed(
            rank=0,  # will be re-ranked in export step
            name=name or f"Custom ({sid[:8]}...)",
            spotify_id=sid,
            monthly_listeners=0,
            daily_change=0,
            scraped_at=scraped_at,
            source="custom",
        ).to_dict())
        added += 1
    if added:
        logger.info(f"Appended {added} custom artists to seed")
    return artists


def _parse_kworb_table(html: str, scraped_at: str) -> list[dict]:
    """Parse one kworb listeners page and return ArtistSeed dicts (no rank yet)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        raise RuntimeError("Could not find artist table on kworb.net")

    artists: list[dict] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells or len(cells) < 3:
            continue

        link = cells[1].find("a")
        if not link:
            continue

        spotify_id = extract_spotify_id(link.get("href", ""))
        if not spotify_id:
            continue

        artists.append(ArtistSeed(
            rank=0,  # re-ranked after merging all pages
            name=link.get_text(strip=True),
            spotify_id=spotify_id,
            monthly_listeners=parse_listeners(cells[2].get_text()),
            daily_change=parse_change(cells[3].get_text()) if len(cells) > 3 else None,
            peak_listeners=parse_listeners(cells[5].get_text()) if len(cells) > 5 else None,
            scraped_at=scraped_at,
        ).to_dict())
    return artists


def run() -> list[dict]:
    """Scrape kworb.net (configurable page depth) and return ArtistSeed dicts."""
    logger.info(f"Step 1: Scraping kworb.net top artists ({KWORB_PAGE_COUNT} page{'s' if KWORB_PAGE_COUNT != 1 else ''})...")
    session = get_session()
    scraped_at = datetime.utcnow().isoformat()

    artists: list[dict] = []
    seen_ids: set[str] = set()
    for page in range(1, KWORB_PAGE_COUNT + 1):
        html = fetch_kworb_page(session, page)
        page_artists = _parse_kworb_table(html, scraped_at)
        new_count = 0
        for a in page_artists:
            if a["spotify_id"] in seen_ids:
                continue
            seen_ids.add(a["spotify_id"])
            artists.append(a)
            new_count += 1
        logger.info(f"  page {page}: {len(page_artists)} rows, {new_count} new (total: {len(artists)})")

    # Re-rank by monthly listeners descending
    artists.sort(key=lambda a: a.get("monthly_listeners", 0), reverse=True)
    for i, a in enumerate(artists, start=1):
        a["rank"] = i

    logger.info(f"Scraped {len(artists)} unique artists from kworb.net")

    # Append user-added custom artists
    artists = _append_custom_artists(artists, scraped_at)

    save_json(artists, "kworb_seed.json")
    append_listener_snapshot(artists)
    return artists


if __name__ == "__main__":
    from utils import setup_logging
    setup_logging()
    run()
