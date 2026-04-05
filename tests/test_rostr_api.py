"""Unit tests for the Rostr private-API client.

Covers the pure-Python pieces (slugify, cache helpers, response
normalisation) that don't need network access. Live API calls are
exercised manually via smoke tests — they burn real quota, so they
don't run in CI.
"""
from __future__ import annotations

import json
import os

import pytest

from pipeline import rostr_api


# ── slugify ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name,expected", [
    ("Justin Bieber", "justinbieber"),
    ("The Weeknd", "theweeknd"),
    ("Tyler, The Creator", "tylerthecreator"),
    ("Beyoncé", "beyonce"),
    ("Rosalía", "rosalia"),
    ("21 Savage", "21savage"),
    ("SZA", "sza"),
    ("  Taylor   Swift  ", "taylorswift"),
    ("J. Cole", "jcole"),
    # Edge case: `$` has no ASCII equivalent in NFKD, so it's stripped.
    # Rostr's real slug may differ; the public-index fallback path covers this.
    ("A$AP Rocky", "aaprocky"),
    ("", ""),
])
def test_slugify(name: str, expected: str) -> None:
    assert rostr_api.slugify(name) == expected


# ── team response normalisation ───────────────────────────────────────────────


def test_flatten_team_dedupes_by_rostr_id() -> None:
    # Rostr sometimes returns the same company twice (company + individual manager).
    raw = [
        {"company": {"name": "Blood Co", "rostrId": "bloodco",
                     "people": [{"name": "Jane Doe", "role": "MANAGER"}],
                     "hqLocations": ["LA"]}},
        {"company": {"name": "Blood Co", "rostrId": "bloodco", "people": []}},
        {"company": {"name": "Second Co", "rostrId": "secondco",
                     "people": [{"name": "Bob", "role": "MANAGER"}]}},
    ]
    out = rostr_api._flatten_team(raw)
    assert len(out) == 2
    assert out[0]["company"] == "Blood Co"
    assert out[0]["people"] == [{"name": "Jane Doe", "role": "MANAGER", "rostrId": None}]
    assert out[0]["hqLocations"] == ["LA"]
    assert out[1]["company"] == "Second Co"


def test_flatten_team_handles_missing_fields() -> None:
    raw = [{"company": {"name": "Minimal Co"}}]
    out = rostr_api._flatten_team(raw)
    assert out == [{
        "company": "Minimal Co",
        "rostrId": None,
        "hqLocations": [],
        "profileUrl": None,
        "people": [],
    }]


# ── events response normalisation ─────────────────────────────────────────────


def test_flatten_events_extracts_venue_and_coords() -> None:
    raw = {
        "bitUrl": "https://bandsintown.com/a/123",
        "events": [
            {
                "id": 1,
                "date": "2026-05-15T20:00:00.000+00:00",
                "ticketsAvailable": True,
                "location": {
                    "name": "Madison Square Garden",
                    "city": "New York", "state": "NY", "country": "United States",
                    "countryCode": "us", "lat": 40.7505, "lng": -73.9934,
                },
                "url": "https://bandsintown.com/e/1",
            }
        ],
    }
    out = rostr_api._flatten_events(raw)
    assert len(out) == 1
    ev = out[0]
    assert ev["venue"] == "Madison Square Garden"
    assert ev["city"] == "New York"
    assert ev["country"] == "United States"
    assert ev["lat"] == 40.7505
    assert ev["lng"] == -73.9934
    assert ev["ticketsAvailable"] is True


def test_flatten_events_handles_empty() -> None:
    assert rostr_api._flatten_events({"events": []}) == []
    assert rostr_api._flatten_events({}) == []


# ── auth env handling ─────────────────────────────────────────────────────────


def test_auth_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROSTR_SESSION_COOKIE", raising=False)
    with pytest.raises(rostr_api.RostrAuthMissing):
        rostr_api._get_session_cookie()


def test_auth_accepts_bare_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROSTR_SESSION_COOKIE", "abc123")
    assert rostr_api._get_session_cookie() == "rack.session=abc123"


def test_auth_accepts_prefixed_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROSTR_SESSION_COOKIE", "rack.session=xyz789")
    assert rostr_api._get_session_cookie() == "rack.session=xyz789"


# ── quota-error classification ────────────────────────────────────────────────


def test_403_with_quota_message_raises_quota_exceeded() -> None:
    body = b'{"msg":"This API request is not authorized as your account has exceeded the maximum profile views for this period."}'
    with pytest.raises(rostr_api.RostrQuotaExceeded):
        rostr_api._handle_status(403, body, "test")


def test_403_without_quota_message_raises_generic() -> None:
    body = b'{"msg":"access denied"}'
    with pytest.raises(rostr_api.RostrError) as exc_info:
        rostr_api._handle_status(403, body, "test")
    assert not isinstance(exc_info.value, rostr_api.RostrQuotaExceeded)


def test_401_raises_auth_invalid() -> None:
    with pytest.raises(rostr_api.RostrAuthInvalid):
        rostr_api._handle_status(401, b"", "test")


def test_404_raises_not_found() -> None:
    with pytest.raises(rostr_api.RostrNotFound):
        rostr_api._handle_status(404, b"", "test")


def test_200_does_nothing() -> None:
    rostr_api._handle_status(200, b"{}", "test")  # should not raise


# ── cache round-trip ──────────────────────────────────────────────────────────


def test_cache_round_trip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Point DB at a temp file so we don't mutate the real one
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path))
    import importlib
    import db
    importlib.reload(db)
    db.init_db()

    db.rostr_cache_put("testslug", "Test Artist", {"name": "Test", "events": [{"id": 1}]})
    got = db.rostr_cache_get("testslug")
    assert got is not None
    assert got["artist_name"] == "Test Artist"
    assert got["data"]["name"] == "Test"
    assert got["data"]["events"][0]["id"] == 1
    assert got["fetched_at"]  # non-empty timestamp

    # Overwrite with new data
    db.rostr_cache_put("testslug", "Test Artist", {"name": "Updated"})
    got2 = db.rostr_cache_get("testslug")
    assert got2["data"]["name"] == "Updated"

    # Delete
    assert db.rostr_cache_delete("testslug") is True
    assert db.rostr_cache_get("testslug") is None
    assert db.rostr_cache_delete("testslug") is False


def test_cache_get_empty_slug_returns_none() -> None:
    import db
    assert db.rostr_cache_get("") is None
    assert db.rostr_cache_get(None) is None  # type: ignore[arg-type]
