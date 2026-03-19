"""Tests for pipeline/step_alerts.py — listener and news alert generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest

from pipeline.step_alerts import (
    generate_listener_alerts,
    generate_news_alerts,
    NEWS_LOOKBACK_HOURS,
)


# ── generate_listener_alerts ─────────────────────────────────────────────────


class TestListenerAlerts:
    def test_spike_alert(self, sample_seed, sample_history):
        """Artist with >5% 7d growth should trigger a listener_spike alert."""
        alerts = generate_listener_alerts(sample_seed, sample_history)
        spike_alerts = [a for a in alerts if a["type"] == "listener_spike"]
        assert len(spike_alerts) >= 1
        # The Weeknd (1Xyo4u8uXC1ZmMpatF05PJ) has a spike in sample_history
        weeknd_alerts = [a for a in spike_alerts if a["spotify_id"] == "1Xyo4u8uXC1ZmMpatF05PJ"]
        assert len(weeknd_alerts) == 1
        assert "gained" in weeknd_alerts[0]["message"].lower() or "+" in weeknd_alerts[0]["message"]

    def test_drop_alert(self, sample_seed, sample_history):
        """Artist with <-5% 7d decline should trigger a listener_drop alert."""
        alerts = generate_listener_alerts(sample_seed, sample_history)
        drop_alerts = [a for a in alerts if a["type"] == "listener_drop"]
        assert len(drop_alerts) >= 1
        # Taylor Swift (06HL4z0CvFAxyc27GXpf02) has a drop in sample_history
        ts_alerts = [a for a in drop_alerts if a["spotify_id"] == "06HL4z0CvFAxyc27GXpf02"]
        assert len(ts_alerts) == 1
        assert "dropped" in ts_alerts[0]["message"].lower() or "-" in ts_alerts[0]["message"]

    def test_insufficient_data_skipped(self, sample_seed, sample_history):
        """Artists with fewer than 3 history entries should not generate alerts."""
        alerts = generate_listener_alerts(sample_seed, sample_history)
        # Drake (3TVXtAsR1Inumwj472S9r4) has only 2 entries
        drake_alerts = [a for a in alerts if a["spotify_id"] == "3TVXtAsR1Inumwj472S9r4"]
        assert len(drake_alerts) == 0

    def test_no_history_no_alerts(self, sample_seed):
        """Empty history dict should produce no alerts."""
        alerts = generate_listener_alerts(sample_seed, {})
        assert alerts == []


# ── generate_news_alerts ─────────────────────────────────────────────────────


class TestNewsAlerts:
    def test_within_cutoff(self, tmp_data_dir, monkeypatch):
        """Articles published within NEWS_LOOKBACK_HOURS should produce alerts."""
        import pipeline.step_alerts as alerts_mod

        now = datetime.now(timezone.utc)
        recent_pub = (now - timedelta(hours=1)).isoformat()
        news = [
            {
                "title": "The Weeknd announces tour",
                "url": "https://example.com/weeknd-tour",
                "source": "Billboard",
                "published": recent_pub,
                "matched_artists": ["The Weeknd"],
                "matched_spotify_ids": ["1Xyo4u8uXC1ZmMpatF05PJ"],
            }
        ]
        # Patch _load_optional to return our test data
        monkeypatch.setattr(alerts_mod, "_load_optional", lambda filename: news)

        seed = [{"name": "The Weeknd", "spotify_id": "1Xyo4u8uXC1ZmMpatF05PJ"}]
        alerts = generate_news_alerts(seed)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "news_mention"

    def test_outside_cutoff(self, tmp_data_dir, monkeypatch):
        """Articles published before the cutoff should NOT produce alerts."""
        import pipeline.step_alerts as alerts_mod

        now = datetime.now(timezone.utc)
        old_pub = (now - timedelta(hours=NEWS_LOOKBACK_HOURS + 10)).isoformat()
        news = [
            {
                "title": "Old news about Drake",
                "url": "https://example.com/old-drake",
                "source": "NME",
                "published": old_pub,
                "matched_artists": ["Drake"],
                "matched_spotify_ids": ["3TVXtAsR1Inumwj472S9r4"],
            }
        ]
        monkeypatch.setattr(alerts_mod, "_load_optional", lambda filename: news)

        seed = [{"name": "Drake", "spotify_id": "3TVXtAsR1Inumwj472S9r4"}]
        alerts = generate_news_alerts(seed)
        assert len(alerts) == 0
