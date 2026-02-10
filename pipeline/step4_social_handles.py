"""Step 3: Get genres, social handles, country, and image from MusicBrainz."""

from __future__ import annotations

import logging
import re
from typing import Optional

import musicbrainzngs

from config import MUSICBRAINZ_APP_NAME, MUSICBRAINZ_APP_VERSION, MUSICBRAINZ_CONTACT
from config import MUSICBRAINZ_RATE_LIMIT
from models import MusicBrainzData
from utils import (
    load_json, save_json, RateLimiter,
    load_checkpoint, save_checkpoint, clear_checkpoint,
)

logger = logging.getLogger("artist_pipeline.step3_musicbrainz")

STEP_NAME = "step3_musicbrainz"


def init_musicbrainz():
    """Initialize MusicBrainz client with required User-Agent."""
    musicbrainzngs.set_useragent(
        MUSICBRAINZ_APP_NAME, MUSICBRAINZ_APP_VERSION, MUSICBRAINZ_CONTACT
    )


def extract_handle(url: str, platform: str) -> Optional[str]:
    """Extract a social media handle from a URL."""
    patterns = {
        "instagram": [
            r"instagram\.com/([A-Za-z0-9_.]+)",
        ],
        "youtube": [
            r"youtube\.com/(?:@|channel/|c/|user/)([A-Za-z0-9_\-@]+)",
        ],
        "tiktok": [
            r"tiktok\.com/@([A-Za-z0-9_.]+)",
        ],
        "twitter": [
            r"(?:twitter|x)\.com/([A-Za-z0-9_]+)",
        ],
    }
    for pattern in patterns.get(platform, []):
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            handle = match.group(1)
            if handle.lower() in ("intent", "share", "home", "explore", "search"):
                return None
            return handle
    return None


def classify_url(url: str) -> Optional[tuple]:
    """Classify a URL as a social platform and extract the handle."""
    url_lower = url.lower()
    for platform in ("instagram", "tiktok", "twitter"):
        if platform in url_lower or (platform == "twitter" and "x.com" in url_lower):
            handle = extract_handle(url, platform)
            if handle:
                return (platform, handle)
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        handle = extract_handle(url, "youtube")
        if handle:
            return ("youtube", handle)
    return None


def extract_image_url(url_rels: list) -> Optional[str]:
    """Try to extract an image URL from MusicBrainz URL relationships."""
    for rel in url_rels:
        rel_type = rel.get("type", "")
        url = rel.get("target", "")
        # MusicBrainz "image" relationship or wikimedia commons images
        if rel_type == "image" or "commons.wikimedia.org" in url:
            return url
    return None


def lookup_artist(name: str, limiter: RateLimiter) -> MusicBrainzData:
    """Look up an artist on MusicBrainz and extract genres, socials, country, image."""
    limiter.wait()
    try:
        result = musicbrainzngs.search_artists(artist=name, limit=5)
    except musicbrainzngs.WebServiceError as e:
        logger.warning(f"MusicBrainz search error for '{name}': {e}")
        return MusicBrainzData(spotify_id="")

    artists = result.get("artist-list", [])
    if not artists:
        return MusicBrainzData(spotify_id="")

    mb_artist = artists[0]
    mb_id = mb_artist.get("id")
    if not mb_id:
        return MusicBrainzData(spotify_id="")

    # Get country from area
    country = None
    area = mb_artist.get("area", {})
    if area:
        iso_codes = area.get("iso-3166-1-code-list")
        country = iso_codes[0] if iso_codes else area.get("name")

    # Get tags (genres) from search result
    genres = []
    tag_list = mb_artist.get("tag-list", [])
    for tag in tag_list:
        tag_name = tag.get("name", "")
        tag_count = int(tag.get("count", 0))
        if tag_name and tag_count > 0:
            genres.append(tag_name)

    # Get URL relationships (socials + image)
    limiter.wait()
    try:
        details = musicbrainzngs.get_artist_by_id(mb_id, includes=["url-rels", "tags"])
    except musicbrainzngs.WebServiceError as e:
        logger.warning(f"MusicBrainz detail error for '{name}': {e}")
        return MusicBrainzData(spotify_id="", genres=genres, country=country)

    # If the detail endpoint returned better tags, use those
    detail_tags = details.get("artist", {}).get("tag-list", [])
    if detail_tags:
        genres = [t["name"] for t in detail_tags if t.get("name") and int(t.get("count", 0)) > 0]

    url_rels = details.get("artist", {}).get("url-relation-list", [])

    # Extract socials
    socials = {"instagram": None, "youtube": None, "tiktok": None, "twitter": None}
    for rel in url_rels:
        url = rel.get("target", "")
        classified = classify_url(url)
        if classified:
            platform, handle = classified
            if socials[platform] is None:
                socials[platform] = handle

    # Extract image
    image_url = extract_image_url(url_rels)

    return MusicBrainzData(
        spotify_id="",
        genres=genres,
        country=country,
        image_url=image_url,
        **socials,
    )


def run() -> list[dict]:
    """Collect genres, social handles, country, and image for all seed artists."""
    logger.info("Step 3: Enriching via MusicBrainz (genres, socials, country, images)...")
    init_musicbrainz()
    seed = load_json("kworb_seed.json")
    limiter = RateLimiter(MUSICBRAINZ_RATE_LIMIT)
    done = load_checkpoint(STEP_NAME)

    results = []
    try:
        results = load_json("musicbrainz_data.json")
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

        data = lookup_artist(name, limiter)
        data.spotify_id = sid
        results.append(data.to_dict())
        save_checkpoint(STEP_NAME, sid)

        if (i + 1) % 50 == 0:
            logger.info(f"  [{i + 1}/{total}] looked up")
            save_json(results, "musicbrainz_data.json")

    save_json(results, "musicbrainz_data.json")
    clear_checkpoint(STEP_NAME)

    # Coverage stats
    n = len(results) or 1
    ig = sum(1 for r in results if r.get("instagram"))
    yt = sum(1 for r in results if r.get("youtube"))
    tt = sum(1 for r in results if r.get("tiktok"))
    tw = sum(1 for r in results if r.get("twitter"))
    gn = sum(1 for r in results if r.get("genres"))
    im = sum(1 for r in results if r.get("image_url"))
    logger.info(
        f"Coverage: Genres {gn}/{n} ({100*gn//n}%), "
        f"Images {im}/{n} ({100*im//n}%), "
        f"Instagram {ig}/{n} ({100*ig//n}%), "
        f"YouTube {yt}/{n} ({100*yt//n}%), "
        f"TikTok {tt}/{n} ({100*tt//n}%), "
        f"Twitter {tw}/{n} ({100*tw//n}%)"
    )
    return results


if __name__ == "__main__":
    from utils import setup_logging
    setup_logging()
    run()
