"""Step 7: Spotify API enrichment — popularity, followers, genres, top tracks.

Uses the batch /artists?ids=... endpoint: 1000 artists = 20 API calls (~2s total).
Top tracks fetched only for the top-100 artists by monthly listeners.
Requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in environment.
"""

from __future__ import annotations

import logging

from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_RATE_LIMIT
from utils import load_json, save_json, RateLimiter, load_checkpoint, save_checkpoint, clear_checkpoint

logger = logging.getLogger("artist_pipeline.step_spotify")

BATCH_SIZE = 50   # Spotify max per /artists call
TOP_TRACKS_N = 100  # only fetch top tracks for top-N artists by listeners


def _get_spotify_client():
    """Return an authenticated Spotify client, or None if credentials are missing."""
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        logger.warning("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET not set — skipping Spotify step")
        return None
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
        sp = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=SPOTIFY_CLIENT_ID,
                client_secret=SPOTIFY_CLIENT_SECRET,
            ),
            requests_timeout=15,
        )
        logger.info(f"Spotify client created (client_id={SPOTIFY_CLIENT_ID[:8]}...)")
        return sp
    except ImportError:
        logger.warning("spotipy not installed — skipping Spotify step")
        return None
    except Exception as e:
        logger.error(f"Spotify client init FAILED: {e}")
        return None


def _fetch_batch(sp, ids: list[str], limiter: RateLimiter) -> list[dict]:
    """Fetch a batch of up to 50 artists from Spotify API."""
    limiter.wait()
    try:
        result = sp.artists(ids)
        return result.get("artists") or []
    except Exception as e:
        logger.warning(f"Spotify batch fetch error: {e}")
        return []


def _fetch_top_tracks(sp, spotify_id: str, limiter: RateLimiter) -> list[dict]:
    """Fetch top tracks for one artist (market=US)."""
    limiter.wait()
    try:
        result = sp.artist_top_tracks(spotify_id, country="US")
        tracks = result.get("tracks") or []
        return [
            {"name": t["name"], "preview_url": t.get("preview_url")}
            for t in tracks[:5]
        ]
    except Exception as e:
        logger.warning(f"Spotify top tracks error for {spotify_id}: {e}")
        return []


def run() -> list[dict]:
    """Enrich artists with Spotify popularity, followers, genres, and top tracks."""
    logger.info("Step 7: Fetching Spotify enrichment data...")

    sp = _get_spotify_client()
    if not sp:
        save_json([], "spotify_data.json")
        return []

    seed = load_json("kworb_seed.json")
    limiter = RateLimiter(SPOTIFY_RATE_LIMIT)

    # Load partial results from previous run (checkpoint)
    done_ids = load_checkpoint("step_spotify")
    results: dict[str, dict] = {}

    # Re-load any previously saved results so we don't lose them on resume
    try:
        existing = load_json("spotify_data.json")
        for r in existing:
            results[r["spotify_id"]] = r
    except Exception:
        pass

    # Stale checkpoint guard: if checkpoint claims work is done but file is empty, reset
    if done_ids and not results:
        logger.warning("Stale Spotify checkpoint detected (checkpoint non-empty but data file empty) — resetting")
        clear_checkpoint("step_spotify")
        done_ids = set()

    # Split into batches
    all_ids = [a["spotify_id"] for a in seed if a["spotify_id"] not in done_ids]
    batches = [all_ids[i:i + BATCH_SIZE] for i in range(0, len(all_ids), BATCH_SIZE)]

    logger.info(f"Fetching {len(all_ids)} artists in {len(batches)} batches...")
    for batch_ids in batches:
        artists_data = _fetch_batch(sp, batch_ids, limiter)
        for artist in artists_data:
            if not artist:
                continue
            sid = artist["id"]
            results[sid] = {
                "spotify_id": sid,
                "popularity": artist.get("popularity"),
                "spotify_genres": artist.get("genres") or [],
                "followers": (artist.get("followers") or {}).get("total"),
                "image_url_spotify": (artist.get("images") or [{}])[0].get("url"),
                "top_tracks": [],
            }
            save_checkpoint("step_spotify", sid)

    # Fetch top tracks for top-N artists only
    top_ids = {a["spotify_id"] for a in seed[:TOP_TRACKS_N]}
    logger.info(f"Fetching top tracks for top {len(top_ids)} artists...")
    for sid in top_ids:
        if sid in results:
            results[sid]["top_tracks"] = _fetch_top_tracks(sp, sid, limiter)

    records = list(results.values())
    save_json(records, "spotify_data.json")
    clear_checkpoint("step_spotify")
    logger.info(f"Spotify enrichment complete: {len(records)} artists")
    return records


if __name__ == "__main__":
    from utils import setup_logging
    setup_logging()
    run()
