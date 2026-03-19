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
    """Save data as JSON to the specified directory (atomic write)."""
    directory.mkdir(parents=True, exist_ok=True)
    filepath = directory / filename
    tmp = filepath.with_suffix(filepath.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(filepath)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    logger.info(f"Saved {filepath} ({len(data) if isinstance(data, list) else 'object'} records)")
    return filepath


def load_json(filename: str, directory: Path = RAW_DIR) -> Any:
    """Load JSON from the specified directory. Returns [] on missing/corrupt files."""
    filepath = directory / filename
    if not filepath.exists():
        logger.warning(f"File not found: {filepath}")
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load {filepath}: {e}")
        return []


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


# ── Listener history helpers ───────────────────────────────────────────────────

HISTORY_FILE = RAW_DIR / "listener_history.json"
HISTORY_MAX_ENTRIES = 365  # cap per artist


def append_listener_snapshot(artists: list[dict]) -> None:
    """Append today's listener count for each artist to the history file.

    Idempotent: if today's date is already the last entry for an artist, skip it.
    Caps each artist's history at HISTORY_MAX_ENTRIES entries (drops oldest).
    """
    from datetime import date as _date
    today = _date.today().isoformat()

    # Load existing history
    history: dict[str, list] = {}
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            history = {}

    updated = 0
    for a in artists:
        sid = a.get("spotify_id")
        ml = a.get("monthly_listeners")
        if not sid or ml is None:
            continue
        entries = history.setdefault(sid, [])
        # Idempotency: skip if last entry is already today
        if entries and entries[-1].get("date") == today:
            continue
        entries.append({
            "date": today,
            "listeners": int(ml),
            "daily_change": int(a.get("daily_change") or 0),
        })
        # Trim to cap
        if len(entries) > HISTORY_MAX_ENTRIES:
            history[sid] = entries[-HISTORY_MAX_ENTRIES:]
        updated += 1

    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_FILE.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        tmp.replace(HISTORY_FILE)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    logger.info(f"Listener history updated: {updated} artists appended (total tracked: {len(history)})")


def compute_momentum(history_entries: list[dict]) -> dict:
    """Compute 7-day and 30-day momentum % from a history list.

    Returns dict with keys: momentum_7d, momentum_30d (floats, percent change).
    Returns 0.0 if insufficient data.
    """
    if not history_entries:
        return {"momentum_7d": 0.0, "momentum_30d": 0.0}

    now_listeners = history_entries[-1]["listeners"]

    def _pct_change(days: int) -> float:
        if len(history_entries) < 2:
            return 0.0
        target_idx = max(0, len(history_entries) - 1 - days)
        past = history_entries[target_idx]["listeners"]
        if not past:
            return 0.0
        return round((now_listeners - past) / past * 100, 2)

    return {
        "momentum_7d": _pct_change(7),
        "momentum_30d": _pct_change(30),
    }
