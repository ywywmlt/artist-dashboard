"""Shared helpers — rate limiting, retries, logging, file I/O."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from config import RAW_DIR, USER_AGENT

logger = logging.getLogger("artist_pipeline")


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the pipeline."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def get_session() -> requests.Session:
    """Create a requests session with standard headers."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def save_json(data: Any, filename: str, directory: Path = RAW_DIR) -> Path:
    """Save data as JSON to the specified directory."""
    directory.mkdir(parents=True, exist_ok=True)
    filepath = directory / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved {filepath} ({len(data) if isinstance(data, list) else 'object'} records)")
    return filepath


def load_json(filename: str, directory: Path = RAW_DIR) -> Any:
    """Load JSON from the specified directory."""
    filepath = directory / filename
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


class RateLimiter:
    """Simple rate limiter that enforces a minimum delay between calls."""

    def __init__(self, requests_per_second: float):
        self.min_interval = 1.0 / requests_per_second
        self.last_call = 0.0

    def wait(self) -> None:
        elapsed = time.time() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.time()


# Retry decorator for HTTP calls
http_retry = retry(
    retry=retry_if_exception_type((requests.exceptions.RequestException, requests.exceptions.Timeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)


def load_checkpoint(step_name: str) -> set[str]:
    """Load set of already-processed spotify_ids for a step."""
    checkpoint_file = RAW_DIR / f".checkpoint_{step_name}"
    if checkpoint_file.exists():
        return set(checkpoint_file.read_text().strip().split("\n"))
    return set()


def save_checkpoint(step_name: str, spotify_id: str) -> None:
    """Append a processed spotify_id to the checkpoint file."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_file = RAW_DIR / f".checkpoint_{step_name}"
    with open(checkpoint_file, "a") as f:
        f.write(spotify_id + "\n")


def clear_checkpoint(step_name: str) -> None:
    """Remove checkpoint file for a step."""
    checkpoint_file = RAW_DIR / f".checkpoint_{step_name}"
    if checkpoint_file.exists():
        checkpoint_file.unlink()
