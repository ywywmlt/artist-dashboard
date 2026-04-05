"""Rostr private API client.

Uses an authenticated session cookie (ROSTR_SESSION_COOKIE env var) to pull
full team and tour data for a single artist on demand. Rostr enforces a
per-account profile-view quota, so this module is built for **one-artist-at-
a-time** use only (Model Builder lookups), never bulk sync.

Endpoints consumed (all require the rack.session cookie):
    GET /v1/artist/{slug}                          — base metadata + uuid
    GET /v1/artist/{slug}/team/MANAGEMENT
    GET /v1/artist/{slug}/team/AGENCY
    GET /v1/artist/{slug}/team/RECORD_LABEL
    GET /v1/artist/{slug}/team/PUBLISHER
    GET /v2/artist/{uuid}/events                   — base64-encoded response

Design decisions:
- Sequential fetch (tour endpoint needs uuid from the base call).
- Strict timeouts and small retry count — this runs on a request-handler path.
- Quota errors raised as RostrQuotaExceeded so callers can fall back to cache.
- All secrets come from env vars; never hardcoded.
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from typing import Any

import requests

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

API_BASE = "https://api.rostr.cc"
REQUEST_TIMEOUT = 8  # seconds per call
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
TEAM_TYPES = ("MANAGEMENT", "AGENCY", "RECORD_LABEL", "PUBLISHER")


class RostrError(Exception):
    """Base exception for Rostr API failures."""


class RostrAuthMissing(RostrError):
    """ROSTR_SESSION_COOKIE env var not set."""


class RostrAuthInvalid(RostrError):
    """Session cookie rejected (401) — needs rotation."""


class RostrQuotaExceeded(RostrError):
    """Account hit the profile-view limit for the current period."""


class RostrNotFound(RostrError):
    """Slug did not resolve to an artist in Rostr's database."""


# ── Slugify ───────────────────────────────────────────────────────────────────


def slugify(name: str) -> str:
    """Convert an artist name to Rostr's slug format.

    Rostr slugs are lowercase ASCII alphanumeric only — spaces, punctuation,
    and accents are all stripped. Validated against known artists:
        "Justin Bieber" → "justinbieber"
        "The Weeknd" → "theweeknd"
        "Tyler, The Creator" → "tylerthecreator"
        "Beyoncé" → "beyonce"
        "21 Savage" → "21savage"
    """
    if not name:
        return ""
    # NFKD folds accented characters to their base form + combining marks,
    # then encoding to ASCII drops the combining marks cleanly.
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]", "", ascii_only).lower()


# ── HTTP primitives ───────────────────────────────────────────────────────────


def _get_session_cookie() -> str:
    # Strip all whitespace/newlines — Railway's variable editor can introduce
    # line breaks when pasting long cookie values.
    cookie = re.sub(r"\s+", "", os.getenv("ROSTR_SESSION_COOKIE", ""))
    if not cookie:
        raise RostrAuthMissing(
            "ROSTR_SESSION_COOKIE env var not set — cannot call Rostr API"
        )
    # Accept either bare value or "rack.session=VALUE" form
    if cookie.startswith("rack.session="):
        return cookie
    return f"rack.session={cookie}"


def _headers() -> dict[str, str]:
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "origin": "https://www.rostr.cc",
        "referer": "https://www.rostr.cc/",
        "user-agent": USER_AGENT,
        "cookie": _get_session_cookie(),
    }


def _get(url: str) -> tuple[int, bytes]:
    """Single GET with shared session headers. Returns (status, body)."""
    try:
        resp = requests.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise RostrError(f"network error: {exc}") from exc
    return resp.status_code, resp.content


def _handle_status(status: int, body: bytes, context: str) -> None:
    """Raise the right exception for non-200 responses."""
    if status == 200:
        return
    if status == 401:
        raise RostrAuthInvalid(
            f"{context}: session cookie rejected (401) — rotate ROSTR_SESSION_COOKIE"
        )
    if status == 403:
        # Rostr returns 403 for quota exhaustion with a specific msg
        text = body.decode("utf-8", errors="replace")
        if "profile views" in text.lower() or "maximum" in text.lower():
            raise RostrQuotaExceeded(f"{context}: {text.strip() or '403'}")
        raise RostrError(f"{context}: 403 forbidden — {text[:200]}")
    if status == 404:
        raise RostrNotFound(f"{context}: 404 not found")
    raise RostrError(f"{context}: HTTP {status}")


# ── Individual endpoint fetchers ──────────────────────────────────────────────


def _fetch_artist_base(slug: str) -> dict[str, Any]:
    status, body = _get(f"{API_BASE}/v1/artist/{slug}")
    _handle_status(status, body, f"/v1/artist/{slug}")
    return json.loads(body)


def _fetch_team(slug: str, team_type: str) -> list[dict[str, Any]]:
    status, body = _get(f"{API_BASE}/v1/artist/{slug}/team/{team_type}")
    _handle_status(status, body, f"/v1/artist/{slug}/team/{team_type}")
    data = json.loads(body)
    return data if isinstance(data, list) else []


def _fetch_events(uuid: str) -> dict[str, Any]:
    """Fetch upcoming events for an artist. Response is plain JSON.

    (Note: HAR exports show this body as base64 because Chrome encodes HAR
    bodies that way by default; the wire format is plain `application/json`.)
    """
    status, body = _get(f"{API_BASE}/v2/artist/{uuid}/events")
    _handle_status(status, body, f"/v2/artist/{uuid}/events")
    return json.loads(body)


# ── Normalisation helpers ─────────────────────────────────────────────────────


def _flatten_team(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip the giant Rostr team JSON down to what the dashboard renders.

    Returns a list of {company, rostrId, hqLocations, people:[{name,role}], profileUrl}.
    """
    result = []
    seen_ids = set()
    for entry in entries:
        company = entry.get("company") or {}
        rostr_id = company.get("rostrId")
        # Dedupe: Rostr often returns multiple entries for the same company
        # (one for the company, one for individual managers at that company).
        if rostr_id and rostr_id in seen_ids:
            continue
        if rostr_id:
            seen_ids.add(rostr_id)
        people = [
            {
                "name": p.get("name"),
                "role": p.get("role"),
                "rostrId": p.get("rostrId"),
            }
            for p in company.get("people", [])
            if p.get("name")
        ]
        result.append({
            "company": company.get("name"),
            "rostrId": rostr_id,
            "hqLocations": company.get("hqLocations") or [],
            "profileUrl": company.get("profileUrl"),
            "people": people,
        })
    return result


def _flatten_events(events_resp: dict[str, Any]) -> list[dict[str, Any]]:
    """Reduce the events payload to a clean list suitable for UI + cross-ref."""
    out = []
    for e in events_resp.get("events", []):
        loc = e.get("location") or {}
        out.append({
            "id": e.get("id"),
            "date": e.get("date"),  # ISO 8601 with timezone
            "ticketsAvailable": e.get("ticketsAvailable"),
            "venue": loc.get("name"),
            "city": loc.get("city"),
            "state": loc.get("state"),
            "country": loc.get("country"),
            "countryCode": loc.get("countryCode"),
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
            "url": e.get("url"),
        })
    return out


# ── Public entry point ────────────────────────────────────────────────────────


def fetch_artist(slug: str) -> dict[str, Any]:
    """Fetch full artist intel for a single slug. Returns a merged dict:

    {
      "slug": "justinbieber",
      "name": "Justin Bieber",
      "uuid": "bccde8c0-...",
      "genres": [...],
      "spotifyUrl": "...",
      "igUrl": "...",
      "management": [{company, people, ...}, ...],
      "agency": [...],
      "recordLabel": [...],
      "publisher": [...],
      "events": [{date, venue, city, country, lat, lng, url}, ...],
      "bitUrl": "https://www.bandsintown.com/..."
    }

    Raises RostrAuthMissing, RostrAuthInvalid, RostrQuotaExceeded, RostrNotFound,
    or RostrError on failure — callers should catch these and fall back.
    """
    if not slug:
        raise ValueError("slug required")

    log.info("Rostr fetch_artist: %s", slug)

    # Call 1: base info → carries the uuid needed for events
    base = _fetch_artist_base(slug)
    uuid = base.get("uuid")
    if not uuid:
        raise RostrError(f"{slug}: base response missing uuid")

    # Calls 2-5: team rosters (sequential to keep quota-error handling clean)
    teams: dict[str, list[dict[str, Any]]] = {}
    for team_type in TEAM_TYPES:
        teams[team_type] = _flatten_team(_fetch_team(slug, team_type))

    # Call 6: tour events (base64-encoded)
    try:
        events_raw = _fetch_events(uuid)
        events = _flatten_events(events_raw)
        bit_url = events_raw.get("bitUrl")
    except RostrNotFound:
        # Some artists have no events endpoint data — not fatal
        events = []
        bit_url = None

    return {
        "slug": slug,
        "name": base.get("name"),
        "uuid": uuid,
        "rostrId": base.get("rostrId"),
        "artistType": base.get("artistType"),
        "gender": base.get("gender"),
        "genres": base.get("genres") or [],
        "location": base.get("location"),
        "profileUrl": base.get("profileUrl"),
        "avatarUrl": base.get("avatarUrl"),
        "spotifyUrl": base.get("spUrl"),
        "spotifyMonthly": base.get("spMetric"),
        "igUrl": base.get("igUrl"),
        "ytUrl": base.get("ytUrl"),
        "ttUrl": base.get("ttUrl"),
        "fbUrl": base.get("fbUrl"),
        "bitOnTour": base.get("bitOnTour"),
        "management": teams["MANAGEMENT"],
        "agency": teams["AGENCY"],
        "recordLabel": teams["RECORD_LABEL"],
        "publisher": teams["PUBLISHER"],
        "events": events,
        "bitUrl": bit_url,
    }
