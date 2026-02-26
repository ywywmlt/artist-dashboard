#!/usr/bin/env python3
"""CLI orchestrator — run the full artist scraping pipeline or specific steps."""

import argparse
import sys
import time
import logging

from utils import setup_logging

logger = logging.getLogger("artist_pipeline")

STEPS = {
    1: ("Seed kworb.net", "pipeline.step1_seed_kworb"),
    2: ("Touring filter", "pipeline.step3_touring_filter"),
    3: ("MusicBrainz enrich", "pipeline.step4_social_handles"),
    4: ("Export CSV/JSON", "pipeline.step5_export"),
    5: ("News mentions", "pipeline.step6_news"),
    6: ("Ticketmaster events", "pipeline.step_ticketmaster"),
}


def run_step(step_num: int) -> None:
    """Run a single pipeline step by number."""
    name, module_path = STEPS[step_num]
    logger.info(f"\n{'='*60}")
    logger.info(f"STEP {step_num}/{len(STEPS)}: {name}")
    logger.info(f"{'='*60}")

    import importlib
    module = importlib.import_module(module_path)
    start = time.time()
    module.run()
    elapsed = time.time() - start
    logger.info(f"Step {step_num} completed in {elapsed:.1f}s")


def main():
    parser = argparse.ArgumentParser(description="Artist Dashboard Scraping Pipeline")
    parser.add_argument(
        "--from", dest="from_step", type=int, default=1,
        help="Start from this step number (1-5). Default: 1",
    )
    parser.add_argument(
        "--to", dest="to_step", type=int, default=5,
        help="Stop after this step number (1-5). Default: 5",
    )
    parser.add_argument(
        "--step", type=int, default=None,
        help="Run only this specific step (1-5)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()
    setup_logging(verbose=args.verbose)

    if args.step:
        if args.step not in STEPS:
            logger.error(f"Invalid step: {args.step}. Must be 1-{len(STEPS)}.")
            sys.exit(1)
        run_step(args.step)
        return

    start_step = args.from_step
    end_step = args.to_step

    if start_step < 1 or end_step > len(STEPS) or start_step > end_step:
        logger.error(f"Invalid range: --from {start_step} --to {end_step}")
        sys.exit(1)

    logger.info(f"Running pipeline steps {start_step} through {end_step}")
    total_start = time.time()

    for step_num in range(start_step, end_step + 1):
        run_step(step_num)

    total_elapsed = time.time() - total_start
    minutes = int(total_elapsed // 60)
    seconds = int(total_elapsed % 60)
    logger.info(f"\nPipeline complete! Total time: {minutes}m {seconds}s")


if __name__ == "__main__":
    main()
