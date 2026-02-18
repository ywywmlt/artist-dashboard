"""Pipeline step: Fetch upcoming events from Ticketmaster for all artists."""

import logging
from datetime import datetime

from config import TICKETMASTER_API_KEY, RAW_DIR
from utils import get_session, load_json, save_json, load_checkpoint, save_checkpoint, clear_checkpoint, RateLimiter

logger = logging.getLogger(__name__)

TICKETMASTER_BASE = "https://app.ticketmaster.com/discovery/v2/events.json"
_rate_limiter = RateLimiter(2)  # 2 req/sec — conservative against 5000/day quota
CHECKPOINT_NAME = "step_ticketmaster"


def _fetch_artist_events(session, artist_name, spotify_id, size=10):
    _rate_limiter.wait()
    params = {
        "apikey": TICKETMASTER_API_KEY,
        "keyword": artist_name,
        "classificationName": "music",
        "size": size,
        "sort": "date,asc",
    }
    try:
        resp = session.get(TICKETMASTER_BASE, params=params, timeout=10)
        resp.raise_for_status()
        raw_events = resp.json().get("_embedded", {}).get("events", [])
        today = datetime.utcnow().date().isoformat()
        results = []
        for ev in raw_events:
            date = ev.get("dates", {}).get("start", {}).get("localDate")
            if not date or date < today:
                continue
            venue = (ev.get("_embedded", {}).get("venues") or [{}])[0]
            price_ranges = ev.get("priceRanges") or [{}]
            results.append({
                "id": ev.get("id"),
                "spotifyId": spotify_id,
                "artistName": artist_name,
                "eventName": ev.get("name"),
                "date": date,
                "dateTime": ev.get("dates", {}).get("start", {}).get("dateTime"),
                "venueName": venue.get("name", "TBD"),
                "city": venue.get("city", {}).get("name", ""),
                "country": venue.get("country", {}).get("name", ""),
                "priceMin": price_ranges[0].get("min"),
                "priceMax": price_ranges[0].get("max"),
                "url": ev.get("url", "#"),
            })
        return results
    except Exception as e:
        logger.warning(f"Ticketmaster error for {artist_name}: {e}")
        return []


def run(progress_callback=None, verbose=False):
    """
    Fetch upcoming Ticketmaster events for all artists in kworb_seed.json.
    Saves results to data/raw/ticketmaster_events.json.
    Supports checkpointing — safe to resume if interrupted.

    progress_callback(done, total, message) — optional, called every 25 artists.
    """
    session = get_session()

    artists = load_json("kworb_seed.json", RAW_DIR)
    if not artists:
        logger.error("kworb_seed.json not found. Run step 1 first.")
        return []

    total = len(artists)
    logger.info(f"Fetching Ticketmaster events for {total} artists at 2 req/sec...")

    done_ids = load_checkpoint(CHECKPOINT_NAME)
    all_events = []

    if done_ids:
        try:
            all_events = load_json("ticketmaster_events.json", RAW_DIR) or []
        except Exception:
            all_events = []
        logger.info(f"Resuming: {len(done_ids)} artists already done, {len(all_events)} events cached")

    processed = len(done_ids)

    for artist in artists:
        spotify_id = artist.get("spotify_id", "")
        name = artist.get("name", "")

        if spotify_id in done_ids:
            continue

        events = _fetch_artist_events(session, name, spotify_id)
        all_events.extend(events)
        save_checkpoint(CHECKPOINT_NAME, spotify_id)
        processed += 1

        if processed % 25 == 0:
            save_json(all_events, "ticketmaster_events.json", RAW_DIR)
            msg = f"{processed}/{total} artists fetched — {len(all_events)} events so far"
            logger.info(msg)
            if progress_callback:
                progress_callback(processed, total, msg)

    # Final dedupe by event id, sort by date
    seen = set()
    unique = []
    for ev in all_events:
        eid = ev.get("id")
        if eid and eid not in seen:
            seen.add(eid)
            unique.append(ev)
    unique.sort(key=lambda e: e.get("date") or "")

    save_json(unique, "ticketmaster_events.json", RAW_DIR)
    clear_checkpoint(CHECKPOINT_NAME)

    summary = f"Done — {len(unique)} upcoming events across {total} artists"
    logger.info(summary)
    if progress_callback:
        progress_callback(total, total, summary)

    return unique
