#!/usr/bin/env python3
"""Daily pipeline cron job — runs automatically on Railway schedule.

Executes the quick refresh sequence:
  1. Seed kworb.net (+ append listener history snapshot)
  7. Spotify enrichment
  5. News mentions
  6. Ticketmaster events
  8. Generate alerts
  4. Export CSV/JSON

Steps 2 (touring) and 3 (MusicBrainz) are slow (~25min total) and run
separately on demand via the full pipeline CLI. This cron keeps daily
listener history, Spotify data, news, and alerts up to date.
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
