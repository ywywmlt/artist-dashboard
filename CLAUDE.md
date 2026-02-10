# Artist Dashboard — CLAUDE.md

## Overview
Scraping pipeline to build a master list of top 1000+ recording artists ranked by Spotify monthly listeners, enriched with genres, social handles, touring data, and country of origin.

## Stack
- Python 3.9+
- Dependencies: `requests`, `beautifulsoup4`, `musicbrainzngs`, `pandas`, `python-dotenv`, `tenacity`, `flask`, `gunicorn`, `feedparser`

## Project Structure
```
├── app.py                       # Flask web server (serves dashboard + data)
├── Procfile                     # Railway/Heroku process definition
├── config.py                    # API keys, rate limits, thresholds
├── models.py                    # Dataclass definitions
├── utils.py                     # Rate limiting, retries, logging, file I/O
├── run_pipeline.py              # CLI orchestrator
├── pipeline/
│   ├── step1_seed_kworb.py      # Scrape kworb.net top artists
│   ├── step3_touring_filter.py  # Bandsintown/setlist.fm touring status
│   ├── step4_social_handles.py  # MusicBrainz: genres, socials, country, image
│   ├── step5_export.py          # Merge + export CSV/JSON
│   └── step6_news.py            # RSS news feed scraper + artist matching
├── data/
│   ├── raw/                     # Intermediate JSON per step
│   ├── output/                  # Final artists_master.csv + .json
│   └── manual/                  # social_overrides.csv for hand-corrections
```

## Setup
```bash
cd ~/Apps/artist-dashboard
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in API keys in .env
```

## API Keys Required
1. **Bandsintown** — `BANDSINTOWN_APP_ID`
2. **setlist.fm** — `SETLISTFM_API_KEY` (api.setlist.fm)
3. **MusicBrainz** — No key, just User-Agent (set in .env)

Note: Spotify API removed — genres/images come from MusicBrainz, Spotify URLs constructed from ID.

## Web Server (Dashboard)
```bash
# Local dev
python app.py  # http://localhost:5001

# Production (Railway uses Procfile)
gunicorn app:app --bind 0.0.0.0:$PORT
```
Flask serves `ui-sample.html` at `/` and the `data/` directory as static files.
Railway auto-deploys via GitHub push.

## Running Pipeline
```bash
# Full pipeline (all 5 steps)
python run_pipeline.py

# Resume from step 2
python run_pipeline.py --from 2

# Run only step 1
python run_pipeline.py --step 1

# Verbose logging
python run_pipeline.py -v
```

## Pipeline Steps
1. **Seed** — Scrapes kworb.net/spotify/listeners.html (~3s)
2. **Touring Filter** — Bandsintown + setlist.fm fallback (~9min)
3. **MusicBrainz Enrich** — Genres, socials, country, images (~17min)
4. **Export** — Merge + CSV/JSON to `data/output/` (~instant)
5. **News** — RSS feeds (Billboard, Pitchfork, NME, etc.) + Google News top 20 (~25s)

Each step saves to `data/raw/` so the pipeline can resume from any point.
Checkpointing within steps means partial progress is not lost.

## Output Columns
```
rank, name, spotify_id, spotify_url, monthly_listeners, genres, country,
image_url, instagram, youtube, tiktok, twitter, is_touring,
recent_event_count, upcoming_event_count, last_event_date, next_event_date,
touring_source, scraped_at
```

## Manual Overrides
Edit `data/manual/social_overrides.csv` to fix incorrect social handles.
Columns: `spotify_id, instagram, youtube, tiktok, twitter, country`
Overrides take precedence over MusicBrainz data in the export step.

## Patterns
- `@dataclass` for all structured data
- `requests.Session()` with custom User-Agent
- Config-driven (all constants in `config.py`)
- `tenacity` retry with exponential backoff on all HTTP calls
- Intermediate data files in `data/raw/` for resumability
- Type annotations throughout
