"""Tests for pipeline/step1_seed_kworb.py — parsing functions."""

from __future__ import annotations

import pytest

from pipeline.step1_seed_kworb import parse_listeners, parse_change, extract_spotify_id


# ── parse_listeners ──────────────────────────────────────────────────────────


class TestParseListeners:
    def test_normal(self):
        assert parse_listeners("102,345,678") == 102_345_678

    def test_no_commas(self):
        assert parse_listeners("12345") == 12345

    def test_whitespace(self):
        assert parse_listeners("  50,000  ") == 50_000


# ── parse_change ─────────────────────────────────────────────────────────────


class TestParseChange:
    def test_positive(self):
        assert parse_change("+123,456") == 123_456

    def test_negative(self):
        assert parse_change("-45,678") == -45_678

    def test_dash_returns_none(self):
        assert parse_change("--") is None

    def test_empty_returns_none(self):
        assert parse_change("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_change("   ") is None


# ── extract_spotify_id ───────────────────────────────────────────────────────


class TestExtractSpotifyId:
    def test_valid_href(self):
        href = "artist/0du5cEVh5yTK9QJze8zA0C_songs.html"
        assert extract_spotify_id(href) == "0du5cEVh5yTK9QJze8zA0C"

    def test_no_match(self):
        assert extract_spotify_id("some/random/path.html") is None

    def test_partial_match(self):
        # Must have _songs.html suffix
        assert extract_spotify_id("artist/0du5cEVh5yTK9QJze8zA0C.html") is None
