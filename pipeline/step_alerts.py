"""Step 8: Generate pipeline alerts for listener spikes, new touring, and breaking news.

Writes data/raw/pipeline_alerts.json — a global list of raw alert objects without
user state (read/dismissed). The Flask app merges new alerts into user data on sync.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta

from config import RAW_DIR
from utils import load_json, save_json, HISTORY_FILE, compute_momentum

logger = logging.getLogger("artist_pipeline.step_alerts")

SPIKE_THRESHOLD_7D = 5.0    # % gain in 7 days to trigger listener_spike alert
DROP_THRESHOLD_7D = -5.0    # % drop in 7 days to trigger listener_drop alert
NEWS_LOOKBACK_HOURS = 48    # hours back to scan for new news mentions


def _load_history() -> dict:
    if not HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_optional(filename: str) -> list:
    try:
        return load_json(filename)
    except Exception:
        return []


def generate_listener_alerts(seed: list[dict], history: dict) -> list[dict]:
    """Generate spike/drop alerts based on 7-day momentum."""
    alerts = []
    now = datetime.now(timezone.utc).isoformat()
    for a in seed:
        sid = a.get("spotify_id")
        name = a.get("name", "Unknown")
        entries = history.get(sid, [])
        if len(entries) < 3:
            continue  # not enough data yet
        mom = compute_momentum(entries)
        m7 = mom["momentum_7d"]
        if m7 >= SPIKE_THRESHOLD_7D:
            idx_past = max(0, len(entries) - 1 - 7)
            listeners_gained = entries[-1]["listeners"] - entries[idx_past]["listeners"]
            alerts.append({
                "id": f"spike_{sid}_{entries[-1]['date']}",
                "type": "listener_spike",
                "artist_name": name,
                "spotify_id": sid,
                "message": f"{name} gained {m7:+.1f}% listeners in 7 days (+{listeners_gained:,})",
                "generated_at": now,
                "read": False,
                "dismissed": False,
            })
        elif m7 <= DROP_THRESHOLD_7D:
            idx_past = max(0, len(entries) - 1 - 7)
            listeners_lost = entries[-1]["listeners"] - entries[idx_past]["listeners"]
            alerts.append({
                "id": f"drop_{sid}_{entries[-1]['date']}",
                "type": "listener_drop",
                "artist_name": name,
                "spotify_id": sid,
                "message": f"{name} dropped {abs(m7):.1f}% listeners in 7 days ({listeners_lost:,})",
                "generated_at": now,
                "read": False,
                "dismissed": False,
            })
    return alerts


def generate_touring_alerts(seed: list[dict]) -> list[dict]:
    """Alert when an artist has upcoming events (they may have just announced a tour)."""
    alerts = []
    now = datetime.now(timezone.utc).isoformat()
    try:
        touring = {r["spotify_id"]: r for r in load_json("touring_data.json")}
    except Exception:
        return []

    # Load previous touring state to detect new announcements
    prev_file = RAW_DIR / "touring_state_prev.json"
    prev_state: dict = {}
    if prev_file.exists():
        try:
            prev_state = json.loads(prev_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    new_state = {}
    for a in seed:
        sid = a.get("spotify_id")
        t = touring.get(sid, {})
        upcoming = t.get("upcoming_event_count", 0)
        new_state[sid] = upcoming
        prev_upcoming = prev_state.get(sid, 0)
        if upcoming > 0 and prev_upcoming == 0:
            alerts.append({
                "id": f"tour_{sid}_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                "type": "new_tour",
                "artist_name": a.get("name", "Unknown"),
                "spotify_id": sid,
                "message": f"{a.get('name', 'Unknown')} has {upcoming} upcoming show{'s' if upcoming > 1 else ''} — possible new tour",
                "generated_at": now,
                "read": False,
                "dismissed": False,
            })

    # Save new state as the next prev (atomic write)
    tmp = prev_file.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(new_state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(prev_file)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return alerts


def generate_news_alerts(seed: list[dict]) -> list[dict]:
    """Alert for breaking news mentions in the last NEWS_LOOKBACK_HOURS hours."""
    alerts = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=NEWS_LOOKBACK_HOURS)
    now_iso = now.isoformat()
    news = _load_optional("news_alerts.json")

    for article in news:
        try:
            pub = datetime.fromisoformat(article.get("published", "").replace("Z", "+00:00"))
        except Exception:
            continue
        if pub < cutoff:
            continue
        matched_ids = article.get("matched_spotify_ids", [])
        matched_names = article.get("matched_artists", [])
        if not matched_ids:
            continue
        # One alert per article (can match multiple artists)
        title = article.get("title", "")[:100]
        source = article.get("source", "")
        artists_str = ", ".join(matched_names[:3]) + ("..." if len(matched_names) > 3 else "")
        alerts.append({
            "id": f"news_{article.get('url','')[-40:].replace('/','_')}",
            "type": "news_mention",
            "artist_name": matched_names[0] if matched_names else "Unknown",
            "spotify_id": matched_ids[0] if matched_ids else None,
            "message": f"[{source}] {title}",
            "artists": matched_names,
            "spotify_ids": matched_ids,
            "url": article.get("url"),
            "generated_at": now_iso,
            "read": False,
            "dismissed": False,
        })

    return alerts


def run() -> list[dict]:
    """Generate all pipeline alerts and save to pipeline_alerts.json."""
    logger.info("Step 8: Generating pipeline alerts...")

    seed = _load_optional("kworb_seed.json")
    history = _load_history()

    listener_alerts = generate_listener_alerts(seed, history)
    touring_alerts = generate_touring_alerts(seed)
    news_alerts = generate_news_alerts(seed)

    all_alerts = listener_alerts + touring_alerts + news_alerts
    save_json(all_alerts, "pipeline_alerts.json")

    logger.info(
        f"Alerts generated: {len(listener_alerts)} listener, "
        f"{len(touring_alerts)} touring, {len(news_alerts)} news "
        f"= {len(all_alerts)} total"
    )
    return all_alerts


if __name__ == "__main__":
    from utils import setup_logging
    setup_logging()
    run()
