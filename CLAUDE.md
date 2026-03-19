# Artist Dashboard — CLAUDE.md

## Overview
Scraping pipeline + web dashboard for the top 2500+ recording artists ranked by Spotify monthly listeners. The pipeline scrapes artist rankings from kworb.net, enriches them with touring data (setlist.fm), genres/socials/country (MusicBrainz), Spotify popularity/followers, Ticketmaster events, Rostr management/agency intel, and music news (RSS feeds), then serves everything through a Flask dashboard with charts, tables, and a city/venue directory.

**GitHub:** https://github.com/ywywmlt/artist-dashboard
**Live:** Auto-deploys to Railway on `git push origin main`

## Stack
- Python 3.9+
- Dependencies: `requests`, `beautifulsoup4`, `musicbrainzngs`, `pandas`, `python-dotenv`, `tenacity`, `flask`, `gunicorn`, `feedparser`, `spotipy`
- Database: SQLite (WAL mode) for user data, JSON files for pipeline data
- Frontend: Vanilla JS + Tailwind CSS (CDN) + Chart.js (CDN)
- Testing: `pytest` (93 tests)

## Project Structure
```
├── app.py                           # Flask web server (port 5001, serves dashboard + /data/ + API)
├── db.py                            # SQLite database module (user data, custom artists, migration)
├── serve.py                         # Fallback HTTP server
├── Procfile                         # Railway: gunicorn app:app --bind 0.0.0.0:$PORT
├── requirements.txt                 # Python dependencies
├── pytest.ini                       # Test configuration
├── config.py                        # All constants: paths, API config, rate limits, thresholds, DB_PATH
├── models.py                        # 6 dataclasses: ArtistSeed, TouringData, MusicBrainzData, SpotifyData, ArtistEnriched, NewsAlert
├── utils.py                         # Rate limiter, retries, logging, JSON I/O (atomic), checkpointing, listener history
├── run_pipeline.py                  # CLI orchestrator (--step, --from, --to, -v)
├── cron_pipeline.py                 # Daily cron job runner (7 steps)
├── run_spotify_careful.py           # Manual Spotify enrichment with 429 retry
├── build_model_xlsx.py              # Financial model generator (openpyxl)
├── ui-sample.html                   # Dashboard SPA (~10K lines, 8 pages)
├── pipeline/
│   ├── __init__.py
│   ├── step1_seed_kworb.py          # Step 1: Scrape kworb.net + append custom artists
│   ├── step3_touring_filter.py      # Step 2: setlist.fm touring status
│   ├── step4_social_handles.py      # Step 3: MusicBrainz genres, socials, country, image
│   ├── step5_export.py              # Step 4: Merge + export CSV/JSON (includes source field)
│   ├── step6_news.py                # Step 5: RSS + Google News scraper
│   ├── step_ticketmaster.py         # Step 6: Ticketmaster upcoming events
│   ├── step_spotify.py              # Step 7: Spotify API enrichment (popularity, followers, images)
│   ├── step_alerts.py               # Step 8: Pipeline alerts (spikes, drops, touring, news)
│   └── step_rostr.py                # Step 9: Rostr.cc management/agency/label intel
├── tests/
│   ├── conftest.py                  # Shared fixtures (Flask test client, temp dirs, sample data)
│   ├── test_utils.py                # JSON I/O, RateLimiter, checkpoints, momentum
│   ├── test_step1_kworb.py          # Kworb HTML parsing
│   ├── test_step4_musicbrainz.py    # MusicBrainz URL regex extraction
│   ├── test_step6_news.py           # News matching, date parsing
│   ├── test_step_rostr.py           # Rostr signing regex, deal types
│   ├── test_step_alerts.py          # Alert generation logic
│   ├── test_api_auth.py             # Login, logout, rate limiting, sessions
│   ├── test_api_user_data.py        # User data CRUD, account management
│   └── test_api_admin.py            # Admin user management, access control
├── data/
│   ├── artist_dashboard.db          # SQLite database (users, profiles, watchlist, contacts, alerts, custom artists)
│   ├── raw/                         # Intermediate JSON per step
│   │   ├── kworb_seed.json          # Step 1 output (~2500 artists incl. custom)
│   │   ├── touring_data.json        # Step 2 output
│   │   ├── musicbrainz_data.json    # Step 3 output
│   │   ├── news_alerts.json         # Step 5 output
│   │   ├── ticketmaster_events.json # Step 6 output (~6000 events)
│   │   ├── spotify_data.json        # Step 7 output (top 500 artists)
│   │   ├── pipeline_alerts.json     # Step 8 output
│   │   ├── rostr_intel.json         # Step 9 output
│   │   ├── listener_history.json    # Daily listener snapshots (momentum)
│   │   └── .checkpoint_*            # Resumability checkpoints
│   ├── output/                      # Final exports (git-ignored)
│   │   ├── artists_master.csv
│   │   └── artists_master.json
│   ├── manual/
│   │   └── social_overrides.csv     # Hand-corrections for socials/country
│   └── touring-cities-venues.json   # 100 cities × ~10 venues each (static)
```

**Note on file naming:** Pipeline files are numbered step1/step3/step4/step5/step6 (legacy naming). The CLI maps them to logical steps 1–5 in `run_pipeline.py`. Steps 6–9 were added later.

## Setup
```bash
cd ~/artist-dashboard
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in API keys in .env
```

## API Keys Required
1. **setlist.fm** — `SETLISTFM_API_KEY` (get from api.setlist.fm)
2. **MusicBrainz** — No API key. Requires User-Agent via env vars: `MUSICBRAINZ_APP_NAME`, `MUSICBRAINZ_APP_VERSION`, `MUSICBRAINZ_CONTACT`
3. **Ticketmaster** — `TICKETMASTER_API_KEY` (get from developer.ticketmaster.com)
4. **Spotify** — `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` (get from developer.spotify.com)

## Web Server (Dashboard)
```bash
# Local dev
python app.py  # http://localhost:5001

# Production (Railway uses Procfile)
gunicorn app:app --bind 0.0.0.0:$PORT
```

## Running Pipeline
```bash
# Full pipeline (all steps)
python run_pipeline.py

# Resume from step 3
python run_pipeline.py --from 3

# Run only step 1
python run_pipeline.py --step 1

# Verbose logging
python run_pipeline.py -v
```

## Running Tests
```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

93 tests covering: utils, pipeline parsers, API auth, user data, admin endpoints.

## Pipeline Steps

| Step | Name | Source File | Runtime | Output File |
|------|------|------------|---------|-------------|
| 1 | Seed kworb.net | `step1_seed_kworb.py` | ~3s | `kworb_seed.json` |
| 2 | Touring filter | `step3_touring_filter.py` | ~9min | `touring_data.json` |
| 3 | MusicBrainz enrich | `step4_social_handles.py` | ~17min | `musicbrainz_data.json` |
| 4 | Export CSV/JSON | `step5_export.py` | instant | `artists_master.{csv,json}` |
| 5 | News mentions | `step6_news.py` | ~25s | `news_alerts.json` |
| 6 | Ticketmaster events | `step_ticketmaster.py` | ~8min | `ticketmaster_events.json` |
| 7 | Spotify enrichment | `step_spotify.py` | ~2min | `spotify_data.json` |
| 8 | Pipeline alerts | `step_alerts.py` | instant | `pipeline_alerts.json` |
| 9 | Rostr intelligence | `step_rostr.py` | ~2min | `rostr_intel.json` |

Step 1 also appends custom artists (from SQLite `custom_artists` table) to the kworb seed.
Step 7 always includes custom artists regardless of the TOP_N_ARTISTS limit.
Step 4 preserves the `source` field ("kworb" or "custom") through to final export.

## Database (db.py)

SQLite database at `PERSISTENT_DIR / "artist_dashboard.db"` (WAL mode, foreign keys).

**Tables:**
- `users` — id, username, password_hash, role, created_at
- `user_profiles` — id (PK), user_id (FK), data (JSON blob), updated_at
- `user_watchlist` — user_id (FK), spotify_id, tag, added_at
- `user_contacts` — user_id (FK), spotify_id, data (JSON blob)
- `user_alerts` — id, user_id (FK), type, artist_name, spotify_id, message, url, generated_at, read, dismissed, extra (JSON)
- `custom_artists` — spotify_id, user_id (FK), name, added_at

**Auto-migration:** On first boot, if `users` table is empty and `users.json` exists, migrates all JSON user data into SQLite automatically.

## Flask Routes

### Public
- `GET /` → serves `ui-sample.html`
- `GET /data/*` → serves static files from `data/` directory

### Auth
- `POST /api/login` — rate-limited (10 attempts / 5 min per IP)
- `POST /api/logout`
- `GET /api/me`

### User Data (login required)
- `GET /POST /api/user-data` — profiles, watchlist, contacts, alerts
- `POST /api/alerts/sync` — merge pipeline alerts into user alerts
- `POST /api/alerts/<id>/read` | `/dismiss`
- `POST /api/alerts/mark-all-read`

### Custom Artists (login required)
- `GET /api/custom-artists` — list user's custom artists
- `POST /api/custom-artists` — add by Spotify URL or ID (validates via Spotify API)
- `DELETE /api/custom-artists/<spotify_id>`

### Admin (admin role required)
- `GET /api/users` — list users (no password hashes)
- `POST /api/users` — create user (username validation, min 8 char password)
- `DELETE /api/users/<username>`
- `POST /api/users/<username>/password`

### Account (login required)
- `POST /api/account/username` — change username (validated)
- `POST /api/account/password` — change password (requires current)

### Events
- `GET /api/events` — live Ticketmaster search
- `POST /api/events/refresh` — trigger background pipeline refresh (session or cron secret)
- `GET /api/events/refresh/status`

## Dashboard Pages

The UI (`ui-sample.html`) is a single-page app with 8 pages navigated via `showPage()`. Dark theme.

1. **Dashboard** — KPIs, charts, artist portfolio table, news alerts, upcoming shows, rostr signings, momentum leaderboard, genre heatmap
2. **Artist Profiles** — Grid view with watchlist tags, "+ Add Artist" for custom artists, compare mode, bulk actions
3. **Cities & Venues** — City/venue directory with charts, capacity ladder
4. **Tour Calendar** — Ticketmaster events with filters
5. **Financials** — Per-user financial profiles
6. **Fin. Model Builder** — Financial model builder with P&L, sensitivity analysis
7. **Reports** — Report generation
8. **Settings** — Account + user management (admin)

## Dashboard Data Sources
```
ui-sample.html loads:
  /data/raw/kworb_seed.json             → Artist rankings, KPIs, portfolio table, charts
  /data/raw/touring_data.json           → Touring status, touring filter, recently active
  /data/raw/musicbrainz_data.json       → Genres, socials, country, images
  /data/raw/news_alerts.json            → News alerts section
  /data/raw/ticketmaster_events.json    → Upcoming shows, tour calendar
  /data/raw/spotify_data.json           → Popularity, followers, artist images
  /data/raw/listener_history.json       → Momentum calculations, trend data
  /data/raw/rostr_intel.json            → Management, agency, label intel
  /data/touring-cities-venues.json      → Cities & Venues page
```

## Models (models.py)

All use `@dataclass` with `to_dict()` method:

- **ArtistSeed** — rank, name, spotify_id, monthly_listeners, daily_change?, peak_listeners?, peak_listener_date?, scraped_at, source ("kworb"/"custom")
- **TouringData** — spotify_id, is_touring, recent_event_count, upcoming_event_count, last_event_date?, next_event_date?, touring_source?
- **MusicBrainzData** — spotify_id, genres[], country?, image_url?, instagram?, youtube?, tiktok?, twitter?
- **SpotifyData** — spotify_id, popularity?, spotify_genres[], followers?, image_url_spotify?, top_tracks[]
- **ArtistEnriched** — All fields merged + momentum_7d/30d, popularity, followers, management/agency/label/publisher, rostr_profile_url, source
- **NewsAlert** — title, url, source, published, matched_artists[], matched_spotify_ids[], fetched_at

## Output Columns (ArtistEnriched)
```
rank, name, spotify_id, spotify_url, monthly_listeners, daily_change,
genres, country, image_url, instagram, youtube, tiktok, twitter,
is_touring, recent_event_count, upcoming_event_count, last_event_date,
next_event_date, touring_source, scraped_at, momentum_7d, momentum_30d,
popularity, followers, management_company, booking_agency, record_label,
publisher, rostr_profile_url, source
```

## Config (config.py)

### Paths
- `BASE_DIR` / `DATA_DIR` / `RAW_DIR` / `OUTPUT_DIR` / `MANUAL_DIR` / `PERSISTENT_DIR` / `DB_PATH`

### Rate Limits
- `SETLISTFM_RATE_LIMIT = 1` (1 req/sec)
- `MUSICBRAINZ_RATE_LIMIT = 1` (1 req/sec)
- `SPOTIFY_RATE_LIMIT = 10` (10 req/sec)
- `NEWS_RATE_LIMIT = 0.5` (2 req/sec)

## Security
- Session-based auth with `pbkdf2:sha256` password hashing
- Username validation: `^[a-zA-Z0-9_-]{1,64}$`
- Login rate limiting: 10 attempts / 5 min per IP
- Session cookies: `SameSite=Lax`, `HttpOnly=True`
- Atomic file writes (temp + rename) for all JSON saves
- Thread lock on background refresh job
- XSS prevention: `escHtml()` applied to all user-facing innerHTML
- `load_json()` returns `[]` on missing/corrupt files (no crashes)

## Patterns
- `@dataclass` for all structured data with `to_dict()` methods
- SQLite for user data (replaced JSON files), JSON for pipeline data
- `requests.Session()` with custom User-Agent on all HTTP calls
- Config-driven — all constants in `config.py`, no hardcoding
- `tenacity` retry with exponential backoff on all HTTP calls
- Intermediate data files in `data/raw/` for step-level resumability
- Checkpoint files for within-step resumability (steps 2, 3, 7)
- Rate limiter class enforcing per-API delays
- Type annotations throughout
- Client-side data merging — Flask serves raw JSON, JS assembles views

## Deployment
- **Railway** auto-deploys on push to `main` via GitHub integration
- **Procfile:** `web: gunicorn app:app --bind 0.0.0.0:$PORT`
- **Volume:** Mount at `/mnt/data`, set `USER_DATA_DIR=/mnt/data` for persistent SQLite DB
- **GitHub:** https://github.com/ywywmlt/artist-dashboard
- Push to deploy: `git push origin main`
