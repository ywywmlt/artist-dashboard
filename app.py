import os
import json
import secrets
from functools import wraps
from pathlib import Path
from flask import Flask, send_file, jsonify, request, session
from werkzeug.security import generate_password_hash, check_password_hash
import requests as http_requests
import threading
from datetime import datetime
from config import TICKETMASTER_API_KEY

SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))

app = Flask(__name__, static_folder="data", static_url_path="/data")
app.secret_key = SECRET_KEY

TICKETMASTER_BASE = "https://app.ticketmaster.com/discovery/v2/events.json"

# ── Data paths ─────────────────────────────────────────────────────────────────
# DATA_DIR is always the local data/ folder (pipeline outputs, static files).
# PERSISTENT_DIR is where user accounts and profiles are stored.
# On Railway: set USER_DATA_DIR=/mnt/data and attach a Volume at /mnt/data.
# That volume survives redeploys. Without the env var it falls back to data/
# (ephemeral, the old behaviour).
DATA_DIR = Path(__file__).parent / "data"
PERSISTENT_DIR = Path(os.getenv("USER_DATA_DIR", str(DATA_DIR)))
USERS_FILE = PERSISTENT_DIR / "users.json"
USERS_DATA_DIR = PERSISTENT_DIR / "users"

# Path to committed (git) copies — used to seed a fresh volume on first boot
_GIT_USERS_FILE = DATA_DIR / "users.json"
_GIT_USERS_DATA_DIR = DATA_DIR / "users"


def _ensure_dirs():
    DATA_DIR.mkdir(exist_ok=True)
    PERSISTENT_DIR.mkdir(parents=True, exist_ok=True)
    USERS_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _seed_volume_from_committed():
    """On first boot with a fresh volume, copy committed data into it.

    This makes the initial deploy seamless: the volume inherits the accounts
    and profiles that were last committed to git, then stays authoritative
    for all future writes (surviving every subsequent redeploy).
    """
    # Only run when USER_DATA_DIR is set (i.e. a real volume is mounted)
    # and the volume doesn't yet have a users.json.
    if PERSISTENT_DIR == DATA_DIR:
        return  # no volume configured, nothing to seed
    if USERS_FILE.exists():
        return  # volume already initialised

    # Copy users.json
    if _GIT_USERS_FILE.exists():
        try:
            USERS_FILE.write_text(_GIT_USERS_FILE.read_text())
        except Exception:
            pass

    # Copy per-user data directories
    if _GIT_USERS_DATA_DIR.exists():
        import shutil
        for user_dir in _GIT_USERS_DATA_DIR.iterdir():
            if user_dir.is_dir():
                target = USERS_DATA_DIR / user_dir.name
                if not target.exists():
                    try:
                        shutil.copytree(str(user_dir), str(target))
                    except Exception:
                        pass


def _load_users():
    _ensure_dirs()
    if not USERS_FILE.exists():
        return []
    try:
        return json.loads(USERS_FILE.read_text())
    except Exception:
        return []


def _save_users(users):
    _ensure_dirs()
    USERS_FILE.write_text(json.dumps(users, indent=2))


def _get_user(username):
    return next((u for u in _load_users() if u["username"] == username), None)


def _user_data_path(username):
    user_dir = USERS_DATA_DIR / username
    user_dir.mkdir(exist_ok=True)
    return user_dir / "data.json"


def _load_user_data(username):
    p = _user_data_path(username)
    if not p.exists():
        return {"profiles": [], "watchlist": {}, "contacts": {}, "alerts": []}
    try:
        data = json.loads(p.read_text())
        data.setdefault("alerts", [])
        return data
    except Exception:
        return {"profiles": [], "watchlist": {}, "contacts": {}, "alerts": []}


def _save_user_data(username, data):
    p = _user_data_path(username)
    p.write_text(json.dumps(data, indent=2))


def _seed_admin():
    users = _load_users()
    if users:
        return
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "changeme123")
    users = [{
        "username": admin_username,
        "password_hash": generate_password_hash(admin_password, method="pbkdf2:sha256"),
        "role": "admin"
    }]
    _save_users(users)


# On first boot with a fresh Railway volume, copy committed data into it
_ensure_dirs()
_seed_volume_from_committed()
# Seed admin on startup
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
        user = _get_user(session["username"])
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


# ── Refresh job state ──────────────────────────────────────────────────────────
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
                    base = 36  # start of TM step (news finishes at 36)
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
    """Kick off a background job to re-fetch events for all artists.

    Accepts either:
    - An authenticated browser session (login_required via session), OR
    - A CRON_SECRET token in the X-Cron-Secret header (for external schedulers).
    """
    cron_secret = os.getenv("CRON_SECRET", "")
    is_authed_session = "username" in session
    is_cron = cron_secret and request.headers.get("X-Cron-Secret") == cron_secret

    if not is_authed_session and not is_cron:
        return jsonify({"error": "Authentication required"}), 401

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


@app.route("/api/debug/spotify")
def debug_spotify():
    """Diagnostic: test Spotify credentials, checkpoint state, and first batch fetch."""
    import json as _json
    from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, RAW_DIR
    from utils import load_checkpoint
    result = {
        "client_id_set": bool(SPOTIFY_CLIENT_ID),
        "client_id_prefix": SPOTIFY_CLIENT_ID[:8] + "..." if SPOTIFY_CLIENT_ID else None,
    }
    # Checkpoint state
    done_ids = load_checkpoint("step_spotify")
    result["checkpoint_count"] = len(done_ids)
    # spotify_data.json size on disk
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
        # Fetch first real batch from kworb_seed
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
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    user = _get_user(username)
    if not user or not check_password_hash(user["password_hash"], password):
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
    data = _load_user_data(session["username"])
    return jsonify(data), 200


@app.route("/api/user-data", methods=["POST"])
@login_required
def api_save_user_data():
    data = request.get_json(force=True) or {}
    # Only persist known keys
    safe = {
        "profiles": data.get("profiles", []),
        "watchlist": data.get("watchlist", {}),
        "contacts": data.get("contacts", {}),
        "alerts": data.get("alerts", []),
    }
    _save_user_data(session["username"], safe)
    return jsonify({"ok": True}), 200


# ── Alert routes ──────────────────────────────────────────────────────────────

@app.route("/api/alerts")
@login_required
def api_get_alerts():
    """Return current user's alerts (non-dismissed)."""
    data = _load_user_data(session["username"])
    alerts = [a for a in data.get("alerts", []) if not a.get("dismissed")]
    return jsonify(alerts), 200


@app.route("/api/alerts/sync", methods=["POST"])
@login_required
def api_sync_alerts():
    """Merge new pipeline_alerts.json entries into the user's alert list."""
    pipeline_file = DATA_DIR / "raw" / "pipeline_alerts.json"
    if not pipeline_file.exists():
        return jsonify([]), 200

    try:
        pipeline_alerts = json.loads(pipeline_file.read_text())
    except Exception:
        return jsonify([]), 200

    data = _load_user_data(session["username"])
    user_alerts = data.get("alerts", [])
    existing_ids = {a["id"] for a in user_alerts}

    added = 0
    for alert in pipeline_alerts:
        if alert["id"] not in existing_ids:
            user_alerts.append(alert)
            added += 1

    # Keep at most 200 alerts per user (drop oldest dismissed first, then oldest read)
    if len(user_alerts) > 200:
        user_alerts.sort(key=lambda a: (not a.get("dismissed"), not a.get("read"), a.get("generated_at", "")))
        user_alerts = user_alerts[-200:]

    data["alerts"] = user_alerts
    _save_user_data(session["username"], data)

    active = [a for a in user_alerts if not a.get("dismissed")]
    return jsonify({"added": added, "alerts": active}), 200


@app.route("/api/alerts/<alert_id>/read", methods=["POST"])
@login_required
def api_mark_alert_read(alert_id):
    data = _load_user_data(session["username"])
    for a in data.get("alerts", []):
        if a["id"] == alert_id:
            a["read"] = True
            break
    _save_user_data(session["username"], data)
    return jsonify({"ok": True}), 200


@app.route("/api/alerts/<alert_id>/dismiss", methods=["POST"])
@login_required
def api_dismiss_alert(alert_id):
    data = _load_user_data(session["username"])
    for a in data.get("alerts", []):
        if a["id"] == alert_id:
            a["dismissed"] = True
            a["read"] = True
            break
    _save_user_data(session["username"], data)
    return jsonify({"ok": True}), 200


@app.route("/api/alerts/mark-all-read", methods=["POST"])
@login_required
def api_mark_all_read():
    data = _load_user_data(session["username"])
    for a in data.get("alerts", []):
        a["read"] = True
    _save_user_data(session["username"], data)
    return jsonify({"ok": True}), 200


# ── User management routes (admin only) ───────────────────────────────────────

@app.route("/api/users")
@admin_required
def api_list_users():
    users = _load_users()
    return jsonify([{"username": u["username"], "role": u["role"]} for u in users]), 200


@app.route("/api/users", methods=["POST"])
@admin_required
def api_create_user():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = data.get("role", "user")
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if role not in ("admin", "user"):
        return jsonify({"error": "Role must be 'admin' or 'user'"}), 400
    users = _load_users()
    if any(u["username"] == username for u in users):
        return jsonify({"error": "Username already exists"}), 409
    users.append({
        "username": username,
        "password_hash": generate_password_hash(password, method="pbkdf2:sha256"),
        "role": role,
    })
    _save_users(users)
    return jsonify({"username": username, "role": role}), 201


@app.route("/api/users/<username>", methods=["DELETE"])
@admin_required
def api_delete_user(username):
    if username == session["username"]:
        return jsonify({"error": "Cannot delete yourself"}), 400
    users = _load_users()
    new_users = [u for u in users if u["username"] != username]
    if len(new_users) == len(users):
        return jsonify({"error": "User not found"}), 404
    _save_users(new_users)
    return jsonify({"ok": True}), 200


@app.route("/api/users/<username>/password", methods=["POST"])
@admin_required
def api_reset_password(username):
    data = request.get_json(force=True) or {}
    password = data.get("password") or ""
    if not password:
        return jsonify({"error": "Password required"}), 400
    users = _load_users()
    user = next((u for u in users if u["username"] == username), None)
    if not user:
        return jsonify({"error": "User not found"}), 404
    user["password_hash"] = generate_password_hash(password, method="pbkdf2:sha256")
    _save_users(users)
    return jsonify({"ok": True}), 200


@app.route("/api/account/username", methods=["POST"])
@login_required
def api_change_username():
    data = request.get_json(force=True) or {}
    new_username = (data.get("username") or "").strip()
    if not new_username:
        return jsonify({"error": "Username required"}), 400
    users = _load_users()
    if any(u["username"] == new_username for u in users):
        return jsonify({"error": "Username already taken"}), 409
    old_username = session["username"]
    for u in users:
        if u["username"] == old_username:
            u["username"] = new_username
            break
    _save_users(users)
    # Move user data directory
    old_dir = USERS_DATA_DIR / old_username
    new_dir = USERS_DATA_DIR / new_username
    if old_dir.exists():
        old_dir.rename(new_dir)
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
    users = _load_users()
    user = next((u for u in users if u["username"] == session["username"]), None)
    if not user or not check_password_hash(user["password_hash"], current_password):
        return jsonify({"error": "Current password is incorrect"}), 403
    user["password_hash"] = generate_password_hash(new_password, method="pbkdf2:sha256")
    _save_users(users)
    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    app.run(debug=True, port=5001)
