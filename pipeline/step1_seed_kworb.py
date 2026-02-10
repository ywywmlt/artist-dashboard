"""Step 1: Scrape kworb.net top artists by Spotify monthly listeners."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup

from config import KWORB_URL
from models import ArtistSeed
from utils import get_session, save_json, http_retry

logger = logging.getLogger("artist_pipeline.step1")


@http_retry
def fetch_kworb_page(session) -> str:
    """Fetch the kworb.net listeners page."""
    resp = session.get(KWORB_URL, timeout=30)
    resp.raise_for_status()
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


def run() -> list[dict]:
    """Scrape kworb.net and return list of ArtistSeed dicts."""
    logger.info("Step 1: Scraping kworb.net top artists...")
    session = get_session()
    html = fetch_kworb_page(session)
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table")
    if not table:
        raise RuntimeError("Could not find artist table on kworb.net")

    artists = []
    rows = table.find_all("tr")
    scraped_at = datetime.utcnow().isoformat()

    for rank, row in enumerate(rows, start=0):
        cells = row.find_all("td")
        if not cells or len(cells) < 3:
            continue  # skip header or malformed rows

        # Columns: #, Artist, Listeners, Daily +/-, Peak, PkListeners
        link = cells[1].find("a")
        if not link:
            continue

        href = link.get("href", "")
        spotify_id = extract_spotify_id(href)
        if not spotify_id:
            continue

        name = link.get_text(strip=True)
        monthly_listeners = parse_listeners(cells[2].get_text())
        daily_change = parse_change(cells[3].get_text()) if len(cells) > 3 else None
        peak_listeners = parse_listeners(cells[5].get_text()) if len(cells) > 5 else None

        artist = ArtistSeed(
            rank=len(artists) + 1,
            name=name,
            spotify_id=spotify_id,
            monthly_listeners=monthly_listeners,
            daily_change=daily_change,
            peak_listeners=peak_listeners,
            scraped_at=scraped_at,
        )
        artists.append(artist.to_dict())

    logger.info(f"Scraped {len(artists)} artists from kworb.net")
    save_json(artists, "kworb_seed.json")
    return artists


if __name__ == "__main__":
    from utils import setup_logging
    setup_logging()
    run()
