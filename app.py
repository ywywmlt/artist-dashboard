from __future__ import annotations

import os
import json
import re
import secrets
import time
from collections import defaultdict
from functools import wraps
from pathlib import Path
from flask import Flask, send_file, jsonify, request, session
from werkzeug.security import generate_password_hash, check_password_hash
import requests as http_requests
import threading
from datetime import datetime
from config import TICKETMASTER_API_KEY

import db

_data_cache = {}
_CACHE_TTL = 60


def _load_cached_json(filename):
    """Load a JSON file from DATA_DIR/raw with 60s cache."""
    import time as _time
    key = filename
    now = _time.time()
    if key in _data_cache and now - _data_cache[key]["ts"] < _CACHE_TTL:
        return _data_cache[key]["data"]
    filepath = DATA_DIR / "raw" / filename
    if not filepath.exists():
        return []
    try:
        data = json.loads(filepath.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    _data_cache[key] = {"data": data, "ts": now}
    return data


SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
# Persist the generated key so sessions survive within a single process lifetime
os.environ.setdefault("SECRET_KEY", SECRET_KEY)

app = Flask(__name__, static_folder="data", static_url_path="/data")
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True

from flask_compress import Compress
Compress(app)


@app.after_request
def add_cache_headers(response):
    if request.path.startswith("/data/") and request.path.endswith(".json"):
        response.headers["Cache-Control"] = "public, max-age=300"
    return response

# ── Username validation ───────────────────────────────────────────────────────
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _validate_username(username: str) -> str | None:
    """Return an error message if username is invalid, else None."""
    if not username:
        return "Username required"
    if not _USERNAME_RE.match(username):
        return "Username must be 1-64 characters: letters, digits, hyphens, underscores only"
    return None


# ── Login rate limiting ───────────────────────────────────────────────────────
_login_attempts: dict[str, list[float]] = defaultdict(list)
_LOGIN_WINDOW = 300    # 5 minutes
_LOGIN_MAX_ATTEMPTS = 10

TICKETMASTER_BASE = "https://app.ticketmaster.com/discovery/v2/events.json"

# ── Data paths ─────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"

# ── Seed volume from committed JSON (for fresh Railway volumes) ───────────────
PERSISTENT_DIR = Path(os.getenv("USER_DATA_DIR", str(DATA_DIR)))
_GIT_USERS_FILE = DATA_DIR / "users.json"
_GIT_USERS_DATA_DIR = DATA_DIR / "users"


def _seed_volume_from_committed():
    """On first boot with a fresh volume, copy committed JSON so migration can find them."""
    if PERSISTENT_DIR == DATA_DIR:
        return
    users_json = PERSISTENT_DIR / "users.json"
    users_dir = PERSISTENT_DIR / "users"
    if users_json.exists() or db.DB_PATH.exists():
        return  # already initialised
    PERSISTENT_DIR.mkdir(parents=True, exist_ok=True)
    if _GIT_USERS_FILE.exists():
        try:
            users_json.write_text(_GIT_USERS_FILE.read_text())
        except Exception:
            pass
    if _GIT_USERS_DATA_DIR.exists():
        import shutil
        users_dir.mkdir(parents=True, exist_ok=True)
        for user_dir in _GIT_USERS_DATA_DIR.iterdir():
            if user_dir.is_dir():
                target = users_dir / user_dir.name
                if not target.exists():
                    try:
                        shutil.copytree(str(user_dir), str(target))
                    except Exception:
                        pass


def _seed_admin():
    """Create default admin if no users exist."""
    users = db.load_users()
    if users:
        return
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "changeme123")
    db.save_user(
        admin_username,
        generate_password_hash(admin_password, method="pbkdf2:sha256"),
        "admin",
    )


# Initialise on import
DATA_DIR.mkdir(exist_ok=True)
_seed_volume_from_committed()
db.init_db()  # creates tables + migrates JSON if needed
_seed_admin()


# ── Auth decorators ────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return jsonify({"error": "Authentication required"}), 401
        user = db.get_user(session["username"])
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


# ── Refresh job state ──────────────────────────────────────────────────────────
_refresh_lock = threading.Lock()
_refresh = {
    "running": False,
    "progress": 0,       # 0–100
    "message": "Idle",
    "error": None,
    "last_run": None,
}


def _run_refresh():
    """Run quick refresh: kworb → spotify → news → ticketmaster → alerts → export."""
    import importlib
    steps = [
        ("kworb rankings",     "pipeline.step1_seed_kworb",      12),
        ("spotify data",       "pipeline.step_spotify",           24),
        ("news articles",      "pipeline.step6_news",             36),
        ("ticketmaster events","pipeline.step_ticketmaster",      80),
        ("rostr intel",        "pipeline.step_rostr",             85),
        ("alerts",             "pipeline.step_alerts",            92),
        ("export",             "pipeline.step5_export",          100),
    ]
    try:
        for label, module_path, pct_done in steps:
            _refresh["message"] = f"Fetching {label}..."
            mod = importlib.import_module(module_path)
            if module_path == "pipeline.step_ticketmaster":
                def _cb(done, total, msg, _pct=pct_done):
                    base = 36
                    _refresh["progress"] = base + int(done / total * (_pct - base)) if total else base
                    _refresh["message"] = msg
                mod.run(progress_callback=_cb)
            else:
                mod.run()
            _refresh["progress"] = pct_done
        _refresh["progress"] = 100
        _refresh["message"] = "Complete"
        _refresh["last_run"] = datetime.utcnow().isoformat() + "Z"
    except Exception as e:
        _refresh["error"] = str(e)
        _refresh["message"] = f"Error: {e}"
    finally:
        with _refresh_lock:
            _refresh["running"] = False


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_file("ui-sample.html")


@app.route("/api/events")
def get_events():
    """Live single-artist lookup (used as fallback / search)."""
    keyword = request.args.get("keyword", "")
    size = request.args.get("size", 20)
    page = request.args.get("page", 0)
    params = {
        "apikey": TICKETMASTER_API_KEY,
        "keyword": keyword,
        "classificationName": "music",
        "size": size,
        "page": page,
        "sort": "date,asc",
    }
    try:
        resp = http_requests.get(TICKETMASTER_BASE, params=params, timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/events/refresh", methods=["POST"])
def refresh_events():
    """Kick off a background job to re-fetch events for all artists."""
    cron_secret = os.getenv("CRON_SECRET", "")
    is_authed_session = "username" in session
    is_cron = cron_secret and request.headers.get("X-Cron-Secret") == cron_secret
    if not is_authed_session and not is_cron:
        return jsonify({"error": "Authentication required"}), 401
    with _refresh_lock:
        if _refresh["running"]:
            return jsonify({"status": "already_running", **_refresh}), 409
        _refresh["running"] = True
        _refresh["progress"] = 0
        _refresh["error"] = None
        _refresh["message"] = "Starting..."
    thread = threading.Thread(target=_run_refresh, daemon=True)
    thread.start()
    return jsonify({"status": "started"}), 202


@app.route("/api/events/refresh/status")
def refresh_status():
    return jsonify(_refresh)


@app.route("/api/events/refresh/stream")
def refresh_stream():
    """SSE stream for pipeline refresh progress."""
    import time as _time
    def generate():
        last_state = None
        while True:
            state = json.dumps(_refresh)
            if state != last_state:
                yield f"data: {state}\n\n"
                last_state = state
                if not _refresh["running"] and _refresh["progress"] >= 100:
                    yield f"data: {json.dumps({**_refresh, 'done': True})}\n\n"
                    break
                if _refresh.get("error"):
                    yield f"data: {json.dumps({**_refresh, 'done': True})}\n\n"
                    break
            _time.sleep(0.5)
    return app.response_class(generate(), mimetype='text/event-stream',
                               headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route("/api/debug/spotify")
def debug_spotify():
    """Diagnostic: test Spotify credentials."""
    import json as _json
    from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, RAW_DIR
    from utils import load_checkpoint
    result = {
        "client_id_set": bool(SPOTIFY_CLIENT_ID),
        "client_id_prefix": SPOTIFY_CLIENT_ID[:8] + "..." if SPOTIFY_CLIENT_ID else None,
    }
    done_ids = load_checkpoint("step_spotify")
    result["checkpoint_count"] = len(done_ids)
    sp_file = RAW_DIR / "spotify_data.json"
    try:
        existing = _json.loads(sp_file.read_text())
        result["spotify_file_records"] = len(existing)
    except Exception as e:
        result["spotify_file_records"] = f"error: {e}"
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        result["status"] = "credentials_missing"
        return jsonify(result)
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
        sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET,
        ), requests_timeout=10)
        seed_file = RAW_DIR / "kworb_seed.json"
        seed = _json.loads(seed_file.read_text())[:5]
        ids = [a["spotify_id"] for a in seed]
        batch_result = sp.artists(ids)
        artists_returned = batch_result.get("artists") or []
        result["status"] = "ok"
        result["batch_test_ids_sent"] = len(ids)
        result["batch_test_returned"] = len([x for x in artists_returned if x])
        result["sample"] = [{"name": a.get("name"), "followers": (a.get("followers") or {}).get("total")}
                            for a in artists_returned if a][:3]
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    return jsonify(result)


# ── Auth routes ────────────────────────────────────────────────────────────────

@app.route("/api/login", methods=["POST"])
def api_login():
    ip = request.remote_addr or "unknown"
    now = time.time()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _LOGIN_WINDOW]
    if len(_login_attempts[ip]) >= _LOGIN_MAX_ATTEMPTS:
        return jsonify({"error": "Too many login attempts. Try again later."}), 429
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    user = db.get_user(username)
    if not user or not check_password_hash(user["password_hash"], password):
        _login_attempts[ip].append(now)
        return jsonify({"error": "Invalid credentials"}), 401
    session["username"] = username
    session["role"] = user["role"]
    return jsonify({"username": username, "role": user["role"]}), 200


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True}), 200


@app.route("/api/me")
def api_me():
    if "username" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    return jsonify({"username": session["username"], "role": session["role"]}), 200


@app.route("/api/user-data")
@login_required
def api_get_user_data():
    data = db.load_user_data(session["username"])
    return jsonify(data), 200


@app.route("/api/user-data", methods=["POST"])
@login_required
def api_save_user_data():
    data = request.get_json(force=True) or {}
    safe = {
        "profiles": data.get("profiles", []),
        "watchlist": data.get("watchlist", {}),
        "contacts": data.get("contacts", {}),
        "alerts": data.get("alerts", []),
    }
    db.save_user_data(session["username"], safe)
    return jsonify({"ok": True}), 200


# ── Alert routes ──────────────────────────────────────────────────────────────

@app.route("/api/alerts")
@login_required
def api_get_alerts():
    data = db.load_user_data(session["username"])
    alerts = [a for a in data.get("alerts", []) if not a.get("dismissed")]
    return jsonify(alerts), 200


@app.route("/api/alerts/sync", methods=["POST"])
@login_required
def api_sync_alerts():
    pipeline_file = DATA_DIR / "raw" / "pipeline_alerts.json"
    if not pipeline_file.exists():
        return jsonify([]), 200
    try:
        pipeline_alerts = json.loads(pipeline_file.read_text())
    except Exception:
        return jsonify([]), 200
    added, active = db.sync_alerts(session["username"], pipeline_alerts)
    return jsonify({"added": added, "alerts": active}), 200


@app.route("/api/alerts/<alert_id>/read", methods=["POST"])
@login_required
def api_mark_alert_read(alert_id):
    db.mark_alert_read(session["username"], alert_id)
    return jsonify({"ok": True}), 200


@app.route("/api/alerts/<alert_id>/dismiss", methods=["POST"])
@login_required
def api_dismiss_alert(alert_id):
    db.dismiss_alert(session["username"], alert_id)
    return jsonify({"ok": True}), 200


@app.route("/api/alerts/mark-all-read", methods=["POST"])
@login_required
def api_mark_all_read():
    db.mark_all_alerts_read(session["username"])
    return jsonify({"ok": True}), 200


# ── User management routes (admin only) ───────────────────────────────────────

@app.route("/api/users")
@admin_required
def api_list_users():
    users = db.load_users()
    return jsonify([{"username": u["username"], "role": u["role"]} for u in users]), 200


@app.route("/api/users", methods=["POST"])
@admin_required
def api_create_user():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = data.get("role", "user")
    err = _validate_username(username)
    if err:
        return jsonify({"error": err}), 400
    if not password or len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if role not in ("admin", "user"):
        return jsonify({"error": "Role must be 'admin' or 'user'"}), 400
    if db.get_user(username):
        return jsonify({"error": "Username already exists"}), 409
    db.save_user(username, generate_password_hash(password, method="pbkdf2:sha256"), role)
    return jsonify({"username": username, "role": role}), 201


@app.route("/api/users/<username>", methods=["DELETE"])
@admin_required
def api_delete_user(username):
    if username == session["username"]:
        return jsonify({"error": "Cannot delete yourself"}), 400
    if not db.delete_user(username):
        return jsonify({"error": "User not found"}), 404
    return jsonify({"ok": True}), 200


@app.route("/api/users/<username>/password", methods=["POST"])
@admin_required
def api_reset_password(username):
    data = request.get_json(force=True) or {}
    password = data.get("password") or ""
    if not password:
        return jsonify({"error": "Password required"}), 400
    if not db.get_user(username):
        return jsonify({"error": "User not found"}), 404
    db.update_password(username, generate_password_hash(password, method="pbkdf2:sha256"))
    return jsonify({"ok": True}), 200


@app.route("/api/account/username", methods=["POST"])
@login_required
def api_change_username():
    data = request.get_json(force=True) or {}
    new_username = (data.get("username") or "").strip()
    err = _validate_username(new_username)
    if err:
        return jsonify({"error": err}), 400
    if db.get_user(new_username):
        return jsonify({"error": "Username already taken"}), 409
    db.update_username(session["username"], new_username)
    session["username"] = new_username
    return jsonify({"ok": True, "username": new_username}), 200


@app.route("/api/account/password", methods=["POST"])
@login_required
def api_change_password():
    data = request.get_json(force=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    if not current_password or not new_password:
        return jsonify({"error": "Both current and new password required"}), 400
    user = db.get_user(session["username"])
    if not user or not check_password_hash(user["password_hash"], current_password):
        return jsonify({"error": "Current password is incorrect"}), 403
    db.update_password(session["username"], generate_password_hash(new_password, method="pbkdf2:sha256"))
    return jsonify({"ok": True}), 200


# ── Custom artist routes ──────────────────────────────────────────────────────

@app.route("/api/custom-artists")
@login_required
def api_list_custom_artists():
    artists = db.get_custom_artists(session["username"])
    return jsonify(artists), 200


@app.route("/api/custom-artists", methods=["POST"])
@login_required
def api_add_custom_artist():
    """Add a custom artist by Spotify URL or ID."""
    data = request.get_json(force=True) or {}
    raw = (data.get("spotify_url") or data.get("spotify_id") or "").strip()
    if not raw:
        return jsonify({"error": "Spotify URL or ID required"}), 400

    # Extract Spotify ID from URL or use raw value
    match = re.search(r"open\.spotify\.com/artist/([A-Za-z0-9]+)", raw)
    spotify_id = match.group(1) if match else raw

    # Validate format (Spotify IDs are 22 base62 chars)
    if not re.match(r"^[A-Za-z0-9]{22}$", spotify_id):
        return jsonify({"error": "Invalid Spotify artist ID"}), 400

    # Check if already added
    existing = db.get_custom_artists(session["username"])
    if any(a["spotify_id"] == spotify_id for a in existing):
        return jsonify({"error": "Artist already added"}), 409

    # Try to look up name via Spotify API
    name = None
    try:
        from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
        if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
            import spotipy
            from spotipy.oauth2 import SpotifyClientCredentials
            sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
                client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET,
            ), requests_timeout=10)
            artist = sp.artist(spotify_id)
            if artist:
                name = artist.get("name")
    except Exception:
        pass

    if not name:
        name = f"Artist ({spotify_id[:8]})"

    db.add_custom_artist(session["username"], spotify_id, name)
    return jsonify({"spotify_id": spotify_id, "name": name, "added": True}), 201


@app.route("/api/custom-artists/<spotify_id>", methods=["DELETE"])
@login_required
def api_delete_custom_artist(spotify_id):
    if not db.delete_custom_artist(session["username"], spotify_id):
        return jsonify({"error": "Artist not found"}), 404
    return jsonify({"ok": True}), 200


# ── Artist search/filter API ──────────────────────────────────────────────────

def _merge_artist_data():
    """Load and merge seed + touring + musicbrainz data by spotify_id."""
    seed = _load_cached_json("kworb_seed.json")
    touring = _load_cached_json("touring_data.json")
    mb = _load_cached_json("musicbrainz_data.json")

    touring_map = {t["spotify_id"]: t for t in touring if isinstance(t, dict) and "spotify_id" in t}
    mb_map = {m["spotify_id"]: m for m in mb if isinstance(m, dict) and "spotify_id" in m}

    merged = []
    for artist in seed:
        if not isinstance(artist, dict) or "spotify_id" not in artist:
            continue
        sid = artist["spotify_id"]
        entry = {**artist}
        if sid in touring_map:
            entry["touring"] = touring_map[sid]
        if sid in mb_map:
            entry["mb"] = mb_map[sid]
        merged.append(entry)
    return merged


@app.route("/api/artists")
def api_artists():
    """Paginated, filtered artist search endpoint."""
    # Parse query params
    q = (request.args.get("q") or "").strip().lower()
    genre = (request.args.get("genre") or "").strip().lower()
    country = (request.args.get("country") or "").strip()
    touring_filter = (request.args.get("touring") or "").strip().lower()
    sort = (request.args.get("sort") or "rank").strip().lower()
    try:
        limit = min(int(request.args.get("limit", 25)), 100)
    except (ValueError, TypeError):
        limit = 25
    if limit < 1:
        limit = 25
    try:
        offset = max(int(request.args.get("offset", 0)), 0)
    except (ValueError, TypeError):
        offset = 0

    artists = _merge_artist_data()

    # Filter by text search on name
    if q:
        artists = [a for a in artists if q in a.get("name", "").lower()]

    # Filter by genre (from musicbrainz data)
    if genre:
        artists = [a for a in artists
                   if any(genre == g.lower() for g in a.get("mb", {}).get("genres", []))]

    # Filter by country (from musicbrainz data)
    if country:
        artists = [a for a in artists
                   if a.get("mb", {}).get("country", "").upper() == country.upper()]

    # Filter by touring status
    if touring_filter == "true":
        artists = [a for a in artists if a.get("touring", {}).get("is_touring")]
    elif touring_filter == "false":
        artists = [a for a in artists if not a.get("touring", {}).get("is_touring")]

    # Sort
    if sort == "listeners":
        artists.sort(key=lambda a: a.get("monthly_listeners", 0), reverse=True)
    elif sort == "change":
        artists.sort(key=lambda a: a.get("daily_change", 0), reverse=True)
    elif sort == "events":
        artists.sort(key=lambda a: a.get("touring", {}).get("recent_event_count", 0), reverse=True)
    else:
        # Default: sort by rank
        artists.sort(key=lambda a: a.get("rank", 99999))

    total = len(artists)
    page = artists[offset:offset + limit]

    return jsonify({"artists": page, "total": total, "limit": limit, "offset": offset})


@app.route("/api/artists/summary")
def api_artists_summary():
    """Return KPI summary data without sending all artists."""
    artists = _merge_artist_data()
    total = len(artists)
    touring_count = sum(1 for a in artists if a.get("touring", {}).get("is_touring"))

    genres_set = set()
    countries_set = set()
    for a in artists:
        mb = a.get("mb", {})
        for g in mb.get("genres", []):
            if g:
                genres_set.add(g)
        c = mb.get("country")
        if c:
            countries_set.add(c)

    # Top 10 by rank
    by_rank = sorted(artists, key=lambda a: a.get("rank", 99999))
    top10 = by_rank[:10]

    return jsonify({
        "total": total,
        "touring": touring_count,
        "genres": len(genres_set),
        "countries": len(countries_set),
        "top10": top10,
    })


if __name__ == "__main__":
    app.run(debug=True, port=5001)
