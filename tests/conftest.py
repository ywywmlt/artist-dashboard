"""Shared fixtures for the artist-dashboard test suite."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is on sys.path so we can import app, utils, pipeline.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# tmp_data_dir — a fresh temporary directory for data files
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_data_dir(tmp_path):
    """Return a temporary directory suitable for data file tests."""
    return tmp_path


# ---------------------------------------------------------------------------
# Flask test clients
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """Flask test client with all paths redirected to temp directories.

    Patches the module-level path globals in ``db`` and ``app`` so that
    the SQLite database and DATA_DIR all point into *tmp_path*.
    The admin seed creates a default admin/changeme123 account.
    """
    import db as db_module
    import app as app_module

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    raw_dir = data_dir / "raw"
    raw_dir.mkdir()
    persistent_dir = tmp_path / "persistent"
    persistent_dir.mkdir()

    # Patch db module paths
    monkeypatch.setattr(db_module, "PERSISTENT_DIR", persistent_dir)
    monkeypatch.setattr(db_module, "DB_PATH", persistent_dir / "test.db")
    monkeypatch.setattr(db_module, "USERS_FILE", persistent_dir / "users.json")
    monkeypatch.setattr(db_module, "USERS_DATA_DIR", persistent_dir / "users")

    # Patch app module paths
    monkeypatch.setattr(app_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(app_module, "PERSISTENT_DIR", persistent_dir)
    monkeypatch.setattr(app_module, "_GIT_USERS_FILE", data_dir / "users.json")
    monkeypatch.setattr(app_module, "_GIT_USERS_DATA_DIR", data_dir / "users")

    # Initialise fresh database
    db_module.init_db()
    # Seed admin
    app_module._seed_admin()

    app_module.app.config["TESTING"] = True
    # Clear rate-limit state between tests
    app_module._login_attempts.clear()

    with app_module.app.test_client() as client:
        yield client


@pytest.fixture()
def admin_client(app_client):
    """A Flask test client already logged in as admin."""
    resp = app_client.post("/api/login", json={
        "username": "admin",
        "password": "changeme123",
    })
    assert resp.status_code == 200, resp.get_json()
    return app_client


@pytest.fixture()
def authed_client(admin_client):
    """A Flask test client logged in as a regular (non-admin) user.

    Creates a user via the admin endpoint, then logs in as that user.
    """
    # Create a regular user via admin
    admin_client.post("/api/users", json={
        "username": "testuser",
        "password": "testpass1234",
        "role": "user",
    })
    # Log out admin
    admin_client.post("/api/logout")
    # Log in as regular user
    resp = admin_client.post("/api/login", json={
        "username": "testuser",
        "password": "testpass1234",
    })
    assert resp.status_code == 200, resp.get_json()
    return admin_client


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_seed():
    """Five sample ArtistSeed-like dicts."""
    return [
        {
            "rank": 1, "name": "The Weeknd", "spotify_id": "1Xyo4u8uXC1ZmMpatF05PJ",
            "monthly_listeners": 115_000_000, "daily_change": 500_000,
            "peak_listeners": 120_000_000, "scraped_at": "2025-01-01T00:00:00",
        },
        {
            "rank": 2, "name": "Taylor Swift", "spotify_id": "06HL4z0CvFAxyc27GXpf02",
            "monthly_listeners": 90_000_000, "daily_change": -200_000,
            "peak_listeners": 100_000_000, "scraped_at": "2025-01-01T00:00:00",
        },
        {
            "rank": 3, "name": "Drake", "spotify_id": "3TVXtAsR1Inumwj472S9r4",
            "monthly_listeners": 80_000_000, "daily_change": 100_000,
            "peak_listeners": 85_000_000, "scraped_at": "2025-01-01T00:00:00",
        },
        {
            "rank": 4, "name": "Bad Bunny", "spotify_id": "4q3ewBCX7sLwd24euuV69X",
            "monthly_listeners": 70_000_000, "daily_change": None,
            "peak_listeners": 75_000_000, "scraped_at": "2025-01-01T00:00:00",
        },
        {
            "rank": 5, "name": "Billie Eilish", "spotify_id": "6qqNVTkY8uBg9cP3Jd7DAH",
            "monthly_listeners": 65_000_000, "daily_change": 300_000,
            "peak_listeners": 70_000_000, "scraped_at": "2025-01-01T00:00:00",
        },
    ]


@pytest.fixture()
def sample_history():
    """Listener history entries suitable for momentum / alert testing.

    Returns a dict keyed by spotify_id with a list of daily snapshots.
    """
    base = 100_000_000
    # Artist with a 7-day spike (~+10%)
    spike_entries = []
    for i in range(10):
        listeners = base + i * 1_000_000
        spike_entries.append({
            "date": f"2025-01-{10 + i:02d}",
            "listeners": listeners,
            "daily_change": 1_000_000,
        })

    # Artist with a 7-day drop (~-10%)
    drop_entries = []
    for i in range(10):
        listeners = base - i * 1_200_000
        drop_entries.append({
            "date": f"2025-01-{10 + i:02d}",
            "listeners": listeners,
            "daily_change": -1_200_000,
        })

    # Artist with insufficient data (2 entries only)
    short_entries = [
        {"date": "2025-01-10", "listeners": base, "daily_change": 0},
        {"date": "2025-01-11", "listeners": base + 500_000, "daily_change": 500_000},
    ]

    return {
        "1Xyo4u8uXC1ZmMpatF05PJ": spike_entries,
        "06HL4z0CvFAxyc27GXpf02": drop_entries,
        "3TVXtAsR1Inumwj472S9r4": short_entries,
    }
