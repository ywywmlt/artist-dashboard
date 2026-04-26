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
PERSISTENT_DIR = Path(os.getenv("USER_DATA_DIR", str(DATA_DIR)))
DB_PATH = PERSISTENT_DIR / "artist_dashboard.db"

# setlist.fm
SETLISTFM_API_KEY = os.getenv("SETLISTFM_API_KEY", "")

# Ticketmaster
TICKETMASTER_API_KEY = os.getenv("TICKETMASTER_API_KEY", "")

# Auth
SECRET_KEY = os.getenv("SECRET_KEY", "")

# MusicBrainz
MUSICBRAINZ_APP_NAME = os.getenv("MUSICBRAINZ_APP_NAME", "ArtistDashboard")
MUSICBRAINZ_APP_VERSION = os.getenv("MUSICBRAINZ_APP_VERSION", "0.1")
MUSICBRAINZ_CONTACT = os.getenv("MUSICBRAINZ_CONTACT", "dev@example.com")

# Spotify API
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_RATE_LIMIT = 10  # req/sec (conservative; batch endpoint keeps total calls low)

# Rate limits (requests per second)
SETLISTFM_RATE_LIMIT = 1  # setlist.fm enforces ~1/sec
MUSICBRAINZ_RATE_LIMIT = 1  # enforced by API

# Touring filter thresholds
TOURING_MIN_EVENTS = 5          # min events in lookback period to count as "active"
TOURING_LOOKBACK_YEARS = 2      # how far back to check

# Scraping — kworb publishes 10 paginated pages of 2,500 artists each.
# Page 1 covers the top 2,500 (≥5.7M listeners), page 2 ≥3M, page 3 ≥1.5M.
# Increase KWORB_PAGE_COUNT to expand the seed; cost is ~9 min step-2 +
# 17 min step-3 per added page.
KWORB_URL = "https://kworb.net/spotify/listeners.html"
KWORB_PAGE_COUNT = 3
USER_AGENT = "ArtistDashboard/0.1 (github.com/artist-dashboard)"

# News RSS feeds
NEWS_RSS_FEEDS = {
    "Billboard": "https://www.billboard.com/music/feed/",
    "Pitchfork": "https://pitchfork.com/feed/feed-news/rss",
    "NME": "https://www.nme.com/news/music/feed",
    "Rolling Stone": "https://www.rollingstone.com/music/music-news/feed/",
    "Consequence": "https://consequence.net/feed/",
    "Stereogum": "https://www.stereogum.com/feed/",
}
NEWS_GOOGLE_TOP_N = 20        # fetch Google News RSS for top N artists
NEWS_RATE_LIMIT = 0.5         # seconds between requests (2 req/sec)
