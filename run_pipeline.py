#!/usr/bin/env python3
"""CLI orchestrator — run the full artist scraping pipeline or specific steps."""

import argparse
import importlib
import sys
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils import setup_logging

logger = logging.getLogger("artist_pipeline")

STEPS = {
    1: ("Seed kworb.net", "pipeline.step1_seed_kworb"),
    2: ("Touring filter", "pipeline.step3_touring_filter"),
    3: ("MusicBrainz enrich", "pipeline.step4_social_handles"),
    4: ("Export CSV/JSON", "pipeline.step5_export"),
    5: ("News mentions", "pipeline.step6_news"),
    6: ("Ticketmaster events", "pipeline.step_ticketmaster"),
    7: ("Spotify enrichment", "pipeline.step_spotify"),
    8: ("Generate alerts", "pipeline.step_alerts"),
    9: ("Rostr signings + intel", "pipeline.step_rostr"),
}

# Steps that can run concurrently (both read kworb_seed.json, write separate outputs)
PARALLEL_GROUPS = {
    (2, 3): "Touring + MusicBrainz (parallel)",
}


def run_step(step_num: int) -> float:
    """Run a single pipeline step by number. Returns elapsed seconds."""
    name, module_path = STEPS[step_num]
    logger.info(f"\n{'='*60}")
    logger.info(f"STEP {step_num}/{len(STEPS)}: {name}")
    logger.info(f"{'='*60}")

    module = importlib.import_module(module_path)
    start = time.time()
    module.run()
    elapsed = time.time() - start
    logger.info(f"Step {step_num} completed in {elapsed:.1f}s")
    return elapsed


def main():
    parser = argparse.ArgumentParser(description="Artist Dashboard Scraping Pipeline")
    parser.add_argument(
        "--from", dest="from_step", type=int, default=1,
        help="Start from this step number (1-9). Default: 1",
    )
    parser.add_argument(
        "--to", dest="to_step", type=int, default=9,
        help="Stop after this step number (1-9). Default: 9",
    )
    parser.add_argument(
        "--step", type=int, default=None,
        help="Run only this specific step (1-9)",
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
    step_times = []

    step_num = start_step
    while step_num <= end_step:
        # Check if this step starts a parallel group
        parallel_key = None
        for group_steps in PARALLEL_GROUPS:
            if step_num == group_steps[0] and all(s <= end_step for s in group_steps):
                parallel_key = group_steps
                break

        if parallel_key:
            group_label = PARALLEL_GROUPS[parallel_key]
            logger.info(f"\n{'='*60}")
            logger.info(f"PARALLEL: {group_label}")
            logger.info(f"{'='*60}")
            group_start = time.time()
            with ThreadPoolExecutor(max_workers=len(parallel_key)) as executor:
                futures = {executor.submit(run_step, s): s for s in parallel_key}
                for future in as_completed(futures):
                    s = futures[future]
                    try:
                        elapsed = future.result()
                        step_times.append((s, elapsed))
                    except Exception as e:
                        logger.error(f"Step {s} failed: {e}")
                        raise
            logger.info(f"Parallel group completed in {time.time()-group_start:.1f}s")
            step_num = max(parallel_key) + 1
        else:
            elapsed = run_step(step_num)
            step_times.append((step_num, elapsed))
            step_num += 1

    total_elapsed = time.time() - total_start
    minutes = int(total_elapsed // 60)
    seconds = int(total_elapsed % 60)

    # Timing summary
    step_times.sort(key=lambda x: x[0])
    logger.info(f"\n{'─'*50}")
    logger.info("TIMING SUMMARY")
    logger.info(f"{'─'*50}")
    for s, elapsed in step_times:
        logger.info(f"  Step {s:>2}: {elapsed:>7.1f}s  {STEPS[s][0]}")
    logger.info(f"{'─'*50}")
    logger.info(f"  TOTAL:  {total_elapsed:>7.1f}s  ({minutes}m {seconds}s)")
    logger.info(f"{'─'*50}")


if __name__ == "__main__":
    main()
