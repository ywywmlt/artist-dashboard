# Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut initial page load payload by ~60% (8.5MB → ~3.5MB) and pipeline runtime by ~60% (26min → ~10min).

**Architecture:** Two independent tracks. Track 1 adds gzip compression and defers heavy JSON files until the page that needs them is opened. Track 2 runs pipeline steps 2+3 concurrently via ThreadPoolExecutor and adds timing instrumentation.

**Tech Stack:** flask-compress (gzip), concurrent.futures (ThreadPoolExecutor), existing Flask/vanilla JS.

---

### Task 1: Enable gzip compression

**Files:**
- Modify: `app.py:1-27` (imports and app init)
- Modify: `requirements.txt`

- [ ] **Step 1: Add flask-compress to requirements.txt**

Add `flask-compress>=1.13` after the `flask>=3.0.0` line.

- [ ] **Step 2: Enable compression in app.py**

After `app.config["SESSION_COOKIE_HTTPONLY"] = True`, add:

```python
from flask_compress import Compress
Compress(app)
```

- [ ] **Step 3: Add Cache-Control headers for static JSON**

Add an `after_request` handler in app.py after the Compress init:

```python
@app.after_request
def add_cache_headers(response):
    if request.path.startswith("/data/") and request.path.endswith(".json"):
        response.headers["Cache-Control"] = "public, max-age=300"
    return response
```

- [ ] **Step 4: Install and verify**

Run: `cd ~/artist-dashboard && .venv/bin/pip install flask-compress`
Run: `python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"`

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: 93 passed

- [ ] **Step 6: Commit**

```bash
git add app.py requirements.txt
git commit -m "Enable gzip compression and cache headers for static JSON"
```

---

### Task 2: Lazy-load heavy JSON files

**Files:**
- Modify: `ui-sample.html:1774-1826` (loadData function)

The initial `loadData()` currently fetches 9 JSON files in parallel (8.5MB total). Three of these are only needed on specific pages:

| File | Size | Used on | Lazy strategy |
|------|------|---------|---------------|
| `ticketmaster_events.json` | 2.8MB | Dashboard upcoming (8 items) + Calendar page | Load 8 items from eventsMap on init; full file deferred to calendar open |
| `rostr_intel.json` | 604KB | Dashboard signings panel + artist profile | Defer; load on first access |
| `listener_history.json` | 412KB | Artist profile momentum chart | Defer; load on first artist profile open |

**Problem:** `ticketmaster_events.json` is already loaded on init (line 1781) AND re-fetched by `loadCalendarData()` (line 4307). It's also used for dashboard upcoming shows (line 2135) and artist profile events. We can't fully defer it without breaking the dashboard.

**Solution:** Keep the initial load but make the 3 deferrable files load AFTER the dashboard renders (non-blocking). The dashboard renders immediately with seed+touring+mb+news+spotify, then the heavy files load in background.

- [ ] **Step 1: Split loadData into critical + deferred**

Replace the `loadData()` function (lines 1774-1826) with:

```javascript
async function loadData() {
  // Critical path — needed for dashboard render (~4.3MB, gzipped ~800KB)
  const [seedRes, touringRes, venueRes, newsRes, mbRes, spotifyRes] = await Promise.all([
    fetch('data/raw/kworb_seed.json').catch(() => null),
    fetch('data/raw/touring_data.json').catch(() => null),
    fetch('data/touring-cities-venues.json').catch(() => null),
    fetch('data/raw/news_alerts.json').catch(() => null),
    fetch('data/raw/musicbrainz_data.json').catch(() => null),
    fetch('data/raw/spotify_data.json').catch(() => null),
  ]);
  artists = (seedRes && seedRes.ok) ? await seedRes.json().catch(() => []) : [];
  const touringArr = (touringRes && touringRes.ok) ? await touringRes.json().catch(() => []) : [];
  touringArr.forEach(t => { touringMap[t.spotify_id] = t; });
  venueData = (venueRes && venueRes.ok) ? await venueRes.json().catch(() => ({ cities: [] })) : { cities: [] };
  if (newsRes && newsRes.ok) { window.newsAlerts = await newsRes.json(); } else { window.newsAlerts = null; }
  if (mbRes && mbRes.ok) { const mbArr = await mbRes.json(); mbArr.forEach(m => { mbMap[m.spotify_id] = m; }); }
  if (spotifyRes && spotifyRes.ok) { const spArr = await spotifyRes.json(); window.spotifyMap = {}; spArr.forEach(s => { window.spotifyMap[s.spotify_id] = s; }); } else { window.spotifyMap = null; }

  // Initialize deferred data as null (loaded on demand)
  window.rostrIntel = null;
  window.listenerHistory = null;

  // Render dashboard immediately with critical data
  // Then load deferred data in background (non-blocking)
  loadDeferredData();
}

async function loadDeferredData() {
  const [eventsRes, histRes, rostrRes] = await Promise.all([
    fetch('data/raw/ticketmaster_events.json').catch(() => null),
    fetch('data/raw/listener_history.json').catch(() => null),
    fetch('data/raw/rostr_intel.json').catch(() => null),
  ]);
  if (eventsRes && eventsRes.ok) {
    const eventsArr = await eventsRes.json();
    eventsArr.forEach(e => {
      const id = e.spotifyId || e.spotify_id;
      if (!id) return;
      if (!eventsMap[id]) eventsMap[id] = [];
      eventsMap[id].push(e);
    });
    Object.values(eventsMap).forEach(arr => arr.sort((a, b) => a.date.localeCompare(b.date)));
  }
  if (histRes && histRes.ok) { window.listenerHistory = await histRes.json(); } else { window.listenerHistory = null; }
  if (rostrRes && rostrRes.ok) { window.rostrIntel = await rostrRes.json(); } else { window.rostrIntel = null; }
  // Re-render sections that depend on deferred data
  if (typeof renderDashboardDeferred === 'function') renderDashboardDeferred();
}
```

- [ ] **Step 2: Add renderDashboardDeferred function**

After the deferred data loads, re-render the dashboard sections that need events/rostr/history. Add this function near the other dashboard render functions:

```javascript
function renderDashboardDeferred() {
  // Re-render upcoming shows (uses eventsMap)
  const upEl = document.getElementById('dashboard-upcoming');
  if (upEl) {
    const todayStr = new Date().toISOString().slice(0, 10);
    const upcoming = [];
    for (const [sid, evts] of Object.entries(eventsMap)) {
      for (const e of evts) {
        if ((e.date || '') >= todayStr) upcoming.push({ ...e, _sid: sid });
      }
    }
    upcoming.sort((a, b) => (a.date || '').localeCompare(b.date || ''));
    const toShow = upcoming.slice(0, 8);
    if (toShow.length) {
      const upBadge = document.getElementById('upcoming-badge');
      if (upBadge) { upBadge.textContent = 'LIVE'; upBadge.style.color = '#4ade80'; upBadge.style.background = 'rgba(34,197,94,0.1)'; upBadge.style.borderColor = 'rgba(34,197,94,0.2)'; }
      upEl.innerHTML = toShow.map(e => {
        const a = artists.find(x => x.spotify_id === e._sid);
        const name = a ? a.name : (e.artistName || 'Unknown Artist');
        const venue = [e.venueName, e.city, e.country].filter(Boolean).join(', ');
        const dateLabel = e.date ? new Date(e.date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—';
        const priceLabel = e.priceMin ? `<div class="text-[10px] text-emerald-400">From $${e.priceMin}</div>` : `<div class="text-[10px] text-slate-500">On Sale</div>`;
        return `<div class="flex items-center gap-3 p-2.5 rounded-lg hover:bg-white/5 transition-colors cursor-pointer" onclick="${a ? "selectArtist('" + e._sid + "')" : ''}">
          <div class="w-8 h-8 rounded-full bg-gradient-to-br ${hashColor(name)} flex items-center justify-center text-[9px] font-bold text-white flex-shrink-0">${escHtml(initials(name))}</div>
          <div class="flex-1 min-w-0">
            <div class="text-sm font-medium text-white truncate">${escHtml(name)}</div>
            <div class="text-[10px] text-slate-500 truncate">${escHtml(venue)}</div>
          </div>
          <div class="text-right flex-shrink-0">
            <div class="text-xs text-slate-300">${dateLabel}</div>
            ${priceLabel}
          </div>
        </div>`;
      }).join('');
    }
  }
  // Re-render rostr signings if loaded
  if (window.rostrIntel && typeof renderRostrSignings === 'function') {
    renderRostrSignings('all');
  }
}
```

- [ ] **Step 3: Verify JS parses**

Run: `node -e "const fs=require('fs');const h=fs.readFileSync('ui-sample.html','utf8');const s=h.match(/<script[^>]*>([\\s\\S]*?)<\\/script>/gi);let j=s.map(x=>x.replace(/<\\/?script[^>]*>/gi,'')).join('\\n');try{new Function(j);console.log('OK')}catch(e){console.log(e.message)}"`

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: 93 passed

- [ ] **Step 5: Commit**

```bash
git add ui-sample.html
git commit -m "Defer heavy JSON loading — render dashboard instantly, load events/rostr/history in background"
```

---

### Task 3: Parallelize pipeline steps 2+3

**Files:**
- Modify: `run_pipeline.py:26-38` (run_step function and main loop)

Steps 2 (touring, ~9min) and 3 (MusicBrainz, ~17min) are independent — they both read from `kworb_seed.json` and write to separate output files. Running them concurrently cuts ~17min off the pipeline.

- [ ] **Step 1: Add parallel execution support to run_pipeline.py**

Add import at top:
```python
from concurrent.futures import ThreadPoolExecutor, as_completed
```

Add parallel group config after STEPS dict:
```python
# Steps that can run concurrently (both read kworb_seed.json, write separate outputs)
PARALLEL_GROUPS = {
    (2, 3): "Touring + MusicBrainz (parallel)",
}
```

Replace the sequential loop in `main()` (lines 79-80) with:

```python
    step_num = start_step
    while step_num <= end_step:
        # Check if this step starts a parallel group
        parallel_key = None
        for group_steps in PARALLEL_GROUPS:
            if step_num == group_steps[0] and all(s <= end_step for s in group_steps):
                parallel_key = group_steps
                break

        if parallel_key:
            group_label = PARALLEL_GROUPS[parallel_key]
            logger.info(f"\n{'='*60}")
            logger.info(f"PARALLEL: {group_label}")
            logger.info(f"{'='*60}")
            group_start = time.time()
            with ThreadPoolExecutor(max_workers=len(parallel_key)) as executor:
                futures = {executor.submit(run_step, s): s for s in parallel_key}
                for future in as_completed(futures):
                    s = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Step {s} failed: {e}")
                        raise
            logger.info(f"Parallel group completed in {time.time()-group_start:.1f}s")
            step_num = max(parallel_key) + 1
        else:
            run_step(step_num)
            step_num += 1
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('run_pipeline.py').read()); print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add run_pipeline.py
git commit -m "Parallelize pipeline steps 2+3 — touring and MusicBrainz run concurrently"
```

---

### Task 4: Add timing instrumentation

**Files:**
- Modify: `run_pipeline.py` (already has per-step timing)
- Modify: `cron_pipeline.py` (already has per-step timing)

Both files already log elapsed time per step. Add a summary table at the end.

- [ ] **Step 1: Add summary table to run_pipeline.py**

After the pipeline loop, before the final log message, add:

```python
    # Print timing summary
    logger.info(f"\n{'─'*40}")
    logger.info("TIMING SUMMARY")
    logger.info(f"{'─'*40}")
    for s, elapsed in step_times:
        logger.info(f"  Step {s:>2}: {elapsed:>6.1f}s  {STEPS[s][0]}")
    logger.info(f"{'─'*40}")
```

This requires collecting `step_times` — modify `run_step` to return elapsed time and collect it in the loop.

- [ ] **Step 2: Commit**

```bash
git add run_pipeline.py
git commit -m "Add pipeline timing summary table"
```

---

### Task 5: Final QC and deploy

- [ ] **Step 1: Syntax check all modified files**
- [ ] **Step 2: Run full test suite (93 tests)**
- [ ] **Step 3: JS parse check**
- [ ] **Step 4: Push to origin main**
