"""Configuration — API keys, rate limits, thresholds."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
OUTPUT_DIR = DATA_DIR / "output"
MANUAL_DIR = DATA_DIR / "manual"

# setlist.fm
SETLISTFM_API_KEY = os.getenv("SETLISTFM_API_KEY", "")

# MusicBrainz
MUSICBRAINZ_APP_NAME = os.getenv("MUSICBRAINZ_APP_NAME", "ArtistDashboard")
MUSICBRAINZ_APP_VERSION = os.getenv("MUSICBRAINZ_APP_VERSION", "0.1")
MUSICBRAINZ_CONTACT = os.getenv("MUSICBRAINZ_CONTACT", "dev@example.com")

# Rate limits (requests per second)
SETLISTFM_RATE_LIMIT = 1  # setlist.fm enforces ~1/sec
MUSICBRAINZ_RATE_LIMIT = 1  # enforced by API

# Touring filter thresholds
TOURING_MIN_EVENTS = 5          # min events in lookback period to count as "active"
TOURING_LOOKBACK_YEARS = 2      # how far back to check

# Scraping
KWORB_URL = "https://kworb.net/spotify/listeners.html"
USER_AGENT = "ArtistDashboard/0.1 (github.com/artist-dashboard)"
