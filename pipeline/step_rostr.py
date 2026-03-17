"""Step 9: Rostr.cc intelligence — signings, management, agency, label data.

Pulls from Rostr's public Framer search index (no auth required):
  - 126+ weekly signings pages (2022–present) → ~1,500 signing records
  - 25 featured artist profiles → management / agency / label / publisher

Outputs:
  data/raw/rostr_signings.json   — list of all parsed signings
  data/raw/rostr_intel.json      — per-artist dict keyed by lowercased name
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

from utils import get_session, save_json, RateLimiter

logger = logging.getLogger("artist_pipeline.step_rostr")

# Framer publishes all site page content into a search index — public, no auth
SEARCH_INDEX_URLS = [
    "https://framerusercontent.com/sites/6pZ2Z5K07tDk4PruqQ9sTP/searchIndex-o0mHJZ2Q1RAZ.json",
    "https://framerusercontent.com/sites/6pZ2Z5K07tDk4PruqQ9sTP/searchIndex-ufVRZYR18aWr.json",
]

SIGNING_RE = re.compile(
    r'^(.+?)\s+signed with\s+(.+?)(?:\s+for\s+(.+?))?\.?\s*$',
    re.IGNORECASE,
)

TEAM_RE = re.compile(
    r'Management:\s*(?P<mgmt>[^A-Z]*?)(?=Agency:|Label:|Publisher:|$)'
    r'|Agency:\s*(?P<agency>[^A-Z]*?)(?=Management:|Label:|Publisher:|$)'
    r'|Label:\s*(?P<label>[^A-Z]*?)(?=Management:|Agency:|Publisher:|$)'
    r'|Publisher:\s*(?P<pub>[^A-Z]*?)(?=Management:|Agency:|Label:|$)',
    re.IGNORECASE | re.DOTALL,
)

NOISE = {
    "about rostr", "sign up", "back to rostr", "jobs", "back to insider",
    "featured", "boosted", "other features", "other artists we think are dope",
    "wild rivers", "sammy rae & the friends", "anella herim", "lime garden",
    "peach tree rascals", "mini trees", "more", "hottest signings",
    "the hottest signings", "view all", "load more", "have a signing to share?",
    "click here", "ad", "advertiser", "promote something?",
}


def _normalize_deal_type(raw: str | None) -> str:
    if not raw:
        return "unknown"
    r = raw.lower()
    if "manag" in r:
        return "management"
    if "tour" in r or "book" in r:
        return "touring"
    if "record" in r or "label" in r or "distrib" in r:
        return "records"
    if "publish" in r:
        return "publishing"
    return r.strip()[:40]


def _parse_signings(pages: dict) -> list[dict]:
    """Extract structured signings from all /insider/signings/* pages."""
    results = []
    seen = set()

    for url, page in pages.items():
        if "/signings/" not in url:
            continue
        date = (page.get("h4") or [""])[0]
        for para in page.get("p", []):
            text = para.strip()
            if not text or text.lower() in NOISE or len(text) > 300:
                continue
            m = SIGNING_RE.match(text)
            if not m:
                continue
            artist = m.group(1).strip()
            company_raw = m.group(2).strip()
            deal_raw = m.group(3)
            # Skip noise strings that leak through
            if len(artist) > 60 or artist.lower() in NOISE:
                continue
            if any(w in artist.lower() for w in ("rostr", "back to", "about", "sign up")):
                continue

            # Extract contact person "of Company" pattern
            contact_person, company = None, company_raw
            of_match = re.match(r'^(.+?)\s+of\s+(.+)$', company_raw, re.IGNORECASE)
            if of_match:
                contact_person = of_match.group(1).strip()
                company = of_match.group(2).strip()

            key = (artist.lower(), company.lower(), _normalize_deal_type(deal_raw))
            if key in seen:
                continue
            seen.add(key)

            results.append({
                "artist": artist,
                "artist_key": artist.lower(),
                "company": company,
                "contact_person": contact_person,
                "deal_type": _normalize_deal_type(deal_raw),
                "date": date,
                "source_url": f"https://hq.rostr.cc{url}",
            })

    # Sort newest first (approximate — date strings like "Jun 11, 2025")
    def _date_sort(s):
        try:
            return datetime.strptime(s["date"], "%b %d, %Y")
        except Exception:
            return datetime.min

    results.sort(key=_date_sort, reverse=True)
    return results


def _parse_featured_profiles(pages: dict) -> dict[str, dict]:
    """Extract management/agency/label from featured artist profile pages."""
    intel: dict[str, dict] = {}

    for url, page in pages.items():
        if "/featured-by-rostr/artist/" not in url:
            continue
        artist_slug = url.split("/artist/")[-1]
        # Find the Team paragraph — always contains "Management:" or "Agency:"
        team_str = None
        for para in page.get("p", []):
            if "Management:" in para or "Agency:" in para or "Label:" in para:
                team_str = para
                break
        if not team_str:
            continue

        mgmt, agency, label, publisher = None, None, None, None
        for m in TEAM_RE.finditer(team_str):
            val = (m.lastgroup and m.group(m.lastgroup) or "").strip().rstrip(",")
            if not val:
                continue
            if m.lastgroup == "mgmt":
                mgmt = val
            elif m.lastgroup == "agency":
                agency = val
            elif m.lastgroup == "label":
                label = val
            elif m.lastgroup == "pub":
                publisher = val

        # Try to resolve artist name from h1
        h1 = page.get("h1", [])
        artist_name = h1[1] if len(h1) > 1 else artist_slug.replace("-", " ").title()

        # Genres from p tags (short words after nationality flag line)
        genres = []
        p_list = page.get("p", [])
        for i, p in enumerate(p_list):
            if p in ("Metal", "Rock", "Pop", "R&B", "Hip-Hop", "Country", "Electronic",
                     "Indie", "Folk", "Jazz", "Classical", "Hard Rock", "Punk",
                     "Alternative", "Soul", "Dance", "Reggae", "Latin"):
                genres.append(p)

        intel[artist_name.lower()] = {
            "artist": artist_name,
            "management": mgmt,
            "agency": agency,
            "label": label,
            "publisher": publisher,
            "genres_rostr": genres or None,
            "rostr_profile_url": f"https://hq.rostr.cc{url}",
        }

    return intel


def _build_artist_intel(signings: list[dict], profiles: dict) -> dict[str, dict]:
    """Merge signings + featured profiles into a per-artist intel dict."""
    intel: dict[str, dict] = {}

    # Start with featured profiles (richest data)
    for key, data in profiles.items():
        intel[key] = dict(data)
        intel[key].setdefault("signings", [])

    # Layer in signings
    for s in signings:
        key = s["artist_key"]
        if key not in intel:
            intel[key] = {
                "artist": s["artist"],
                "management": None,
                "agency": None,
                "label": None,
                "publisher": None,
                "rostr_profile_url": None,
                "signings": [],
            }
        intel[key]["signings"].append({
            "company": s["company"],
            "contact_person": s["contact_person"],
            "deal_type": s["deal_type"],
            "date": s["date"],
            "source_url": s["source_url"],
        })
        # Fill in management/agency/label from the most recent signing if missing
        if intel[key]["management"] is None and s["deal_type"] == "management":
            intel[key]["management"] = s["company"]
        if intel[key]["agency"] is None and s["deal_type"] == "touring":
            intel[key]["agency"] = s["company"]
        if intel[key]["label"] is None and s["deal_type"] == "records":
            intel[key]["label"] = s["company"]

    return intel


def run() -> None:
    logger.info("Step 9: Fetching Rostr intelligence data...")
    session = get_session()
    limiter = RateLimiter(requests_per_second=2)

    # Fetch both search indexes and merge
    all_pages: dict = {}
    for url in SEARCH_INDEX_URLS:
        limiter.wait()
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            # Deduplicate — second index overlaps with first
            for k, v in data.items():
                if k not in all_pages:
                    all_pages[k] = v
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")

    if not all_pages:
        logger.error("Could not fetch any Rostr search index — skipping")
        return

    signing_pages = sum(1 for k in all_pages if "/signings/" in k)
    profile_pages = sum(1 for k in all_pages if "/featured-by-rostr/artist/" in k)
    logger.info(f"  Loaded {len(all_pages)} pages ({signing_pages} signings, {profile_pages} artist profiles)")

    signings = _parse_signings(all_pages)
    profiles = _parse_featured_profiles(all_pages)
    intel = _build_artist_intel(signings, profiles)

    logger.info(f"  Parsed {len(signings)} signings, {len(profiles)} featured profiles")
    logger.info(f"  Total artists with intel: {len(intel)}")

    save_json(signings, "rostr_signings.json")
    save_json(intel, "rostr_intel.json")

    mgmt_count = sum(1 for v in intel.values() if v.get("management"))
    agency_count = sum(1 for v in intel.values() if v.get("agency"))
    label_count = sum(1 for v in intel.values() if v.get("label"))
    logger.info(
        f"  Coverage — management: {mgmt_count}, agency: {agency_count}, label: {label_count}"
    )
