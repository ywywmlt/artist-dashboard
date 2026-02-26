# Artist Dashboard — CLAUDE.md

## Overview
Scraping pipeline + web dashboard for the top 1000+ recording artists ranked by Spotify monthly listeners. The pipeline scrapes artist rankings from kworb.net, enriches them with touring data (setlist.fm), genres/socials/country (MusicBrainz), and music news (RSS feeds), then serves everything through a Flask dashboard with charts, tables, and a city/venue directory.

**GitHub:** https://github.com/alcylu/artist-dashboard
**Live:** Auto-deploys to Railway on `git push origin main`

## Stack
- Python 3.9+
- Dependencies: `requests`, `beautifulsoup4`, `musicbrainzngs`, `pandas`, `python-dotenv`, `tenacity`, `flask`, `gunicorn`, `feedparser`
- Frontend: Vanilla JS + Tailwind CSS (CDN) + Chart.js (CDN)

## Project Structure
```
├── app.py                           # Flask web server (port 5001, serves dashboard + /data/)
├── serve.py                         # Fallback HTTP server
├── Procfile                         # Railway: gunicorn app:app --bind 0.0.0.0:$PORT
├── requirements.txt                 # Python dependencies
├── .env.example                     # Environment variable template
├── config.py                        # All constants: paths, API config, rate limits, thresholds, RSS feeds
├── models.py                        # 5 dataclasses: ArtistSeed, TouringData, MusicBrainzData, ArtistEnriched, NewsAlert
├── utils.py                         # Rate limiter, retries, logging, JSON I/O, checkpointing
├── run_pipeline.py                  # CLI orchestrator (--step, --from, --to, -v)
├── ui-sample.html                   # Dashboard UI (1243 lines, 3 pages)
├── pipeline/
│   ├── __init__.py
│   ├── step1_seed_kworb.py          # Step 1: Scrape kworb.net top artists
│   ├── step3_touring_filter.py      # Step 2: setlist.fm touring status
│   ├── step4_social_handles.py      # Step 3: MusicBrainz genres, socials, country, image
│   ├── step5_export.py              # Step 4: Merge + export CSV/JSON
│   └── step6_news.py                # Step 5: RSS + Google News scraper
├── data/
│   ├── raw/                         # Intermediate JSON per step
│   │   ├── kworb_seed.json          # Step 1 output (~1000 artists)
│   │   ├── touring_data.json        # Step 2 output (touring status per artist)
│   │   ├── musicbrainz_data.json    # Step 3 output (genres, socials, country)
│   │   ├── news_alerts.json         # Step 5 output (matched news articles)
│   │   ├── .checkpoint_step2_touring       # Resumability checkpoint
│   │   └── .checkpoint_step3_musicbrainz   # Resumability checkpoint
│   ├── output/                      # Final exports (git-ignored)
│   │   ├── artists_master.csv       # Step 4 output
│   │   └── artists_master.json      # Step 4 output
│   ├── manual/
│   │   └── social_overrides.csv     # Hand-corrections for socials/country
│   └── touring-cities-venues.json   # 100 cities × ~10 venues each (static reference data)
```

**Note on file naming:** Pipeline files are numbered step1/step3/step4/step5/step6 (legacy naming). The CLI maps them to logical steps 1–5 in `run_pipeline.py`.

## Setup
```bash
cd ~/Apps/artist-dashboard
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in SETLISTFM_API_KEY and MUSICBRAINZ_CONTACT in .env
```

## API Keys Required
1. **setlist.fm** — `SETLISTFM_API_KEY` (get from api.setlist.fm)
2. **MusicBrainz** — No API key. Requires User-Agent via env vars: `MUSICBRAINZ_APP_NAME`, `MUSICBRAINZ_APP_VERSION`, `MUSICBRAINZ_CONTACT`

No Bandsintown or Spotify API keys needed. Bandsintown was removed. Spotify URLs are constructed from the ID (`https://open.spotify.com/artist/{spotify_id}`). Genres and images come from MusicBrainz.

## Web Server (Dashboard)
```bash
# Local dev
python app.py  # http://localhost:5001

# Production (Railway uses Procfile)
gunicorn app:app --bind 0.0.0.0:$PORT
```

Flask routes:
- `GET /` → serves `ui-sample.html`
- `GET /data/*` → serves static files from `data/` directory (all JSON/CSV files)

## Running Pipeline
```bash
# Full pipeline (all 5 steps)
python run_pipeline.py

# Resume from step 3
python run_pipeline.py --from 3

# Run steps 1 through 3
python run_pipeline.py --from 1 --to 3

# Run only step 1
python run_pipeline.py --step 1

# Verbose logging
python run_pipeline.py -v
```

## Pipeline Steps

| Step | Name | Source File | Runtime | Output File |
|------|------|------------|---------|-------------|
| 1 | Seed kworb.net | `step1_seed_kworb.py` | ~3s | `data/raw/kworb_seed.json` |
| 2 | Touring filter | `step3_touring_filter.py` | ~9min | `data/raw/touring_data.json` |
| 3 | MusicBrainz enrich | `step4_social_handles.py` | ~17min | `data/raw/musicbrainz_data.json` |
| 4 | Export CSV/JSON | `step5_export.py` | instant | `data/output/artists_master.{csv,json}` |
| 5 | News mentions | `step6_news.py` | ~25s | `data/raw/news_alerts.json` |
| 6 | Ticketmaster events | `step_ticketmaster.py` | ~8min | `data/raw/ticketmaster_events.json` |

### Step 1: Seed
Scrapes `https://kworb.net/spotify/listeners.html`. Parses the HTML table with BeautifulSoup, extracting rank, artist name, Spotify ID (from href), monthly listeners, daily change, and peak listeners. Saves ~1000+ artists to `kworb_seed.json`.

### Step 2: Touring Filter
For each artist, queries setlist.fm API (`/rest/1.0/search/setlists`) by artist name. Counts events in the last 2 years (`TOURING_LOOKBACK_YEARS`). Marks artist as touring if ≥5 events (`TOURING_MIN_EVENTS`). Uses checkpointing — can resume if interrupted.

### Step 3: MusicBrainz Enrich
For each artist, queries MusicBrainz via `musicbrainzngs`. Extracts genres (from tag-list), country (from area ISO code), image URL (from URL relationships/Wikimedia), and social handles (Instagram, YouTube, TikTok, Twitter/X) via regex on URL relationships. Uses checkpointing. Logs coverage stats on completion.

### Step 4: Export
Loads all three JSON files + `social_overrides.csv`. Merges on `spotify_id`, applies manual overrides (overrides take precedence), constructs Spotify URLs, sorts by monthly_listeners descending, re-ranks, and exports to CSV + JSON.

### Step 5: News
Scrapes 6 RSS feeds (Billboard, Pitchfork, NME, Rolling Stone, Consequence, Stereogum) via `feedparser`. Also fetches Google News RSS for top 20 artists (query: `"[Artist Name]" music`, max 5 articles each). Matches artist names in title + summary (skips names ≤3 chars to avoid false positives). Deduplicates by URL, sorts by date.

## Data Files

### `data/raw/kworb_seed.json`
Array of ArtistSeed objects. Fields: `rank`, `name`, `spotify_id`, `monthly_listeners`, `daily_change`, `peak_listeners`, `peak_listener_date`, `scraped_at`.

### `data/raw/touring_data.json`
Array of TouringData objects. Fields: `spotify_id`, `is_touring`, `recent_event_count`, `upcoming_event_count`, `last_event_date`, `next_event_date`, `touring_source`.

### `data/raw/musicbrainz_data.json`
Array of MusicBrainzData objects. Fields: `spotify_id`, `genres[]`, `country`, `image_url`, `instagram`, `youtube`, `tiktok`, `twitter`.

### `data/raw/news_alerts.json`
Array of NewsAlert objects. Fields: `title`, `url`, `source`, `published`, `matched_artists[]`, `matched_spotify_ids[]`, `fetched_at`.

### `data/output/artists_master.csv` / `.json`
Final merged export. ArtistEnriched schema (see Output Columns below). Git-ignored — regenerate with step 4.

### `data/manual/social_overrides.csv`
Columns: `spotify_id, instagram, youtube, tiktok, twitter, country`. Any non-empty value overrides MusicBrainz data in the export step.

### `data/touring-cities-venues.json`
Static reference data: 100 cities with ~10 venues each. Structure:
```json
{
  "metadata": { "version", "last_updated", "sources", "total_cities", "total_venues" },
  "cities": [{
    "rank", "city", "country", "region", "city_tier" (1/2/3),
    "venues": [{ "name", "venue_tier" ("A"/"B"/"C"), "capacity", "type" ("stadium"/"arena"/"theater"/"club") }]
  }]
}
```

### Checkpoint Files
`data/raw/.checkpoint_step2_touring` and `.checkpoint_step3_musicbrainz` — track processed `spotify_id`s for step resumability. Git-ignored. Cleared automatically on step completion.

## Output Columns (ArtistEnriched)
```
rank, name, spotify_id, spotify_url, monthly_listeners, genres, country,
image_url, instagram, youtube, tiktok, twitter, is_touring,
recent_event_count, upcoming_event_count, last_event_date, next_event_date,
touring_source, scraped_at
```

## Dashboard Pages

The UI (`ui-sample.html`) is a single-page app with 3 pages navigated via `showPage()`. Dark theme with glass-morphism effects.

### Page 1: Dashboard (`#page-dashboard`)
**KPI Cards (4):** Total artists, Actively touring, Unique genres, Coverage metrics.

**Charts:**
- Top 10 Artists by Monthly Listeners (bar chart, `#topArtistsChart`)
- Touring Status Breakdown (pie chart, `#touringStatusChart`)

**Data Sections:**
- Biggest Daily Movers (`#daily-movers`)
- Recently Active Artists (`#recent-touring`)
- Recent Alerts (`#dashboard-alerts`) — from `news_alerts.json`
- Upcoming Shows (`#dashboard-upcoming`)

**Artist Portfolio Table:** Paginated (25/page), filterable (All / Touring / Not Touring / No Data), sortable (Rank / Listeners / Daily Change / Recent Events). Columns: #, Artist, Monthly Listeners, Daily Change, Peak, Touring, Recent Events, Last Show.

### Page 2: Artist Profile (`#page-artist`)
Dynamic detail view populated when user clicks an artist row. Shows artist image, name, social links, touring status, and stats.

### Page 3: Cities & Venues (`#page-venues`)
**KPI Cards (5):** Total cities, Total venues, Major cities (Tier 1), Average capacity, Regional breakdown.

**Charts:**
- Cities by Region & Tier (scatter/bubble chart, `#regionChart`)
- Venue Types Breakdown (donut chart, `#venueTypeChart`)

**Capacity Ladder:** Dropdown city selector → shows venue tiers (A/B/C) with capacities (`#capacity-ladder-content`).

**City Directory Table:** Paginated (20/page), filterable by region, tier (1/2/3), and search. Columns: Rank, City, Country, Region, Tier, Venues, Largest Venue, Max Capacity.

## Dashboard Data Sources
```
ui-sample.html loads:
  /data/raw/kworb_seed.json         → Artist rankings, KPIs, portfolio table, charts
  /data/raw/touring_data.json       → Touring status, touring filter, recently active
  /data/raw/musicbrainz_data.json   → Genres, socials, country, images (optional, .catch)
  /data/raw/news_alerts.json        → News alerts section (optional, .catch)
  /data/touring-cities-venues.json  → Cities & Venues page (all sections)
```

Data merged client-side into `artists[]` array. Touring data keyed by `spotify_id` in `touringMap`, MusicBrainz data in `mbMap`.

## Models (models.py)

All use `@dataclass` with `to_dict()` method:

- **ArtistSeed** — rank, name, spotify_id, monthly_listeners, daily_change?, peak_listeners?, peak_listener_date?, scraped_at
- **TouringData** — spotify_id, is_touring, recent_event_count, upcoming_event_count, last_event_date?, next_event_date?, touring_source?
- **MusicBrainzData** — spotify_id, genres[], country?, image_url?, instagram?, youtube?, tiktok?, twitter?
- **ArtistEnriched** — All fields merged (seed + touring + MusicBrainz + Spotify URL). `genres` stored as comma-separated string for CSV.
- **NewsAlert** — title, url, source, published, matched_artists[], matched_spotify_ids[], fetched_at

## Config (config.py)

### Paths
- `BASE_DIR` / `DATA_DIR` / `RAW_DIR` / `OUTPUT_DIR` / `MANUAL_DIR`

### Rate Limits
- `SETLISTFM_RATE_LIMIT = 1` (1 req/sec)
- `MUSICBRAINZ_RATE_LIMIT = 1` (1 req/sec)
- `NEWS_RATE_LIMIT = 0.5` (2 req/sec)

### Touring Thresholds
- `TOURING_MIN_EVENTS = 5`
- `TOURING_LOOKBACK_YEARS = 2`

### News RSS Feeds
Billboard, Pitchfork, NME, Rolling Stone, Consequence, Stereogum. Plus Google News for top 20 artists (`NEWS_GOOGLE_TOP_N = 20`).

## Utilities (utils.py)

- `setup_logging(verbose)` — DEBUG or INFO level
- `get_session()` → `requests.Session` with custom User-Agent
- `save_json(data, filename, directory)` / `load_json(filename, directory)`
- `RateLimiter(requests_per_second)` — enforces minimum delay between calls
- `http_retry` — tenacity decorator: 3 attempts, exponential backoff (2–30s), retries on `RequestException`/`Timeout`
- `load_checkpoint(step_name)` / `save_checkpoint(step_name, spotify_id)` / `clear_checkpoint(step_name)` — resumability via `.checkpoint_*` files

## Manual Overrides
Edit `data/manual/social_overrides.csv` to fix incorrect social handles or country.
Columns: `spotify_id, instagram, youtube, tiktok, twitter, country`
Non-empty values override MusicBrainz data in step 4 (export).

## Patterns
- `@dataclass` for all structured data with `to_dict()` methods
- `requests.Session()` with custom User-Agent on all HTTP calls
- Config-driven — all constants in `config.py`, no hardcoding
- `tenacity` retry with exponential backoff on all HTTP calls
- Intermediate data files in `data/raw/` for step-level resumability
- Checkpoint files for within-step resumability (steps 2 and 3)
- Rate limiter class enforcing per-API delays
- Type annotations throughout
- Client-side data merging — Flask serves raw JSON, JS assembles views

## Deployment
- **Railway** auto-deploys on push to `main` via GitHub integration
- **Procfile:** `web: gunicorn app:app --bind 0.0.0.0:$PORT`
- **GitHub:** https://github.com/alcylu/artist-dashboard
- Push to deploy: `git push origin main`
