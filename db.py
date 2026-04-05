"""SQLite database module — replaces JSON file-based user data storage."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

# ── Persistent directory (same logic as app.py) ──────────────────────────────
DATA_DIR = Path(__file__).parent / "data"
PERSISTENT_DIR = Path(os.getenv("USER_DATA_DIR", str(DATA_DIR)))
DB_PATH = PERSISTENT_DIR / "artist_dashboard.db"

# Legacy JSON paths (for migration)
USERS_FILE = PERSISTENT_DIR / "users.json"
USERS_DATA_DIR = PERSISTENT_DIR / "users"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin', 'user')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_profiles (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    data JSON NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_watchlist (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    spotify_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, spotify_id)
);

CREATE TABLE IF NOT EXISTS user_contacts (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    spotify_id TEXT NOT NULL,
    data JSON NOT NULL,
    PRIMARY KEY (user_id, spotify_id)
);

CREATE TABLE IF NOT EXISTS user_alerts (
    id TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    artist_name TEXT,
    spotify_id TEXT,
    message TEXT NOT NULL,
    url TEXT,
    generated_at TEXT NOT NULL,
    read BOOLEAN NOT NULL DEFAULT 0,
    dismissed BOOLEAN NOT NULL DEFAULT 0,
    extra JSON,
    PRIMARY KEY (id, user_id)
);

CREATE TABLE IF NOT EXISTS custom_artists (
    spotify_id TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (spotify_id, user_id)
);

CREATE TABLE IF NOT EXISTS rostr_cache (
    slug TEXT PRIMARY KEY,
    artist_name TEXT,
    data JSON NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# ── Connection management ────────────────────────────────────────────────────


def get_db() -> sqlite3.Connection:
    """Return a SQLite connection with WAL mode and foreign keys enabled."""
    PERSISTENT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables (if not exists) and run migration from JSON if needed."""
    conn = get_db()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
        log.info("Database tables ensured at %s", DB_PATH)
        migrate_from_json(conn)
    finally:
        conn.close()


# ── Migration from JSON ─────────────────────────────────────────────────────


def migrate_from_json(conn: sqlite3.Connection | None = None) -> None:
    """Migrate legacy JSON files into SQLite.

    Only runs if the users table is empty AND users.json exists.
    """
    close = False
    if conn is None:
        conn = get_db()
        close = True
    try:
        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        if row[0] > 0:
            log.debug("Users table already populated — skipping JSON migration")
            return
        if not USERS_FILE.exists():
            log.debug("No users.json found — skipping JSON migration")
            return

        log.info("Migrating from JSON files into SQLite…")
        try:
            users_list = json.loads(USERS_FILE.read_text())
        except Exception as exc:
            log.error("Failed to read users.json: %s", exc)
            return

        with conn:
            for u in users_list:
                username = u.get("username")
                password_hash = u.get("password_hash")
                role = u.get("role", "user")
                if not username or not password_hash:
                    continue

                conn.execute(
                    "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    (username, password_hash, role),
                )
                user_row = conn.execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone()
                if user_row is None:
                    continue
                user_id = user_row[0]

                # Load per-user data.json
                data_file = USERS_DATA_DIR / username / "data.json"
                if not data_file.exists():
                    continue
                try:
                    data = json.loads(data_file.read_text())
                except Exception:
                    continue

                # Profiles
                for profile in data.get("profiles", []):
                    profile_id = profile.get("id")
                    if not profile_id:
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO user_profiles (id, user_id, data) VALUES (?, ?, ?)",
                        (profile_id, user_id, json.dumps(profile)),
                    )

                # Watchlist
                for spotify_id, tag in data.get("watchlist", {}).items():
                    conn.execute(
                        "INSERT OR IGNORE INTO user_watchlist (user_id, spotify_id, tag) VALUES (?, ?, ?)",
                        (user_id, spotify_id, tag),
                    )

                # Contacts
                for spotify_id, contact_data in data.get("contacts", {}).items():
                    conn.execute(
                        "INSERT OR IGNORE INTO user_contacts (user_id, spotify_id, data) VALUES (?, ?, ?)",
                        (user_id, spotify_id, json.dumps(contact_data)),
                    )

                # Alerts
                for alert in data.get("alerts", []):
                    alert_id = alert.get("id")
                    if not alert_id:
                        continue
                    # Separate known columns from extra
                    extra_keys = set(alert.keys()) - {
                        "id", "type", "artist_name", "spotify_id",
                        "message", "url", "generated_at", "read", "dismissed",
                    }
                    extra = {k: alert[k] for k in extra_keys} if extra_keys else None
                    conn.execute(
                        """INSERT OR IGNORE INTO user_alerts
                           (id, user_id, type, artist_name, spotify_id, message, url,
                            generated_at, read, dismissed, extra)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            alert_id,
                            user_id,
                            alert.get("type", ""),
                            alert.get("artist_name"),
                            alert.get("spotify_id"),
                            alert.get("message", ""),
                            alert.get("url"),
                            alert.get("generated_at", ""),
                            1 if alert.get("read") else 0,
                            1 if alert.get("dismissed") else 0,
                            json.dumps(extra) if extra else None,
                        ),
                    )

        log.info("JSON migration complete")
    finally:
        if close:
            conn.close()


# ── Helper: resolve user_id from username ────────────────────────────────────


def _user_id(conn: sqlite3.Connection, username: str) -> int | None:
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    return row[0] if row else None


# ── User CRUD ────────────────────────────────────────────────────────────────


def load_users() -> list[dict]:
    """Return list of {username, password_hash, role} dicts."""
    conn = get_db()
    try:
        rows = conn.execute("SELECT username, password_hash, role FROM users").fetchall()
        return [{"username": r["username"], "password_hash": r["password_hash"], "role": r["role"]} for r in rows]
    finally:
        conn.close()


def save_user(username: str, password_hash: str, role: str = "user") -> None:
    """Insert a new user."""
    conn = get_db()
    try:
        with conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, password_hash, role),
            )
        log.info("Created user: %s (role=%s)", username, role)
    finally:
        conn.close()


def get_user(username: str) -> dict | None:
    """Get a single user by username. Returns {id, username, password_hash, role} or None."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, username, password_hash, role FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "username": row["username"],
                "password_hash": row["password_hash"], "role": row["role"]}
    finally:
        conn.close()


def delete_user(username: str) -> bool:
    """Delete a user and cascade. Returns True if found."""
    conn = get_db()
    try:
        with conn:
            cur = conn.execute("DELETE FROM users WHERE username = ?", (username,))
        deleted = cur.rowcount > 0
        if deleted:
            log.info("Deleted user: %s", username)
        return deleted
    finally:
        conn.close()


def update_username(old_username: str, new_username: str) -> None:
    """Rename a user."""
    conn = get_db()
    try:
        with conn:
            conn.execute(
                "UPDATE users SET username = ? WHERE username = ?",
                (new_username, old_username),
            )
        log.info("Renamed user: %s → %s", old_username, new_username)
    finally:
        conn.close()


def update_password(username: str, password_hash: str) -> None:
    """Update a user's password hash."""
    conn = get_db()
    try:
        with conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (password_hash, username),
            )
        log.info("Updated password for user: %s", username)
    finally:
        conn.close()


# ── User data (profiles, watchlist, contacts, alerts) ────────────────────────


def load_user_data(username: str) -> dict:
    """Load all user data as the same dict structure app.py expects:

    {"profiles": [...], "watchlist": {...}, "contacts": {...}, "alerts": [...]}
    """
    conn = get_db()
    try:
        uid = _user_id(conn, username)
        if uid is None:
            return {"profiles": [], "watchlist": {}, "contacts": {}, "alerts": []}

        # Profiles
        profiles = []
        for row in conn.execute("SELECT data FROM user_profiles WHERE user_id = ?", (uid,)):
            profiles.append(json.loads(row["data"]))

        # Watchlist
        watchlist = {}
        for row in conn.execute("SELECT spotify_id, tag FROM user_watchlist WHERE user_id = ?", (uid,)):
            watchlist[row["spotify_id"]] = row["tag"]

        # Contacts
        contacts = {}
        for row in conn.execute("SELECT spotify_id, data FROM user_contacts WHERE user_id = ?", (uid,)):
            contacts[row["spotify_id"]] = json.loads(row["data"])

        # Alerts
        alerts = []
        for row in conn.execute(
            """SELECT id, type, artist_name, spotify_id, message, url,
                      generated_at, read, dismissed, extra
               FROM user_alerts WHERE user_id = ?""",
            (uid,),
        ):
            alert = {
                "id": row["id"],
                "type": row["type"],
                "artist_name": row["artist_name"],
                "spotify_id": row["spotify_id"],
                "message": row["message"],
                "url": row["url"],
                "generated_at": row["generated_at"],
                "read": bool(row["read"]),
                "dismissed": bool(row["dismissed"]),
            }
            if row["extra"]:
                extra = json.loads(row["extra"])
                alert.update(extra)
            alerts.append(alert)

        return {"profiles": profiles, "watchlist": watchlist, "contacts": contacts, "alerts": alerts}
    finally:
        conn.close()


def save_user_data(username: str, data: dict) -> None:
    """Save user data from the same dict structure. Replaces all sub-tables."""
    conn = get_db()
    try:
        uid = _user_id(conn, username)
        if uid is None:
            log.warning("save_user_data: user %s not found", username)
            return

        with conn:
            # Clear existing data
            conn.execute("DELETE FROM user_profiles WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM user_watchlist WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM user_contacts WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM user_alerts WHERE user_id = ?", (uid,))

            # Profiles
            for profile in data.get("profiles", []):
                profile_id = profile.get("id")
                if not profile_id:
                    continue
                conn.execute(
                    "INSERT INTO user_profiles (id, user_id, data) VALUES (?, ?, ?)",
                    (profile_id, uid, json.dumps(profile)),
                )

            # Watchlist
            for spotify_id, tag in data.get("watchlist", {}).items():
                conn.execute(
                    "INSERT INTO user_watchlist (user_id, spotify_id, tag) VALUES (?, ?, ?)",
                    (uid, spotify_id, tag),
                )

            # Contacts
            for spotify_id, contact_data in data.get("contacts", {}).items():
                conn.execute(
                    "INSERT INTO user_contacts (user_id, spotify_id, data) VALUES (?, ?, ?)",
                    (uid, spotify_id, json.dumps(contact_data)),
                )

            # Alerts
            for alert in data.get("alerts", []):
                alert_id = alert.get("id")
                if not alert_id:
                    continue
                extra_keys = set(alert.keys()) - {
                    "id", "type", "artist_name", "spotify_id",
                    "message", "url", "generated_at", "read", "dismissed",
                }
                extra = {k: alert[k] for k in extra_keys} if extra_keys else None
                conn.execute(
                    """INSERT INTO user_alerts
                       (id, user_id, type, artist_name, spotify_id, message, url,
                        generated_at, read, dismissed, extra)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        alert_id,
                        uid,
                        alert.get("type", ""),
                        alert.get("artist_name"),
                        alert.get("spotify_id"),
                        alert.get("message", ""),
                        alert.get("url"),
                        alert.get("generated_at", ""),
                        1 if alert.get("read") else 0,
                        1 if alert.get("dismissed") else 0,
                        json.dumps(extra) if extra else None,
                    ),
                )

        log.debug("Saved user data for %s", username)
    finally:
        conn.close()


# ── Alert helpers ────────────────────────────────────────────────────────────


def sync_alerts(username: str, pipeline_alerts: list[dict]) -> tuple[int, list[dict]]:
    """Merge pipeline alerts into user's alerts. Returns (added_count, active_alerts)."""
    conn = get_db()
    try:
        uid = _user_id(conn, username)
        if uid is None:
            return 0, []

        with conn:
            # Get existing alert IDs
            existing_ids = {
                row[0]
                for row in conn.execute(
                    "SELECT id FROM user_alerts WHERE user_id = ?", (uid,)
                )
            }

            added = 0
            for alert in pipeline_alerts:
                alert_id = alert.get("id")
                if not alert_id or alert_id in existing_ids:
                    continue
                extra_keys = set(alert.keys()) - {
                    "id", "type", "artist_name", "spotify_id",
                    "message", "url", "generated_at", "read", "dismissed",
                }
                extra = {k: alert[k] for k in extra_keys} if extra_keys else None
                conn.execute(
                    """INSERT INTO user_alerts
                       (id, user_id, type, artist_name, spotify_id, message, url,
                        generated_at, read, dismissed, extra)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        alert_id,
                        uid,
                        alert.get("type", ""),
                        alert.get("artist_name"),
                        alert.get("spotify_id"),
                        alert.get("message", ""),
                        alert.get("url"),
                        alert.get("generated_at", ""),
                        1 if alert.get("read") else 0,
                        1 if alert.get("dismissed") else 0,
                        json.dumps(extra) if extra else None,
                    ),
                )
                added += 1

            # Prune to 200: keep newest, drop oldest dismissed first, then oldest read
            total = conn.execute(
                "SELECT COUNT(*) FROM user_alerts WHERE user_id = ?", (uid,)
            ).fetchone()[0]
            if total > 200:
                # Delete the excess rows (oldest dismissed first, then oldest read, then oldest)
                conn.execute(
                    """DELETE FROM user_alerts WHERE rowid IN (
                        SELECT rowid FROM user_alerts WHERE user_id = ?
                        ORDER BY
                            dismissed ASC,
                            read ASC,
                            generated_at DESC
                        LIMIT -1 OFFSET 200
                    )""",
                    (uid,),
                )

        # Return active (non-dismissed) alerts
        active = []
        for row in conn.execute(
            """SELECT id, type, artist_name, spotify_id, message, url,
                      generated_at, read, dismissed, extra
               FROM user_alerts WHERE user_id = ? AND dismissed = 0""",
            (uid,),
        ):
            alert = {
                "id": row["id"],
                "type": row["type"],
                "artist_name": row["artist_name"],
                "spotify_id": row["spotify_id"],
                "message": row["message"],
                "url": row["url"],
                "generated_at": row["generated_at"],
                "read": bool(row["read"]),
                "dismissed": bool(row["dismissed"]),
            }
            if row["extra"]:
                extra = json.loads(row["extra"])
                alert.update(extra)
            active.append(alert)

        return added, active
    finally:
        conn.close()


def mark_alert_read(username: str, alert_id: str) -> None:
    """Mark a single alert as read."""
    conn = get_db()
    try:
        uid = _user_id(conn, username)
        if uid is None:
            return
        with conn:
            conn.execute(
                "UPDATE user_alerts SET read = 1 WHERE id = ? AND user_id = ?",
                (alert_id, uid),
            )
    finally:
        conn.close()


def dismiss_alert(username: str, alert_id: str) -> None:
    """Dismiss a single alert (also marks as read)."""
    conn = get_db()
    try:
        uid = _user_id(conn, username)
        if uid is None:
            return
        with conn:
            conn.execute(
                "UPDATE user_alerts SET dismissed = 1, read = 1 WHERE id = ? AND user_id = ?",
                (alert_id, uid),
            )
    finally:
        conn.close()


def mark_all_alerts_read(username: str) -> None:
    """Mark all alerts as read for a user."""
    conn = get_db()
    try:
        uid = _user_id(conn, username)
        if uid is None:
            return
        with conn:
            conn.execute(
                "UPDATE user_alerts SET read = 1 WHERE user_id = ?", (uid,)
            )
    finally:
        conn.close()


# ── Custom artists (Feature 9) ──────────────────────────────────────────────


def add_custom_artist(username: str, spotify_id: str, name: str | None = None) -> None:
    """Add a custom artist for a user."""
    conn = get_db()
    try:
        uid = _user_id(conn, username)
        if uid is None:
            log.warning("add_custom_artist: user %s not found", username)
            return
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO custom_artists (spotify_id, user_id, name) VALUES (?, ?, ?)",
                (spotify_id, uid, name),
            )
        log.info("Added custom artist %s for user %s", spotify_id, username)
    finally:
        conn.close()


def get_custom_artists(username: str) -> list[dict]:
    """Get all custom artists for a user."""
    conn = get_db()
    try:
        uid = _user_id(conn, username)
        if uid is None:
            return []
        rows = conn.execute(
            "SELECT spotify_id, name, added_at FROM custom_artists WHERE user_id = ?",
            (uid,),
        ).fetchall()
        return [{"spotify_id": r["spotify_id"], "name": r["name"], "added_at": r["added_at"]} for r in rows]
    finally:
        conn.close()


def delete_custom_artist(username: str, spotify_id: str) -> bool:
    """Delete a custom artist. Returns True if found."""
    conn = get_db()
    try:
        uid = _user_id(conn, username)
        if uid is None:
            return False
        with conn:
            cur = conn.execute(
                "DELETE FROM custom_artists WHERE spotify_id = ? AND user_id = ?",
                (spotify_id, uid),
            )
        return cur.rowcount > 0
    finally:
        conn.close()


# ── Rostr private-API cache ──────────────────────────────────────────────────


def rostr_cache_get(slug: str) -> dict | None:
    """Return cached Rostr data for a slug, or None if not cached.

    Returns {"data": dict, "fetched_at": str, "artist_name": str}.
    """
    if not slug:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT artist_name, data, fetched_at FROM rostr_cache WHERE slug = ?",
            (slug,),
        ).fetchone()
        if row is None:
            return None
        return {
            "artist_name": row["artist_name"],
            "data": json.loads(row["data"]),
            "fetched_at": row["fetched_at"],
        }
    finally:
        conn.close()


def rostr_cache_put(slug: str, artist_name: str | None, data: dict) -> None:
    """Insert or replace a Rostr cache entry. fetched_at set to now."""
    if not slug:
        return
    conn = get_db()
    try:
        with conn:
            conn.execute(
                """INSERT INTO rostr_cache (slug, artist_name, data, fetched_at)
                   VALUES (?, ?, ?, datetime('now'))
                   ON CONFLICT(slug) DO UPDATE SET
                       artist_name = excluded.artist_name,
                       data        = excluded.data,
                       fetched_at  = excluded.fetched_at""",
                (slug, artist_name, json.dumps(data)),
            )
        log.info("rostr_cache: stored %s", slug)
    finally:
        conn.close()


def rostr_cache_delete(slug: str) -> bool:
    """Delete a cache entry (forces next lookup to refetch). Returns True if found."""
    if not slug:
        return False
    conn = get_db()
    try:
        with conn:
            cur = conn.execute("DELETE FROM rostr_cache WHERE slug = ?", (slug,))
        return cur.rowcount > 0
    finally:
        conn.close()


def get_all_custom_artist_ids() -> list[tuple[str, str | None]]:
    """Get all distinct (spotify_id, name) pairs across all users (for pipeline use)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT DISTINCT spotify_id, name FROM custom_artists"
        ).fetchall()
        return [(r["spotify_id"], r["name"]) for r in rows]
    finally:
        conn.close()
