#!/usr/bin/env python3
# Railway cron: Add a cron trigger hitting POST /api/events/refresh with X-Cron-Secret header
# Recommended schedule: 0 6 * * * (daily at 6 AM UTC)
"""Daily pipeline cron job — runs automatically on Railway schedule.

Executes the full daily refresh:
  1. Seed kworb.net (+ append listener history snapshot)
  2. Touring filter (setlist.fm) — slow (~27 min @ 7,500 artists)
  3. MusicBrainz enrichment (genres, country, socials) — slow (~51 min @ 7,500)
  7. Spotify enrichment
  5. News mentions
  6. Ticketmaster events
  9. Rostr signings + intel
  8. Generate alerts
  4. Export CSV/JSON

Total runtime ~85 min on the 7,500-artist seed. Steps 2 and 3 used to be
manual-only (faster cron) but were folded in once the dataset expanded so
new artists get touring/region data without operator intervention.
"""

import importlib
import logging
import sys
import time
from datetime import datetime, timezone

from utils import setup_logging

setup_logging(verbose=False)
logger = logging.getLogger("cron_pipeline")

STEPS = [
    ("kworb rankings + history snapshot", "pipeline.step1_seed_kworb"),
    ("touring filter (setlist.fm)",       "pipeline.step3_touring_filter"),
    ("MusicBrainz enrichment",            "pipeline.step4_social_handles"),
    ("Spotify enrichment",                "pipeline.step_spotify"),
    ("news articles",                     "pipeline.step6_news"),
    ("Ticketmaster events",               "pipeline.step_ticketmaster"),
    ("Rostr signings + intel",            "pipeline.step_rostr"),
    ("generate alerts",                   "pipeline.step_alerts"),
    ("export CSV/JSON",                   "pipeline.step5_export"),
]


def run():
    started = datetime.now(timezone.utc)
    logger.info(f"=== Daily pipeline cron started at {started.isoformat()} ===")
    total_start = time.time()
    failed = []

    for label, module_path in STEPS:
        logger.info(f"--- {label} ---")
        t0 = time.time()
        try:
            mod = importlib.import_module(module_path)
            if module_path == "pipeline.step_ticketmaster":
                # Pass a no-op progress callback
                mod.run(progress_callback=lambda done, total, msg: None)
            else:
                mod.run()
            logger.info(f"    OK ({time.time()-t0:.1f}s)")
        except Exception as e:
            logger.error(f"    FAILED: {e}")
            failed.append((label, str(e)))
            # Continue — don't let one step abort the rest

    elapsed = time.time() - total_start
    logger.info(f"=== Cron complete in {elapsed/60:.1f}min — {len(failed)} failure(s) ===")
    if failed:
        for label, err in failed:
            logger.error(f"  - {label}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    run()
