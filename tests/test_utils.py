"""Tests for utils.py — JSON I/O, RateLimiter, checkpointing, momentum."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from utils import (
    save_json,
    load_json,
    RateLimiter,
    load_checkpoint,
    save_checkpoint,
    clear_checkpoint,
    compute_momentum,
    append_listener_snapshot,
)


# ── save_json / load_json ────────────────────────────────────────────────────


class TestJsonIO:
    def test_roundtrip(self, tmp_data_dir):
        data = [{"name": "Alice", "value": 42}]
        save_json(data, "test.json", directory=tmp_data_dir)
        loaded = load_json("test.json", directory=tmp_data_dir)
        assert loaded == data

    def test_load_missing_returns_empty_list(self, tmp_data_dir):
        result = load_json("nonexistent.json", directory=tmp_data_dir)
        assert result == []

    def test_load_corrupt_returns_empty_list(self, tmp_data_dir):
        bad_file = tmp_data_dir / "corrupt.json"
        bad_file.write_text("{invalid json!!!", encoding="utf-8")
        result = load_json("corrupt.json", directory=tmp_data_dir)
        assert result == []

    def test_save_atomic_no_leftover_tmp(self, tmp_data_dir):
        save_json([1, 2, 3], "atomic.json", directory=tmp_data_dir)
        # The .tmp file should not exist after a successful write
        tmp_file = tmp_data_dir / "atomic.json.tmp"
        assert not tmp_file.exists()
        assert (tmp_data_dir / "atomic.json").exists()


# ── RateLimiter ──────────────────────────────────────────────────────────────


class TestRateLimiter:
    def test_enforces_minimum_delay(self):
        limiter = RateLimiter(requests_per_second=5.0)  # min_interval = 0.2s
        limiter.wait()
        t0 = time.monotonic()
        limiter.wait()
        elapsed = time.monotonic() - t0
        # Should have waited at least ~0.15s (allow small tolerance)
        assert elapsed >= 0.15, f"Expected >= 0.15s delay, got {elapsed:.3f}s"


# ── Checkpoint lifecycle ─────────────────────────────────────────────────────


class TestCheckpoint:
    def test_save_load_clear(self, tmp_data_dir, monkeypatch):
        # Redirect RAW_DIR to tmp_data_dir
        import utils
        monkeypatch.setattr(utils, "RAW_DIR", tmp_data_dir)

        step = "test_step"
        # Initially empty
        assert load_checkpoint(step) == set()

        # Save a couple of IDs
        save_checkpoint(step, "id_1")
        save_checkpoint(step, "id_2")
        loaded = load_checkpoint(step)
        assert "id_1" in loaded
        assert "id_2" in loaded

        # Clear
        clear_checkpoint(step)
        assert load_checkpoint(step) == set()


# ── compute_momentum ─────────────────────────────────────────────────────────


class TestComputeMomentum:
    def test_empty_history(self):
        result = compute_momentum([])
        assert result == {"momentum_7d": 0.0, "momentum_30d": 0.0}

    def test_insufficient_data(self):
        result = compute_momentum([{"date": "2025-01-01", "listeners": 1000}])
        assert result["momentum_7d"] == 0.0
        assert result["momentum_30d"] == 0.0

    def test_7d_momentum(self):
        entries = []
        for i in range(10):
            entries.append({"date": f"2025-01-{10+i:02d}", "listeners": 100_000 + i * 1000})
        result = compute_momentum(entries)
        # 7d: compare index 9 vs index 2 → (109000 - 102000) / 102000 * 100
        expected_7d = round((109_000 - 102_000) / 102_000 * 100, 2)
        assert result["momentum_7d"] == expected_7d

    def test_30d_momentum(self):
        entries = []
        for i in range(35):
            entries.append({"date": f"2025-01-{i+1:02d}", "listeners": 100_000 + i * 500})
        result = compute_momentum(entries)
        # 30d: compare index 34 vs index 4 → (117000 - 102000) / 102000 * 100
        expected_30d = round((117_000 - 102_000) / 102_000 * 100, 2)
        assert result["momentum_30d"] == expected_30d


# ── append_listener_snapshot ─────────────────────────────────────────────────


class TestAppendListenerSnapshot:
    def test_idempotency(self, tmp_data_dir, monkeypatch):
        import utils
        history_file = tmp_data_dir / "listener_history.json"
        monkeypatch.setattr(utils, "HISTORY_FILE", history_file)

        artists = [
            {"spotify_id": "abc123", "monthly_listeners": 5_000_000, "daily_change": 100},
        ]

        # First call writes one entry
        append_listener_snapshot(artists)
        data = json.loads(history_file.read_text())
        assert len(data["abc123"]) == 1

        # Second call with same date should be idempotent
        append_listener_snapshot(artists)
        data = json.loads(history_file.read_text())
        assert len(data["abc123"]) == 1  # still 1
