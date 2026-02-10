"""Step 5: Merge all data and export to CSV + JSON."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

import pandas as pd

from config import OUTPUT_DIR, MANUAL_DIR
from models import ArtistEnriched
from utils import load_json

logger = logging.getLogger("artist_pipeline.step5")

EXPORT_COLUMNS = [
    "rank", "name", "spotify_id", "spotify_url", "monthly_listeners",
    "genres", "country", "image_url",
    "instagram", "youtube", "tiktok", "twitter",
    "is_touring", "recent_event_count", "upcoming_event_count",
    "last_event_date", "next_event_date", "touring_source", "scraped_at",
]


def load_overrides() -> dict[str, dict]:
    """Load manual social overrides from CSV if it exists."""
    override_file = MANUAL_DIR / "social_overrides.csv"
    if not override_file.exists():
        return {}

    overrides = {}
    with open(override_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = row.get("spotify_id", "").strip()
            if sid:
                overrides[sid] = {k: v.strip() for k, v in row.items() if v.strip() and k != "spotify_id"}
    logger.info(f"Loaded {len(overrides)} manual overrides")
    return overrides


def merge_all() -> list[dict]:
    """Merge seed, touring, and MusicBrainz data on spotify_id."""
    seed = load_json("kworb_seed.json")
    touring = {r["spotify_id"]: r for r in load_json("touring_data.json")}
    mb = {r["spotify_id"]: r for r in load_json("musicbrainz_data.json")}
    overrides = load_overrides()

    merged = []
    for artist in seed:
        sid = artist["spotify_id"]
        tr = touring.get(sid, {})
        m = mb.get(sid, {})
        ov = overrides.get(sid, {})

        genres = m.get("genres", [])
        genres_str = ", ".join(genres) if isinstance(genres, list) else str(genres)

        record = ArtistEnriched(
            rank=artist["rank"],
            name=artist["name"],
            spotify_id=sid,
            spotify_url=f"https://open.spotify.com/artist/{sid}",
            monthly_listeners=artist["monthly_listeners"],
            genres=genres_str,
            country=ov.get("country") or m.get("country"),
            image_url=m.get("image_url"),
            instagram=ov.get("instagram") or m.get("instagram"),
            youtube=ov.get("youtube") or m.get("youtube"),
            tiktok=ov.get("tiktok") or m.get("tiktok"),
            twitter=ov.get("twitter") or m.get("twitter"),
            is_touring=tr.get("is_touring", False),
            recent_event_count=tr.get("recent_event_count", 0),
            upcoming_event_count=tr.get("upcoming_event_count", 0),
            last_event_date=tr.get("last_event_date"),
            next_event_date=tr.get("next_event_date"),
            touring_source=tr.get("touring_source"),
            scraped_at=artist.get("scraped_at", ""),
        )
        merged.append(record.to_dict())

    # Sort by monthly_listeners descending, re-rank
    merged.sort(key=lambda r: r["monthly_listeners"], reverse=True)
    for i, record in enumerate(merged):
        record["rank"] = i + 1

    return merged


def export_csv(records: list[dict], path: Path) -> None:
    """Export records to CSV."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    logger.info(f"Exported CSV: {path} ({len(records)} rows)")


def export_json(records: list[dict], path: Path) -> None:
    """Export records to JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    logger.info(f"Exported JSON: {path} ({len(records)} records)")


def print_summary(records: list[dict]) -> None:
    """Print a summary of the exported data."""
    n = len(records)
    touring = sum(1 for r in records if r["is_touring"])
    ig = sum(1 for r in records if r.get("instagram"))
    yt = sum(1 for r in records if r.get("youtube"))
    tt = sum(1 for r in records if r.get("tiktok"))
    tw = sum(1 for r in records if r.get("twitter"))
    genres_set = set()
    for r in records:
        if r.get("genres"):
            for g in r["genres"].split(", "):
                genres_set.add(g.strip())
    countries = set(r.get("country") for r in records if r.get("country"))

    logger.info("=" * 60)
    logger.info(f"EXPORT SUMMARY")
    logger.info(f"  Total artists:     {n}")
    logger.info(f"  Actively touring:  {touring} ({100*touring//max(n,1)}%)")
    logger.info(f"  Unique genres:     {len(genres_set)}")
    logger.info(f"  Countries:         {len(countries)}")
    logger.info(f"  Instagram handles: {ig} ({100*ig//max(n,1)}%)")
    logger.info(f"  YouTube channels:  {yt} ({100*yt//max(n,1)}%)")
    logger.info(f"  TikTok handles:    {tt} ({100*tt//max(n,1)}%)")
    logger.info(f"  Twitter handles:   {tw} ({100*tw//max(n,1)}%)")
    logger.info("=" * 60)


def run() -> list[dict]:
    """Merge all data and export to CSV + JSON."""
    logger.info("Step 5: Merging and exporting...")
    records = merge_all()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    export_csv(records, OUTPUT_DIR / "artists_master.csv")
    export_json(records, OUTPUT_DIR / "artists_master.json")
    print_summary(records)

    return records


if __name__ == "__main__":
    from utils import setup_logging
    setup_logging()
    run()
