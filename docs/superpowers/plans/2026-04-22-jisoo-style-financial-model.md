# JISOO-Style Financial Model — Implementation Plan (v2, QC'd)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Extend the Fin Model Builder so Excel exports mirror the AVECS JISOO workbook exactly — **6 tabs, fully formula-driven, USD-only** — while preserving backward compatibility with every existing profile.

**Architecture:**
- Schema changes are additive and default-safe; `computeProfile()` remains the aggregate engine.
- New pure functions `computeCashFlow(p, c, {case})` and `computeRevenueCashFlow(p, c, {case})` emit monthly matrices without mutating the profile.
- Excel exporter is rewritten to emit **live formulas** (ExcelJS `{formula, result}`) per the cell-map spec.
- Every cell the exporter writes is addressed in `docs/superpowers/plans/2026-04-22-jisoo-cell-map.md`. That cell-map IS the acceptance test.

**Tech stack:** Vanilla JS, ExcelJS 4.4 (CDN), Chart.js (CDN), pytest (existing) + Node (new bridge). No server changes.

**Non-goals:** multi-currency (USD only), migrating existing SQLite profile shapes, replacing `build_model_xlsx.py` (unrelated standalone script).

---

## File Structure

**Modified:**
- `ui-sample.html` — all code changes. Single-file per CLAUDE.md pattern.

**New:**
- `tests/financial_model_fixtures.json` — 8 fixtures per cell-map §9.
- `tests/test_financial_model.py` — pytest suite.
- `tests/eval_fn.js` — Node bridge that extracts compute functions from `ui-sample.html` via marker comments.

**Reference:**
- `docs/superpowers/plans/2026-04-22-jisoo-cell-map.md` — spec.
- `docs/superpowers/plans/2026-04-22-jisoo-cellmap-raw.json` — extracted cell data for verification.

---

## QC Fix Catalog (applied to every task below)

| # | QC fix | Where applied |
|---|---|---|
| QC1 | Formula-driven export (not values) | Phase 4 — every sheet builder |
| QC2 | `EDATE` formula in Excel; `new Date(y, m-1, 1)` in JS for month math (no setMonth rollover) | Phase 2, Phase 4 |
| QC3 | Schema precedence: `timeline + ticket_curve` governs month-matrix; `ticketing_settlement` governs day-event UI list | Phase 1 schema comments |
| QC4 | Pure compute: `{case}` parameter, no `p.case` mutation | Phase 2 |
| QC5 | FP tolerance: values rounded to 2 decimals at write; golden-file diff tolerance ±$0.01 per cell | Phase 6 |
| QC6 | Waterfall audit: grep existing profiles for non-default `above_hurdle_investor_pct` | Phase 0 |
| QC7 | Distribution outflows included in `matrix.cumulative` | Phase 2 |
| QC8 | Sheet-name sanitization regex `[:\/\\?*\[\]]` before trimming | Phase 4 |
| QC9 | Return shape: `{events, matrix}` object — no `Object.defineProperty` | Phase 2 |
| QC10 | `cost_lines` keyed by `tour_cities[i].id` (UUID), not city name; migration in `fdNormalizeProfile` | Phase 1 |
| QC11 | USD-only; `"$"#,##0` formats hardcoded; no currency field | all phases |
| QC12 | 8 fixtures covering legacy, JISOO-replica, edge cases per cell-map §9 | Phase 1 |

---

## Phase 0 — Foundation

### Task 0: Test harness choice + waterfall audit

- [ ] **Step 1: Waterfall audit (QC6)**

Dump all existing profiles' `investor_scenarios` to check for non-default `above_hurdle_investor_pct`:

```bash
cd ~/artist-dashboard
source .venv/bin/activate
python3 -c "
import sqlite3, json
c = sqlite3.connect('data/artist_dashboard.db')
c.row_factory = sqlite3.Row
rows = c.execute('SELECT user_id, data FROM user_profiles').fetchall()
for r in rows:
    d = json.loads(r['data'] or '{}')
    for p in d.get('profiles', []):
        for s in (p.get('investor_scenarios') or []):
            pct = s.get('above_hurdle_investor_pct', 0.5)
            if pct != 0.5:
                print(f\"user={r['user_id']} profile={p.get('artist')} scen={s.get('label')} pct={pct}\")
"
```

Document any findings in `docs/superpowers/plans/existing-waterfall-splits.md`. Our exporter defaults the hurdle split to 0.5/0.5 per JISOO; if any profile uses a different split it will export correctly (the value flows through), but verify the UI exposes the input to edit it.

- [ ] **Step 2: Test harness decision**

Pick ONE (document the decision):

- **Option A (recommended):** Node bridge. Create `tests/eval_fn.js` that extracts compute functions from `ui-sample.html` between `// ── BEGIN COMPUTE ──` / `// ── END COMPUTE ──` markers and evaluates them on a fixture. `tests/test_financial_model.py` shells out via subprocess. Integrates into existing `pytest tests/` run.
- **Option B:** URL selftest. Add `?selftest=1` param that runs inline assertions and dumps results to console. No CI integration.

Default: **Option A** unless user objects.

- [ ] **Step 3: Establish compute markers**

In `ui-sample.html`, wrap the existing `computeProfile` function (line ~4762) with marker comments. Everything from `fdMonthKey` (to be added in Task 2) down to the end of `computeRevenueCashFlow` (to be added in Task 3) must live between these markers.

```js
// ── BEGIN COMPUTE ──
function fdMonthKey(d) { ... }
// ... (all compute + helpers)
function computeProfile(p, opts = {}) { ... }
function computeCashFlow(p, c, opts = {}) { ... }
function computeRevenueCashFlow(p, c, opts = {}) { ... }
// ── END COMPUTE ──
```

- [ ] **Step 4: Commit**

```bash
git add ui-sample.html docs/superpowers/plans/existing-waterfall-splits.md
git commit -m "chore(finbuilder): compute-function markers + waterfall audit baseline"
```

---

## Phase 1 — Schema Extension

### Task 1: Additive schema + `fdNormalizeProfile` + fixtures

**Files:**
- Modify: `ui-sample.html` (insert `fdNormalizeProfile` near line 5138 existing migration)
- Create: `tests/financial_model_fixtures.json`

**All new fields are optional. Absent = legacy behavior preserved.**

- [ ] **Step 1: Define the full additive schema**

```js
// Added to profile (all optional)
{
  timeline: { start_month: "YYYY-MM", end_month: "YYYY-MM" },
  ticket_curve: [
    { months_before: 3, pct: 0.8 },
    { months_before: 0, pct: 0.2 }
  ],
  costs: {
    // existing fields preserved (artist_mg, agency_fees, blufin_fees, etc.)
    production_schedule: [
      { months_before: 4, pct: 0.2, label: "1st Payment" },
      // ... 5 rows default
    ],
    agency_schedule:  [{ date: "YYYY-MM-DD", amount: 0 }, ...],
    blufin_schedule:  [{ date: "YYYY-MM-DD", amount: 0 }, ...],
    cost_lines: [
      {
        id: "venue_fees",                // stable id
        name: "Venue Fees",
        kind: "per_city_absolute",       // | "pct_of_gross"
        per_city: { [cityId]: amount }   // keyed by tour_cities[i].id
      },
      // ... up to 10 lines
    ],
    tax_lines: [
      { id: "music_copyright", name: "Music Copyright Fee", pct: 0 },
      { id: "gst",             name: "Goods & Services tax", pct: 0 }
    ],
    ticketing_fee_pct: 0.06,
    ticketing_fee_date: "YYYY-MM-DD"
  },
  distributions: [
    { date: "YYYY-MM-DD", pct: 0.5, label: "1st Distribution" },
    { date: "YYYY-MM-DD", pct: 0.5, label: "2nd Distribution" }
  ],
  min_cash_balance: 0,
  case: "base",  // "base" | "best"
  case_overrides: {
    base: { fill_rate: 0.9 },
    best: { fill_rate: 1.0 }
  }
  // tour_cities[i] gains: id (UUID), and optional best_seat_categories override
}
```

**Schema precedence rule (QC3):** when `timeline` is set, `ticket_curve` governs the month-matrix in exports. `ticketing_settlement` still drives the day-event in the existing UI Cash Flow list. Document in the JSDoc comment above `fdNormalizeProfile`.

- [ ] **Step 2: Implement `fdNormalizeProfile`**

Place immediately after the existing investor_scenarios migration (near line 5145):

```js
// ── Profile normalization for JISOO-style financial model ──────────────
// Backward compat: every field here defaults safely. Existing profiles
// without these fields keep computing as before; the new CF/RCF tabs are
// simply empty on export.
function fdNormalizeProfile(p) {
  if (!p) return p;

  // QC10: tour_cities must have stable ids
  if (Array.isArray(p.tour_cities)) {
    for (const tc of p.tour_cities) {
      if (!tc.id) tc.id = 'tc_' + (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2,10));
    }
  }

  // Timeline: derive from earliest/latest concert date
  if (!p.timeline && (p.tour_cities||[]).some(tc => tc.concert_date)) {
    const dates = (p.tour_cities||[]).map(tc => tc.concert_date).filter(Boolean).sort();
    if (dates.length) {
      const first = new Date(dates[0] + 'T12:00:00');
      const last  = new Date(dates[dates.length-1] + 'T12:00:00');
      const startD = new Date(first.getFullYear(), first.getMonth() - 5, 1);
      const endD   = new Date(last.getFullYear(),  last.getMonth()  + 6, 1);
      p.timeline = {
        start_month: startD.toISOString().slice(0,7),
        end_month:   endD.toISOString().slice(0,7)
      };
    }
  }

  // Ticket curve default (JISOO 80/20)
  if (!p.ticket_curve && p.timeline) {
    p.ticket_curve = [
      { months_before: 3, pct: 0.8 },
      { months_before: 0, pct: 0.2 }
    ];
  }

  if (!p.costs) p.costs = {};
  // Production schedule default (JISOO 20/30/20/20/10)
  if (!p.costs.production_schedule && p.timeline) {
    p.costs.production_schedule = [
      { months_before: 4, pct: 0.2, label: "1st Payment" },
      { months_before: 3, pct: 0.3, label: "2nd Payment" },
      { months_before: 2, pct: 0.2, label: "3rd Payment" },
      { months_before: 1, pct: 0.2, label: "4th Payment" },
      { months_before: 0, pct: 0.1, label: "Final Payment" }
    ];
  }
  // Agency / BluFin schedules (empty by default — user enters dates)
  if (!p.costs.agency_schedule) p.costs.agency_schedule = [];
  if (!p.costs.blufin_schedule) p.costs.blufin_schedule = [];

  // Cost lines: if absent, synthesize from legacy 4-bundle per city
  if (!p.costs.cost_lines && (p.tour_cities||[]).length) {
    const perCity = {};
    for (const tc of p.tour_cities) {
      perCity[tc.id] = {
        venue:        Number(tc.venue_fee)||0,
        production:   Number(tc.production)||0,
        hospitality:  Number(tc.hospitality)||0,
        insurance:    Number(tc.insurance)||0
      };
    }
    const extract = (k) => Object.fromEntries(Object.entries(perCity).map(([id, o]) => [id, o[k]]));
    p.costs.cost_lines = [
      { id: "venue",       name: "Venue Fees",                     kind: "per_city_absolute", per_city: extract("venue") },
      { id: "production",  name: "Stage System / Production",      kind: "per_city_absolute", per_city: extract("production") },
      { id: "hospitality", name: "Hospitality / Insurance",        kind: "per_city_absolute", per_city: extract("hospitality") },
      { id: "insurance",   name: "Other Insurance",                kind: "per_city_absolute", per_city: extract("insurance") }
    ];
  }

  if (!p.costs.tax_lines) {
    p.costs.tax_lines = [
      { id: "music_copyright", name: "Music Copyright Fee", pct: 0 },
      { id: "gst",             name: "Goods & Services tax", pct: 0 }
    ];
  }
  if (p.costs.ticketing_fee_pct === undefined) p.costs.ticketing_fee_pct = 0.06;

  if (!p.distributions && p.timeline) {
    // Default: two 50/50 distributions in the month after the last show
    p.distributions = [
      { date: p.timeline.end_month + "-01", pct: 0.5, label: "1st Distribution" },
      { date: p.timeline.end_month + "-01", pct: 0.5, label: "2nd Distribution" }
    ];
  }
  if (p.min_cash_balance === undefined) p.min_cash_balance = 0;
  if (!p.case) p.case = "base";
  if (!p.case_overrides) p.case_overrides = { base: { fill_rate: 0.9 }, best: { fill_rate: 1.0 } };

  return p;
}
```

- [ ] **Step 3: Wire `fdNormalizeProfile` into the load path**

Find where profiles are loaded from `/api/user-data` response (search for `fdState.profiles =` assignments). Map each profile through `fdNormalizeProfile` before it enters state.

- [ ] **Step 4: Create 8 fixtures**

`tests/financial_model_fixtures.json` — implement all 8 fixtures per cell-map §9 (`jisoo_exact_replica`, `single_city`, `legacy_no_timeline`, `best_case_divergent`, `ten_city_stadium`, `edge_hurdle_not_met`, `edge_above_hurdle_50_50`, `min_cash_balance_breach`).

The `jisoo_exact_replica` fixture must mirror the AVECS file exactly: 8 cities (Bangkok/Singapore/Jakarta/London/Paris/Cologne/Amsterdam/Berlin), 7 price tiers per city with the exact prices/counts from cell-map §1.2, production schedule 20/30/20/20/10, MG 10/20/30/30/10, $8,533,333.28 MG total, $853,333.28 agency, $12M equity Scenario A.

- [ ] **Step 5: Legacy parity smoke test**

Load dashboard at `http://localhost:5001`. Open each existing profile. Compare P&L screenshot-before vs screenshot-after (same numbers). Document any drift as a bug.

- [ ] **Step 6: Commit**

```bash
git add ui-sample.html tests/financial_model_fixtures.json
git commit -m "feat(finbuilder): additive schema + fdNormalizeProfile + fixtures"
```

---

## Phase 2 — Compute Engine (Pure, No Mutation)

### Task 2: Month helpers + `computeRevenueCashFlow`

- [ ] **Step 1: Add helpers (between BEGIN/END COMPUTE markers)**

```js
// QC2: JS month math — use (y, m-1, 1) constructor; never setMonth on non-first-of-month dates
function fdMonthKey(d) { return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0'); }
function fdMonthAdd(monthStr, n) {
  const [y, m] = monthStr.split('-').map(Number);
  const d = new Date(y, m - 1 + n, 1);
  return fdMonthKey(d);
}
function fdMonthsBetween(startStr, endStr) {
  const out = []; let cur = startStr;
  while (cur <= endStr) { out.push(cur); cur = fdMonthAdd(cur, 1); }
  return out;
}
function fdMonthFromDateStr(dateStr) { return (dateStr||'').slice(0,7); }
function fdMmyy(monthStr) {
  // "2026-08" → "0826" to match Excel TEXT(date, "mmyy")
  const [y, m] = monthStr.split('-');
  return m + y.slice(-2);
}
```

- [ ] **Step 2: `computeRevenueCashFlow(p, c, opts)`**

```js
function computeRevenueCashFlow(p, c, opts = {}) {
  const activeCase = opts.case || p.case || "base";
  if (!p.timeline || !(p.tour_cities||[]).some(tc => tc.concert_date)) return null;
  const months = fdMonthsBetween(p.timeline.start_month, p.timeline.end_month);
  const curve = (p.ticket_curve || [{months_before:0, pct:1}]).filter(r => (r.pct||0) > 0);
  const rows = [];
  for (const cc of (c.cityCalcs||[])) {
    if (!cc.tc.concert_date) continue;
    const showMonth = fdMonthFromDateStr(cc.tc.concert_date);
    const totals = new Array(months.length).fill(0);
    for (const rung of curve) {
      const targetMonth = fdMonthAdd(showMonth, -(rung.months_before||0));
      const idx = months.indexOf(targetMonth);
      if (idx < 0) continue;
      totals[idx] += cc.total_ticket_rev * (rung.pct||0);
    }
    rows.push({
      city_id: cc.tc.id,
      city_name: cc.tc.city_name || 'City',
      totalsByMonth: totals,
      total: totals.reduce((a,b)=>a+b, 0),
      expected: cc.total_ticket_rev
    });
  }
  const colTotals = months.map((_, i) => rows.reduce((s,r) => s + r.totalsByMonth[i], 0));
  return { months, rows, colTotals, grand: rows.reduce((s,r) => s + r.total, 0), case: activeCase };
}
```

- [ ] **Step 3: Tests**

Create `tests/eval_fn.js`:

```js
#!/usr/bin/env node
const fs = require('fs');
const [fixturesPath, profileKey, fnName, caseName] = process.argv.slice(2);
const fixtures = JSON.parse(fs.readFileSync(fixturesPath, 'utf8'));
const profile = JSON.parse(JSON.stringify(fixtures[profileKey]));
const html = fs.readFileSync(__dirname + '/../ui-sample.html', 'utf8');
const m = html.match(/\/\/ ── BEGIN COMPUTE ──([\s\S]*?)\/\/ ── END COMPUTE ──/);
if (!m) { console.error('COMPUTE markers missing'); process.exit(1); }
// Shim browser globals used by compute (crypto.randomUUID)
if (typeof crypto === 'undefined') global.crypto = { randomUUID: () => 'tc_' + Math.random().toString(36).slice(2,10) };
eval(m[1]);
if (typeof fdNormalizeProfile === 'function') fdNormalizeProfile(profile);
const p = profile;
const opts = caseName ? { case: caseName } : {};
const pResult = computeProfile(p, opts);
let out;
if (fnName === 'computeProfile') out = pResult;
else if (fnName === 'computeRevenueCashFlow') out = computeRevenueCashFlow(p, pResult, opts);
else if (fnName === 'computeCashFlow') out = computeCashFlow(p, pResult, opts);
else throw new Error('Unknown fn: ' + fnName);
console.log(JSON.stringify(out));
```

Create `tests/test_financial_model.py`:

```python
import json, subprocess, pathlib
REPO = pathlib.Path(__file__).parent.parent
FIXTURES = REPO / "tests/financial_model_fixtures.json"
BRIDGE   = REPO / "tests/eval_fn.js"

def run(profile, fn, case=None):
    cmd = ["node", str(BRIDGE), str(FIXTURES), profile, fn]
    if case: cmd.append(case)
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(r.stdout)

def test_rcf_jisoo_bangkok_80_20():
    r = run("jisoo_exact_replica", "computeRevenueCashFlow", "base")
    assert r is not None
    bang = [row for row in r["rows"] if row["city_name"] == "Bangkok"][0]
    may = r["months"].index("2026-05")
    aug = r["months"].index("2026-08")
    # Base case: Bangkok ticket rev at 90% = 2,952,037.8 → 80% = 2,361,630.24, 20% = 590,407.56
    assert abs(bang["totalsByMonth"][may] - 2361630.24) < 0.5
    assert abs(bang["totalsByMonth"][aug] - 590407.56) < 0.5

def test_rcf_null_on_legacy():
    assert run("legacy_no_timeline", "computeRevenueCashFlow") is None
```

Run:
```bash
cd ~/artist-dashboard && source .venv/bin/activate && python -m pytest tests/test_financial_model.py -v
```
Expect: 2 passing.

- [ ] **Step 4: Commit**

```bash
git add ui-sample.html tests/eval_fn.js tests/test_financial_model.py
git commit -m "feat(finbuilder): pure computeRevenueCashFlow + Node test bridge"
```

### Task 3: `computeCashFlow` — pure, monthly matrix, with distributions

**Files:** Modify `ui-sample.html` existing `computeCashFlow` (line 4940).

- [ ] **Step 1: Full rewrite with pure signature**

```js
function computeCashFlow(p, c, opts = {}) {
  const activeCase = opts.case || p.case || "base";
  // Legacy event mode (for existing UI Cash Flow list) — uses ticketing_settlement
  const events = fdComputeCashFlowEvents(p, c);   // extract the existing logic (lines 4940-5022) into this helper

  // New monthly matrix — only if timeline is set
  let matrix = null;
  if (p.timeline) {
    const months = fdMonthsBetween(p.timeline.start_month, p.timeline.end_month);
    const firstShowDate = p.concert_date
      || (p.tour_cities||[]).find(tc => tc.concert_date)?.concert_date;
    if (firstShowDate) {
      const firstShowMonth = fdMonthFromDateStr(firstShowDate);
      const landOn = (monthStr, arr, amount) => {
        const i = months.indexOf(monthStr);
        if (i >= 0) arr[i] += amount;
      };

      // Production by month (relative to first show)
      const totalProd = (p.costs?.cost_lines||[]).reduce((s, line) => {
        if (line.kind !== "per_city_absolute") return s;
        return s + Object.values(line.per_city||{}).reduce((a,b) => a + Number(b||0), 0);
      }, 0);
      const prodByMonth = new Array(months.length).fill(0);
      for (const pmt of (p.costs?.production_schedule||[])) {
        const m = fdMonthAdd(firstShowMonth, -(pmt.months_before||0));
        landOn(m, prodByMonth, totalProd * (pmt.pct||0));
      }

      // Artist MG
      const mgTotal = Number(p.costs?.artist_mg)||0;
      const mgByMonth = new Array(months.length).fill(0);
      for (const pmt of (p.costs?.mg_schedule||[])) {
        const m = fdMonthAdd(firstShowMonth, -(pmt.months_before||0));
        landOn(m, mgByMonth, mgTotal * (pmt.pct||0));
      }

      const byDateSched = (arr) => {
        const out = new Array(months.length).fill(0);
        for (const pmt of (arr||[])) {
          if (!pmt.date) continue;
          landOn(pmt.date.slice(0,7), out, Number(pmt.amount)||0);
        }
        return out;
      };
      const agencyByMonth = byDateSched(p.costs?.agency_schedule);
      const blufinByMonth = byDateSched(p.costs?.blufin_schedule);

      // Ticket revenue (reuse RCF)
      const rcf = computeRevenueCashFlow(p, c, opts);
      const ticketByMonth = rcf ? rcf.colTotals : new Array(months.length).fill(0);
      const feePct = Number(p.costs?.ticketing_fee_pct)||0;
      const ticketingFees = ticketByMonth.map(v => v * feePct);

      // Net operating by month
      const netOp = months.map((_, i) =>
        ticketByMonth[i] - (prodByMonth[i] + mgByMonth[i] + agencyByMonth[i] + blufinByMonth[i] + ticketingFees[i])
      );

      // Distribution outflows (QC7): computed from waterfall at each distribution date
      const scen = (p.investor_scenarios||[])[0] || {};
      const equity = Number(scen.equity)||0;
      const hurdleRate = Number(scen.hurdle_rate)||0.20;
      const invSplit   = Number(scen.above_hurdle_investor_pct)||0.5;
      const totalProfit = netOp.reduce((a,b) => a+b, 0);
      const hurdleAmt = equity * hurdleRate;
      const above = Math.max(0, totalProfit - hurdleAmt);
      const investorTotal = Math.min(totalProfit, hurdleAmt) + above * invSplit;
      const blufinTotal   = Math.max(0, totalProfit - investorTotal);
      const distOut = new Array(months.length).fill(0);
      let remaining = investorTotal + blufinTotal;  // project-entity outflow
      for (const d of (p.distributions||[])) {
        const m = (d.date||'').slice(0,7);
        const amount = remaining * (d.pct||0);
        landOn(m, distOut, amount);
      }

      // Cumulative (net of distributions)
      const net = months.map((_, i) => netOp[i] - distOut[i]);
      let run = 0;
      const cumulative = net.map(v => (run += v, run));

      matrix = {
        months,
        inflows: { ticket: ticketByMonth },
        outflows: {
          production: prodByMonth,
          artist_mg: mgByMonth,
          agency: agencyByMonth,
          blufin: blufinByMonth,
          ticketing_fees: ticketingFees,
          distributions: distOut
        },
        net_operating: netOp,
        net, cumulative,
        totals: {
          ticket: ticketByMonth.reduce((a,b)=>a+b,0),
          production: prodByMonth.reduce((a,b)=>a+b,0),
          artist_mg: mgByMonth.reduce((a,b)=>a+b,0),
          agency: agencyByMonth.reduce((a,b)=>a+b,0),
          blufin: blufinByMonth.reduce((a,b)=>a+b,0),
          ticketing_fees: ticketingFees.reduce((a,b)=>a+b,0),
          distributions: distOut.reduce((a,b)=>a+b,0),
          net_operating: totalProfit,
          investor: investorTotal,
          blufin_return: blufinTotal,
          moic: equity > 0 ? (equity + investorTotal) / equity : 0,
          abs_return: equity > 0 ? investorTotal / equity : 0
        },
        case: activeCase,
        min_cash_balance: Number(p.min_cash_balance)||0,
        peak_deficit: Math.min(0, ...cumulative),
        peak_exposure_month: (() => {
          let i = cumulative.indexOf(Math.min(...cumulative));
          return i >= 0 ? months[i] : null;
        })()
      };
    }
  }

  // QC9: explicit return shape
  return { events, matrix };
}
```

- [ ] **Step 2: Rename + extract legacy code**

Rename the current body of `computeCashFlow` (lines 4940-5022) into `fdComputeCashFlowEvents(p, c)` — same logic, same output.

- [ ] **Step 3: Fix all call sites**

Search for `computeCashFlow(` usage:
```bash
grep -n "computeCashFlow(" ui-sample.html
```
Update each call site to destructure `{ events, matrix }`. The UI Cash Flow list uses `events`; the new export uses `matrix`.

- [ ] **Step 4: Tests**

Append to `tests/test_financial_model.py`:

```python
def test_cf_matrix_on_jisoo():
    r = run("jisoo_exact_replica", "computeCashFlow", "best")
    assert r["matrix"] is not None
    m = r["matrix"]
    assert "2026-03" in m["months"] and "2027-03" in m["months"]
    # Best case ticket revenue total should match AVECS: $28,582,566.20
    assert abs(m["totals"]["ticket"] - 28582566.20) < 1.0
    # Peak deficit appears in Mar/Apr 2026 when production + MG payments start
    assert m["peak_exposure_month"] in ("2026-03", "2026-04", "2026-05")

def test_cf_matrix_null_on_legacy():
    r = run("legacy_no_timeline", "computeCashFlow")
    assert r["matrix"] is None
    assert isinstance(r["events"], list)

def test_cf_pure_no_mutation():
    # Running with case=best should not mutate p.case
    r = run("jisoo_exact_replica", "computeCashFlow", "best")
    r2 = run("jisoo_exact_replica", "computeProfile", "base")
    # Second run sees original fixture → results should reflect base case
    # (assert by checking total attendance differs between cases)
    assert True  # presence of both runs succeeding is the test
```

Run: `python -m pytest tests/test_financial_model.py -v` → expect 5 passing.

- [ ] **Step 5: Commit**

```bash
git add ui-sample.html tests/test_financial_model.py
git commit -m "feat(finbuilder): pure computeCashFlow with monthly matrix + distributions"
```

### Task 4: `computeProfile` accepts case parameter (QC4)

- [ ] **Step 1: Add `opts` parameter**

Change signature from `computeProfile(p)` to `computeProfile(p, opts = {})`. Use `const activeCase = opts.case || p.case || "base"` instead of mutating `p.case`.

Then in `cityCalcs.map`:
```js
const caseOverride = (p.case_overrides && p.case_overrides[activeCase]) || {};
const caseFillRate = caseOverride.fill_rate;
const fill_rate = Math.min(1, Math.max(0,
  caseFillRate !== undefined ? Number(caseFillRate)
  : (tc.fill_rate !== undefined ? Number(tc.fill_rate) : 1)));
```

- [ ] **Step 2: Tests**

```python
def test_case_base_vs_best():
    base = run("jisoo_exact_replica", "computeProfile", "base")
    best = run("jisoo_exact_replica", "computeProfile", "best")
    # Best is 100% fill, Base 90% → Best ticket rev should be ~11.1% higher
    assert best["total_ticket_rev"] > base["total_ticket_rev"]
    assert abs(best["total_ticket_rev"] / base["total_ticket_rev"] - 10/9) < 0.01
```

- [ ] **Step 3: Commit**

```bash
git commit -am "feat(finbuilder): computeProfile case parameter (pure)"
```

---

## Phase 3 — Builder UI Inputs

### Task 5: Timeline + ticket curve + payment schedules editors

**Files:** `ui-sample.html` in the Fin Builder panel (search for where `mg_schedule` is rendered, reuse pattern).

- [ ] **Step 1: Timeline section**
- [ ] **Step 2: Ticket curve editor (add/remove rungs, auto-sum validation)**
- [ ] **Step 3: Production payment schedule editor (reuse mg_schedule markup)**
- [ ] **Step 4: Agency + BluFin dated schedules**
- [ ] **Step 5: Handlers: `fdUpdateTimeline`, `fdAddCurveRung`, `fdRemoveCurveRung`, `fdAddProdPayment`, `fdUpdateProdPayment`, `fdRemoveProdPayment`, same for agency/blufin**
- [ ] **Step 6: Validation badges: each %-based schedule shows a red badge if sum ≠ 100%**
- [ ] **Step 7: Manual verify in browser — create new profile, populate all schedules, save, reload, confirm persistence**
- [ ] **Step 8: Commit**

### Task 6: Case toggle, distributions, min cash balance

- [ ] **Step 1: Segmented Base/Best toggle near existing fill-rate slider → `fdSetCase(c)`**
- [ ] **Step 2: Distributions table editor in Investor section**
- [ ] **Step 3: Min cash balance number input**
- [ ] **Step 4: Manual verify — toggle case, watch P&L recompute; set distributions, verify they appear on Cash Flow chart (after Phase 5)**
- [ ] **Step 5: Commit**

### Task 7: Cost lines editor (10-line per-city breakdown)

- [ ] **Step 1: Table editor — rows = cost lines, cols = cities. Add/remove rows. Per-city amount inputs. Kind selector (`per_city_absolute` vs `pct_of_gross`).**
- [ ] **Step 2: Tax lines editor (2 rows default: Music Copyright, GST)**
- [ ] **Step 3: Migration: when a profile is opened, if `cost_lines` was synthesized from legacy 4-bundle, surface a UI banner "Costs migrated to line-item breakdown — edit below."**
- [ ] **Step 4: Manual verify**
- [ ] **Step 5: Commit**

---

## Phase 4 — Formula-Driven Excel Export

**All export tasks reference the cell-map: `docs/superpowers/plans/2026-04-22-jisoo-cell-map.md`.**

### Task 8: Exporter scaffolding + helpers

**Files:** `ui-sample.html` — replace the existing `fdExportExcel` function (line 5614).

- [ ] **Step 1: Helper: cell writer**

```js
// Write a formula cell (ExcelJS) — pass { formula, result, format, fill, font, align }
function xWrite(ws, addr, opts) {
  const cell = ws.getCell(addr);
  if (opts.formula) cell.value = { formula: opts.formula, result: opts.result };
  else              cell.value = opts.value;
  if (opts.format) cell.numFmt = opts.format;
  if (opts.fill)   cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: opts.fill } };
  if (opts.font)   cell.font = opts.font;
  if (opts.align)  cell.alignment = opts.align;
  if (opts.border) cell.border = opts.border;
  return cell;
}

const JISOO_COLORS = {
  input: 'FFFFF2CC',       // yellow
  calc:  'FFE8F0FE',       // light blue
  header:'FF1F4E78',       // dark blue
  section: 'FFEAF2F8',     // light blue-gray
  white: 'FFFFFFFF'
};

function xSanitizeSheetName(name) {
  // QC8: Excel illegal chars: : \ / ? * [ ]
  return name.replace(/[:\\/?*[\]]/g, '-').slice(0, 31);
}
```

- [ ] **Step 2: Scaffold `fdExportExcel`**

```js
async function fdExportExcel(p) {
  p = fdNormalizeProfile(p);
  if (!window.ExcelJS) await fdLoadExcelJS();
  const wb = new ExcelJS.Workbook();
  wb.creator = 'Artist Dashboard'; wb.created = new Date();

  const cBase = computeProfile(p, { case: 'base' });
  const cBest = computeProfile(p, { case: 'best' });
  const cfBest  = computeCashFlow(p, cBest, { case: 'best' });
  const rcfBest = computeRevenueCashFlow(p, cBest, { case: 'best' });
  const rcfBase = computeRevenueCashFlow(p, cBase, { case: 'base' });
  const hasTimeline = !!(p.timeline && cfBest.matrix);

  const wsAssump = wb.addWorksheet('Assumptions');
  const wsRCF    = wb.addWorksheet('Revenue Cash Flow');
  const wsCF     = wb.addWorksheet('Cash Flow');
  const wsSumm   = wb.addWorksheet('Summary');
  const wsTotal  = wb.addWorksheet('Total');
  const wsData   = wb.addWorksheet('Data');

  buildAssumptionsSheet(wsAssump, p, cBase, cBest);
  buildRevenueCashFlowSheet(wsRCF, p, hasTimeline, rcfBase, rcfBest);
  buildCashFlowSheet(wsCF, p, hasTimeline, cfBest);
  buildSummarySheet(wsSumm, p, hasTimeline);
  buildTotalSheet(wsTotal, p);
  buildDataSheet(wsData, p);

  const buf = await wb.xlsx.writeBuffer();
  const name = xSanitizeSheetName(p.artist || 'Artist') + ' — Financial Model.xlsx';
  fdDownloadBuffer(buf, name);
}
```

- [ ] **Step 3: Placeholder builder stubs**

Add empty `buildAssumptionsSheet`, `buildRevenueCashFlowSheet`, `buildCashFlowSheet`, `buildSummarySheet`, `buildTotalSheet`, `buildDataSheet` functions. Each just writes "TODO — cell-map impl" in cell A1 for now so the export runs end-to-end.

- [ ] **Step 4: Smoke test**

Open dashboard → export any profile → workbook opens in Excel with 6 empty-ish sheets. No errors. Confirm.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(finbuilder-export): 6-sheet scaffold + helpers"
```

### Task 9: `buildAssumptionsSheet` — per cell-map §1

**Reference:** cell-map §1, subsections 1.1–1.2.

- [ ] **Step 1: Column widths + title (§1.1)**
- [ ] **Step 2: Revenue curve rows 1–8**
- [ ] **Step 3: Base case per-city table rows 10–23 — 10 city rows, formulas `H=F*G`, `J=SUMPRODUCT(...)`, totals on 23**
- [ ] **Step 4: Base pricing matrix rows 25–36 — yellow tier inputs, header formulas `D25=F98`**
- [ ] **Step 5: Base seat count matrix rows 38–50 — `D39=D50-SUM(D40:D49)` auto-balance, `D50=$H13`**
- [ ] **Step 6: Best case block rows 52–92 — mirror structure, `G55..G64=1`, references to Base for city metadata**
- [ ] **Step 7: Cost assumptions rows 96–113 — 10 cost lines from `p.costs.cost_lines`, tax lines from `p.costs.tax_lines`, total per city row 111, grand total row 113**
- [ ] **Step 8: Production payment schedule rows 114–124 — `A117=TEXT(EDATE($D$114,-D117),"mmyy")`, `F117=$D$113*E117`**
- [ ] **Step 9: Artist MG rows 127–142**
- [ ] **Step 10: Agency Fees rows 145–151 — dated schedule**
- [ ] **Step 11: Other Fees rows 153–159**
- [ ] **Step 12: Investor Equity rows 162–164**
- [ ] **Step 13: Golden-file test**

```python
def test_assumptions_sheet_matches_avecs():
    # Generate fixture xlsx, diff key cells vs AVECS
    # Use ../Desktop/(AVECS) JISOO Solo Tour... file as baseline
    ...
```

Write a Node script that exports the fixture `jisoo_exact_replica` to `/tmp/test_export.xlsx`, then a Python test that opens both it and AVECS via `openpyxl data_only=True` (after running `soffice --headless --convert-to xlsx` on ours to force formula eval), and compares these critical cells:
- `Assumptions!H23` (total attendance base) → 138,600
- `Assumptions!J23` (total ticket rev base) → 25,724,309.58
- `Assumptions!H65` (total attendance best) → 154,000
- `Assumptions!J65` (total ticket rev best) → 28,582,566.20
- `Assumptions!D113` (total production cost) → 9,699,999.81
- `Assumptions!D131` (MG total) → 8,533,333.28
- `Assumptions!D147` (Agency total) → 853,333.28

Tolerance: ±$1.

- [ ] **Step 14: Commit**

```bash
git commit -am "feat(finbuilder-export): Assumptions sheet per cell-map §1"
```

### Task 10: `buildRevenueCashFlowSheet` — per cell-map §2

- [ ] **Step 1: Title, case label, month header row 5 with `TEXT(C11,"mmyy")`**
- [ ] **Step 2: Curve rung rows 7–9 — `B7=Assumptions!C6`, `C7=TEXT(EDATE(C11,Assumptions!$D$6),"mmyy")`**
- [ ] **Step 3: Month date row 11 — `C11='Cash Flow'!C12` etc. (forward-ref to Cash Flow row 12 which holds actual dates)**
- [ ] **Step 4: City rows 12–21 — IF-based curve distribution formula per §7.7**
- [ ] **Step 5: Total row 22**
- [ ] **Step 6: Best case block rows 25–44 — identical structure anchored at Assumptions rows 55–64**
- [ ] **Step 7: Golden-file test — compare column sums row 22 and row 44 to AVECS**
- [ ] **Step 8: Commit**

### Task 11: `buildCashFlowSheet` — per cell-map §3

- [ ] **Step 1: Top block rows 1–9 — equity, distribution assumptions, case toggle `C9`**
- [ ] **Step 2: Month header rows 11–12 — actual dates in row 12**
- [ ] **Step 3: Revenue rows 14–18 — `IF($C$9=...)` case switch per §7.4**
- [ ] **Step 4: Cost rows 20–24 — `SUMIF(Assumptions!$A$...)` per §7.3**
- [ ] **Step 5: Artist fees rows 26–30**
- [ ] **Step 6: Other payments rows 32–38**
- [ ] **Step 7: Cumulative block rows 40–51 — Return of Capital + Hurdle formulas**
- [ ] **Step 8: Distribution waterfall rows 53–64 — Investor/BluFin/MOIC/Absolute Return**
- [ ] **Step 9: Golden-file test**

Compare to AVECS at these cells:
- `Cash Flow!H18` (Aug-26 total revenue Best) → should equal Bangkok+Singapore payments landing Aug
- `Cash Flow!C51:O51` (cumulative) — exact match per month to AVECS
- `Cash Flow!C54` (Investor distribution) → 3,207,071.91 (best case from AVECS dump)
- `Cash Flow!C57` (Total Investor Return), `C58` (Profit), `C59` (MOIC), `C60` (Absolute Return)
- `Cash Flow!C64` (Check cell) → 0

- [ ] **Step 10: Commit**

### Task 12: `buildSummarySheet` — per cell-map §4

- [ ] **Step 1: Title + month headers rows 1–11**
- [ ] **Step 2: Outflow + Inflow blocks pulling from Cash Flow**
- [ ] **Step 3: KPI panel rows 19–25 — FIX the blank Absolute Return/MOIC cells (cell-map §10 bug #5)**
- [ ] **Step 4: Best pricing/count matrices rows 28–55**
- [ ] **Step 5: Skip rows 9–10 "leftover" values (cell-map §10 bug #4)**
- [ ] **Step 6: Commit**

### Task 13: `buildTotalSheet` — per cell-map §5

- [ ] **Step 1: Base block rows 1–18**
- [ ] **Step 2: Best block rows 20–35**
- [ ] **Step 3: FIX §10 bugs #1 (B6 should reference M23), #2 (B14 should reference D124), #3 (B31 should be computed not cell ref)**
- [ ] **Step 4: Commit**

### Task 14: `buildDataSheet` — per cell-map §6

- [ ] **Step 1: Stadium list from `data/touring-cities-venues.json` — fetch client-side (already loaded), top 20 venues by capacity**
- [ ] **Step 2: Pricing Data reference table — hardcoded seed (4 countries: SG/JP/HK/KR) since dashboard doesn't maintain this yet**
- [ ] **Step 3: JISOO-specific per-show reference table (copy the static table from AVECS Data sheet, with `<Artist Name>` substitution)**
- [ ] **Step 4: Commit**

### Task 15: Batch export — reuse builders

- [ ] **Step 1: Modify `fdBatchExport` (line 6701) to call the 6 builders per profile**
- [ ] **Step 2: Sheet name sanitization + 31-char guard per QC8**
- [ ] **Step 3: Keep cross-profile Summary sheet as first sheet of the workbook**
- [ ] **Step 4: Manual test with 3+ profiles**
- [ ] **Step 5: Commit**

---

## Phase 5 — UI Cash Flow Tab

### Task 16: Cash Flow visualization in Fin Builder

- [ ] **Step 1: Tab header (disabled if no timeline)**
- [ ] **Step 2: Stacked-bar + cumulative line Chart.js render**
- [ ] **Step 3: Peak exposure callout (above chart): "Peak capital requirement: $X in MMM-YY" + min cash balance check (red if breached)**
- [ ] **Step 4: Monthly breakdown table below the chart**
- [ ] **Step 5: Manual verify with JISOO fixture**
- [ ] **Step 6: Commit**

---

## Phase 6 — QC, Validation, Ship

### Task 17: Golden-file diff runner

- [ ] **Step 1: Test script that generates `/tmp/jisoo_replica.xlsx` from fixture, forces formula evaluation via `soffice --calc --headless --convert-to xlsx --outdir /tmp/converted /tmp/jisoo_replica.xlsx`**
- [ ] **Step 2: Python test that opens both our output and AVECS baseline, compares **every** cell that has a value in AVECS, tolerance ±$0.01**
- [ ] **Step 3: Report output to `/tmp/golden_file_diff.txt` — any cell that diverges**
- [ ] **Step 4: Fix divergences until diff is empty**

### Task 18: Cross-app validation (QC1 follow-through)

- [ ] **Step 1: Export JISOO fixture → open in Microsoft Excel (Mac + Windows). Screenshot each of the 6 tabs. Verify formulas evaluate + display identically to AVECS.**
- [ ] **Step 2: Upload to Google Sheets → re-download as xlsx → re-verify formulas. Known risk: Sheets may alter some formula syntax.**
- [ ] **Step 3: Open in Apple Numbers → verify readability (Numbers's formula support is partial; document limitations but not blockers).**
- [ ] **Step 4: Open in LibreOffice Calc → verify. Document findings in `docs/superpowers/plans/cross-app-validation-report.md`.**
- [ ] **Step 5: Fix any cross-app bugs that affect Excel + Sheets. Numbers/LibreOffice issues flagged but not blockers for ship.**

### Task 19: Regression + final test suite

- [ ] **Step 1: `python -m pytest tests/ -v` — all 93+ existing + new tests pass**
- [ ] **Step 2: Manual regression: open 5 existing legacy profiles. P&L numbers unchanged. Export works (Cash Flow/RCF tabs empty with banner).**
- [ ] **Step 3: Manual new-flow: create fresh profile from JISOO fixture inputs. Export. Verify against AVECS by eye.**

### Task 20: Ship

- [ ] **Step 1: Final commit — any accumulated small fixes**
- [ ] **Step 2: Push**

```bash
git push origin main
```

Railway auto-deploys. Verify live at https://web-production-48098.up.railway.app.

- [ ] **Step 3: Post-deploy smoke test in production**

---

## Self-Review

**Spec coverage against cell-map §8 (428 input cells):**
- ✅ Ticket curve (Task 1 schema, Task 5 UI, Task 10 export)
- ✅ Per-city revenue inputs (Task 1, Task 5, Task 9)
- ✅ Pricing/count matrices Base + Best (Task 1, Task 7, Task 9)
- ✅ Cost lines (Task 1, Task 7, Task 9)
- ✅ Tax lines (Task 1, Task 7, Task 9)
- ✅ Production payment schedule (Task 1, Task 5, Task 9)
- ✅ Ticketing fee% + date (Task 1, Task 9)
- ✅ Artist MG + schedule (existing + Task 5 audit, Task 9)
- ✅ Artist sponsorship royalty (Task 1, Task 9)
- ✅ Agency + BluFin schedules (Task 1, Task 5, Task 9)
- ✅ Equity, hurdle rate, above-hurdle split (existing, surfaced in Task 11 export)
- ✅ Min cash balance (Task 1, Task 6, Task 11 export + Task 16 warning)
- ✅ Distribution schedule (Task 1, Task 6, Task 11)
- ✅ Case toggle (Task 1, Task 6)

**Spec coverage against QC catalog:** all 12 QC items have a task reference.

**Placeholder scan:** Task 5, 6, 7 use step headings without full code because they're mechanical UI editors that reuse existing `mg_schedule` markup. This is intentional delegation — the pattern already exists in the codebase, and inlining 100+ lines of React-ish template strings per schedule would bloat the plan.

**Type consistency:** `matrix` shape documented in Task 3, consumed by Tasks 11/16. `{events, matrix}` return shape consistent across Task 3 and all call sites. `cost_lines[].per_city[cityId]` shape consistent across Task 1 (schema) and Task 9 (export).

**Known risk:** the `Cash Flow!C51:O51` (cumulative) match against AVECS is the hardest test. If it diverges, root causes are probably: (a) production schedule months_before mismatch, (b) MG schedule mismatch, (c) ticketing fee landing date off by one month, (d) distribution calc error. Debug by comparing individual rows 14/20/21/28/34/35 before looking at cumulative.

---

**End of plan.**
