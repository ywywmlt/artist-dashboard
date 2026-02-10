"""Step 2: Check touring activity via setlist.fm."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from config import (
    SETLISTFM_API_KEY, SETLISTFM_RATE_LIMIT,
    TOURING_MIN_EVENTS, TOURING_LOOKBACK_YEARS,
)
from models import TouringData
from utils import (
    get_session, load_json, save_json, http_retry, RateLimiter,
    load_checkpoint, save_checkpoint, clear_checkpoint,
)

logger = logging.getLogger("artist_pipeline.step2_touring")

STEP_NAME = "step2_touring"
SETLISTFM_BASE = "https://api.setlist.fm/rest/1.0"


@http_retry
def fetch_setlistfm_events(session, artist_name: str, page: int = 1) -> Optional[list]:
    """Fetch setlists from setlist.fm for an artist."""
    if not SETLISTFM_API_KEY:
        logger.error("SETLISTFM_API_KEY not set in .env")
        return None
    url = f"{SETLISTFM_BASE}/search/setlists"
    params = {"artistName": artist_name, "p": page}
    headers = {
        "x-api-key": SETLISTFM_API_KEY,
        "Accept": "application/json",
    }
    resp = session.get(url, params=params, headers=headers, timeout=15)
    if resp.status_code in (404, 403):
        return None
    resp.raise_for_status()
    data = resp.json()
    return data.get("setlist", [])


def analyze_setlists(setlists: list) -> TouringData:
    """Analyze setlist.fm data to determine touring status."""
    now = datetime.utcnow()
    cutoff = now - timedelta(days=TOURING_LOOKBACK_YEARS * 365)

    recent_count = 0
    last_event_date = None

    for setlist in setlists:
        event_date_str = setlist.get("eventDate", "")
        if not event_date_str:
            continue
        try:
            # setlist.fm uses DD-MM-YYYY format
            event_dt = datetime.strptime(event_date_str, "%d-%m-%Y")
        except (ValueError, TypeError):
            continue

        if event_dt >= cutoff:
            recent_count += 1
            iso_date = event_dt.strftime("%Y-%m-%d")
            if last_event_date is None or iso_date > last_event_date:
                last_event_date = iso_date

    is_touring = recent_count >= TOURING_MIN_EVENTS

    return TouringData(
        spotify_id="",
        is_touring=is_touring,
        recent_event_count=recent_count,
        upcoming_event_count=0,  # setlist.fm only has past events
        last_event_date=last_event_date,
        touring_source="setlistfm",
    )


def check_artist_touring(session, artist_name: str, limiter: RateLimiter) -> TouringData:
    """Check touring status for one artist via setlist.fm."""
    limiter.wait()
    setlists = fetch_setlistfm_events(session, artist_name)
    if setlists:
        return analyze_setlists(setlists)
    return TouringData(spotify_id="", is_touring=False, touring_source=None)


def run() -> list[dict]:
    """Check touring status for all seed artists."""
    logger.info("Step 2: Checking touring activity via setlist.fm...")
    seed = load_json("kworb_seed.json")
    session = get_session()
    limiter = RateLimiter(SETLISTFM_RATE_LIMIT)
    done = load_checkpoint(STEP_NAME)

    results = []
    try:
        results = load_json("touring_data.json")
        logger.info(f"Resuming from {len(results)} existing results")
    except FileNotFoundError:
        pass

    existing_ids = {r["spotify_id"] for r in results}
    total = len(seed)

    for i, artist in enumerate(seed):
        sid = artist["spotify_id"]
        name = artist["name"]
        if sid in done or sid in existing_ids:
            continue

        touring = check_artist_touring(session, name, limiter)
        touring.spotify_id = sid
        results.append(touring.to_dict())
        save_checkpoint(STEP_NAME, sid)

        if (i + 1) % 50 == 0:
            logger.info(f"  [{i + 1}/{total}] checked")
            save_json(results, "touring_data.json")

    save_json(results, "touring_data.json")
    clear_checkpoint(STEP_NAME)

    touring_count = sum(1 for r in results if r["is_touring"])
    logger.info(f"Touring check complete: {touring_count}/{len(results)} are actively touring")
    return results


if __name__ == "__main__":
    from utils import setup_logging
    setup_logging()
    run()
