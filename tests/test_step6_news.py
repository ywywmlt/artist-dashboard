"""Tests for pipeline/step6_news.py — artist matching, date parsing."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from pipeline.step6_news import _build_artist_lookup, _match_artists, _parse_published


# ── _build_artist_lookup ─────────────────────────────────────────────────────


class TestBuildArtistLookup:
    def test_case_insensitive_keys(self):
        artists = [
            {"name": "The Weeknd", "spotify_id": "abc"},
            {"name": "Taylor Swift", "spotify_id": "def"},
        ]
        lookup = _build_artist_lookup(artists)
        assert "the weeknd" in lookup
        assert "taylor swift" in lookup
        assert lookup["the weeknd"]["name"] == "The Weeknd"

    def test_preserves_original_name(self):
        artists = [{"name": "Bad Bunny", "spotify_id": "xyz"}]
        lookup = _build_artist_lookup(artists)
        assert lookup["bad bunny"]["name"] == "Bad Bunny"
        assert lookup["bad bunny"]["spotify_id"] == "xyz"


# ── _match_artists ───────────────────────────────────────────────────────────


class TestMatchArtists:
    def test_basic_match(self):
        lookup = {
            "taylor swift": {"name": "Taylor Swift", "spotify_id": "ts1"},
            "drake": {"name": "Drake", "spotify_id": "dk1"},
        }
        matches = _match_artists("Taylor Swift announces new album", lookup)
        assert len(matches) == 1
        assert matches[0]["name"] == "Taylor Swift"

    def test_multiple_matches(self):
        lookup = {
            "taylor swift": {"name": "Taylor Swift", "spotify_id": "ts1"},
            "drake": {"name": "Drake", "spotify_id": "dk1"},
        }
        matches = _match_artists("Taylor Swift and Drake collaborate on new track", lookup)
        assert len(matches) == 2
        names = {m["name"] for m in matches}
        assert names == {"Taylor Swift", "Drake"}

    def test_short_names_skipped(self):
        """Names with 3 or fewer characters should be skipped to avoid false positives."""
        lookup = {
            "sia": {"name": "SIA", "spotify_id": "sia1"},
            "taylor swift": {"name": "Taylor Swift", "spotify_id": "ts1"},
        }
        matches = _match_artists("SIA and Taylor Swift perform at Coachella", lookup)
        # "sia" is 3 chars → skipped
        assert len(matches) == 1
        assert matches[0]["name"] == "Taylor Swift"

    def test_no_matches(self):
        lookup = {
            "taylor swift": {"name": "Taylor Swift", "spotify_id": "ts1"},
        }
        matches = _match_artists("New album reviews for the week", lookup)
        assert matches == []


# ── _parse_published ─────────────────────────────────────────────────────────


class TestParsePublished:
    def test_published_parsed_struct_time(self):
        entry = {
            "published_parsed": time.struct_time((2025, 3, 15, 12, 0, 0, 5, 74, 0)),
        }
        result = _parse_published(entry)
        assert "2025-03-15" in result

    def test_published_string_rfc2822(self):
        entry = {
            "published": "Mon, 10 Mar 2025 08:30:00 GMT",
        }
        result = _parse_published(entry)
        assert "2025-03-10" in result

    def test_fallback_to_now(self):
        entry = {}
        result = _parse_published(entry)
        # Should return current time; just verify it's a valid ISO string
        dt = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert dt.year >= 2025
