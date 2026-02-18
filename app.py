from flask import Flask, send_file, jsonify, request
import requests as http_requests
import threading
from datetime import datetime
from config import TICKETMASTER_API_KEY

app = Flask(__name__, static_folder="data", static_url_path="/data")

TICKETMASTER_BASE = "https://app.ticketmaster.com/discovery/v2/events.json"

# ── Refresh job state ──────────────────────────────────────────────────────────
_refresh = {
    "running": False,
    "progress": 0,       # 0–100
    "message": "Idle",
    "error": None,
    "last_run": None,
}


def _run_refresh():
    def on_progress(done, total, message):
        _refresh["progress"] = int(done / total * 100) if total else 0
        _refresh["message"] = message

    try:
        from pipeline.step_ticketmaster import run
        run(progress_callback=on_progress)
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
    """Kick off a background job to re-fetch events for all artists."""
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


if __name__ == "__main__":
    app.run(debug=True, port=5001)
