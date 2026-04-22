# JISOO Workbook Cell-Map (Spec for Exporter)

> **Purpose:** Exact-addressing specification for the JISOO-mirroring Excel exporter. Every cell the exporter writes must match this map — address, value/formula, number format. This IS the acceptance test.
>
> **Source:** `/Users/ywywmlt/Desktop/(AVECS) JISOO Solo Tour_Estimate_v1.20_21Apr26.xlsx`
> **Raw extract:** `2026-04-22-jisoo-cellmap-raw.json` (2,371 cells, all formulas + values + formats + fills)
> **Currency:** USD only (per user directive 2026-04-22). All `"$"#,##0` formats are hardcoded.

---

## 0. Architecture

Six sheets. **Assumptions** holds every input and the derived per-city totals. Every other sheet is pure cross-reference formulas.

```
Assumptions (source of truth)
    │
    ├── Revenue Cash Flow ─── distributes ticket rev across months via curve + EDATE
    │         │
    │         └──────────┐
    │                    ▼
    ├── Cash Flow ──── SUMIF on mmyy keys, pulls payments into months
    │         │
    │         └────┐
    │              ▼
    ├── Summary ── pure references to Cash Flow + Assumptions pricing/count matrices
    │
    └── Total ──── Base/Best aggregate P&L, Assumptions references only

Data (static) ── venue/pricing reference table, no formulas in data body
```

**Case toggle:** `Cash Flow!$C$9` holds the active case label ("Base" or "Best"). Every case-dependent formula uses `IF($C$9=Assumptions!$C$10, <base_path>, <best_path>)`. Default is "Best".

**Month-join key:** Every cell that participates in cash-flow timing derives a `mmyy` text code via `TEXT(date, "mmyy")`. Payments SUMIF on this key to land in the right month column.

**Yellow fill `FFFFF2CC`:** the 224 user-editable input cells. These are the ONLY cells the user should change. Everything else is a formula.

**Cell counts per sheet:**
| Sheet | Total | Formulas | Values | Yellow inputs |
|---|---:|---:|---:|---:|
| Assumptions | 884 | 395 | 489 | **224** |
| Cash Flow | 459 | 383 | 76 | 0 (operational inputs live on Assumptions; only `C9` case label + `F6` hurdle + `F8` min-cash + `G5/G6` splits + `J5-L7` distribution schedule are here — these are the investor-scenario inputs) |
| Revenue Cash Flow | 493 | 486 | 7 | 0 |
| Summary | 364 | 340 | 24 | 0 (a few typed "2,000,000 / 6,000,000 / 9,100,000" values at C9/D9/F9 appear to be leftover notes — **discard** in the exporter) |
| Total | 63 | 26 | 37 | 0 |
| Data | 108 | 8 | 100 | 0 (reference content; titles + table cells are values) |

---

## 1. `Assumptions` Sheet

### 1.1 Column widths (set these on the sheet)

| Col | Width | Purpose |
|---|---:|---|
| A | 8 | mmyy derived key (hidden-ish, light gray text) |
| B | 3 | left gutter |
| C | 32 | row labels |
| D | 14 | first data col / "Assumption" col |
| E | 14 | Base case first city data / "% of Cost" col |
| F–M | 14 each | 8 city data cols |
| N | 14 | 9th city (empty placeholder) |
| O | 14 | 10th city (empty placeholder) |
| P–Q | 14 | F&B and sponsorship roll-up columns |

### 1.2 Row-by-row layout

Column positions per row section. Format abbreviations: `[Y]`=yellow input, `[F]`=formula, `[v]`=static value, `[H]`=section/header style.

#### Rows 1–8: Title + Revenue Curve

| Row | Col B | Col C | Col D | Notes |
|---|---|---|---|---|
| 1 | `"Assumptions"` [H] | | | Sheet title, merged B1:Q1, dark fill |
| 3 | | `"Revenue Assumptions"` [H] | | Section header |
| 5 | | `"Ticket Sales Revenue Realized"` | `"Months before the concert"` | |
| 6 | | `0.8` [Y] | `3` [Y] | **INPUT: curve rung 1 — 80% paid 3mo before** |
| 7 | | `0.2` [Y] | `0` [Y] | **INPUT: curve rung 2 — 20% paid in-month** |
| 8 | | `0` [Y] | `0` [Y] | **INPUT: curve rung 3 (empty by default)** |

**Formula idiom:** Revenue Cash Flow references these directly (`=Assumptions!C6`, `=Assumptions!D6`) for each curve rung. If we allow more than 3 rungs, extend rows 8+, and Revenue Cash Flow needs matching rows.

#### Rows 10–23: BASE case — per-city revenue table

```
R10: A10[F]==C10   C10[v]="Base"    ← case label (referenced by toggle)
R11: A11[F]==C52                     ← "Best" label reference (for toggle comparisons)
R12: column headers (city table)
R13–R22: 10 city rows (8 populated + 2 empty)
R23: totals
```

**Row 12 headers (values, col C–Q):**
C12=`"No."`, D12=`"Country"`, E12=`"Schedule"`, F12=`"Venue Capacity"`, G12=`"Occupancy Rate"`, H12=`"Expected Attendance"`, I12=`"Avg Ticket Price"`, J12=`"Ticket Revenue"`, K12=`"Expected Merch Sales"`, L12=`"Split Received"`, M12=`"Merchandise Revenue"`, N12=`"Average F&B Spend Per Head"`, O12=`"F&B Buyers out of total Attendance"`, P12=`"F&B Revenue"`, Q12=`"Sponsorship Revenue"`.

**Row 13 (first city, Bangkok):**

| Addr | Kind | Value / Formula | Number format |
|---|---|---|---|
| A13 | F | `=TEXT(E13, "mmyy")` | `@` (text) — this is the mmyy join key |
| C13 | v/Y | `1` [Y] | `#,##0` |
| D13 | Y | `"Bangkok"` | `@` |
| E13 | Y | `2026-08-22` (date) | `d-mmm-yy` |
| F13 | Y | `20000` | `#,##0` |
| G13 | Y | `0.9` | `0%` |
| H13 | F | `=F13*G13` | `#,##0` |
| I13 | F | `=IFERROR(J13/H13, "")` | `"$"#,##0.00` |
| J13 | F | `=SUMPRODUCT(D26:D36,D39:D49)` | `"$"#,##0` ← weighted sum of prices × counts for this city |
| K13 | Y | `0` | `"$"#,##0` |
| L13 | Y | `0.2` | `0%` |
| M13 | F | `=K13*L13` | `"$"#,##0` |
| N13 | Y | `0` | `"$"#,##0` |
| O13 | Y | `20000` | `#,##0` |
| P13 | F | `=N13*O13` | `"$"#,##0` |
| Q13 | Y | `0` | `"$"#,##0` |

**Rows 14–22 (cities 2–10):** same template. `C14=C13+1` (auto-increment city number). `D14..D22` reference prices column `E..M` of the pricing matrix (see row 25): `J14=SUMPRODUCT(E$26:E$36,E$39:E$49)`, `J15=SUMPRODUCT(F$26:F$36,F$39:F$49)`, etc. — column letter in pricing matrix advances by 1 per city row.

**Row 23 (totals):**

| H23 | F | `=SUM(H13:H22)` | `#,##0` | total attendance |
| I23 | F | `=AVERAGE(I13:I22)` | `"$"#,##0.00` | avg ticket price (weighted-ish, simple AVERAGE of per-city ATP) |
| J23 | F | `=SUM(J13:J22)` | `"$"#,##0` | total ticket revenue Base |
| M23 | F | `=SUM(M13:M22)` | `"$"#,##0` | total merch rev |
| P23 | F | `=SUM(P13:P22)` | `"$"#,##0` | total F&B rev |
| Q23 | F | `=SUM(Q13:Q22)` | `"$"#,##0` | total sponsorship rev |

#### Rows 25–36: BASE case — pricing matrix (Category × City)

**Row 25 (header):** C25=`"Category / Price"`. Cols D25..M25 pull from pricing matrix labels (formulas referencing cells below — city names). Pattern:

```
D25=F98, E25=G98, F25=H98, G25=I98, H25=J98, I25=K98, J25=L98, K25=M98, L25=N98, M25=O98
```

(Row 98 is the cost-assumption header, which has city names.)

**Rows 26–32 (7 price tiers):** yellow inputs. Standard order: P5, P4, P3, P2, P1, VIP Premium, VIP Ultimate. **The tier LABEL is in column C** (C26=`"  P5"`, C27=`"  P4"`, ... C32=`"  VIP Ultimate"`).

**Prices in cols D26:M32** — all yellow, format `"$"#,##0.00`. Defaults from JISOO (Bangkok, Singapore, Jakarta, London, Paris, Cologne, Amsterdam, Berlin):

```
P5:    78.57,  92.86,  71.43, 107.14,  92.86,  85.71, 100.00, 100.00
P4:   114.29, 135.71, 100.00, 150.00, 135.71, 121.43, 142.86, 142.86
P3:   142.86, 171.43, 128.57, 192.86, 171.43, 150.00, 178.57, 178.57
P2:   171.43, 207.14, 157.14, 228.57, 207.14, 185.71, 214.29, 214.29
P1:   214.29, 250.00, 200.00, 278.57, 250.00, 221.43, 257.14, 257.14
VIPp: 285.71, 321.43, 257.14, 357.14, 321.43, 292.86, 335.71, 335.71
VIPu: 371.43, 414.29, 342.86, 464.29, 414.29, 385.71, 428.57, 428.57
```

**Rows 33–36 (empty extra tier slots):** 4 empty yellow rows in case user adds more tiers.

#### Rows 38–50: BASE case — seat-count matrix (Category × City)

**Row 38 header:** mirrors row 25 (`D38=D25`, `E38=E25`, etc.).

**Row 39 (P5 count):** **not a plain input**. It's a formula that auto-balances the total:

```
D39 = D50 - SUM(D40:D49)
```

This means the P5 count is derived — if total capacity (D50 = $H13 = F13*G13) changes or other tiers change, P5 adjusts to keep the sum matching capacity. **This is a critical invariant.** Yellow fill so user can override, but the formula enforces the balance by default.

**Rows 40–45 (P4, P3, P2, P1, VIP Premium, VIP Ultimate):** plain yellow counts. Defaults (Bangkok column):
```
P4: 3600,  P3: 4500,  P2: 3600,  P1: 2700,  VIPp: 1260,  VIPu: 540
```
(Bangkok total = 1800 + 3600 + 4500 + 3600 + 2700 + 1260 + 540 = 18,000 = 20,000 × 0.9 ✓)

**Rows 46–47:** extra slots with balancing formulas `L46=(L50-SUM(L39,L49,L48))/2` (split remainder 50/50 between two extra rows) — used by Amsterdam/Berlin which differ.

**Rows 48–49:** extra empty slots.

**Row 50 (Total):** `D50=$H13` (expected attendance for city 1), ..., `M50=$H22` (city 10).

#### Rows 52–92: BEST case — mirrors rows 10–50

Structure identical, shifted down by 42 rows.

- Row 52: `"Best"` header in C52.
- Row 54: headers (all formulas referencing row 12): `C54=C12, D54=D12, ...`
- Rows 55–64: 10 city rows. Differences from Base:
  - `G55..G64 = 1.0` (100% occupancy — hardcoded `1`, yellow)
  - `D55=D13, E55=E13, F55=F13` (city name/date/capacity **reference** Base — user doesn't re-enter)
  - `J55=SUMPRODUCT(D$68:D$78,D$81:D$91)` etc. (pricing matrix rows 68–78, count rows 81–91)
- Rows 67–78: Best pricing matrix (yellow inputs, SAME prices as Base by default — user can differentiate)
- Rows 80–92: Best seat-count matrix. Row 81 has the same auto-balance formula (`D81=D92-SUM(D82:D91)`).
- Row 92 (totals): `D92=$H55, ..., M92=$H64`.

#### Rows 96–113: Cost Assumptions table

**Row 98 header:** C98=`"Particulars"`, D98=`"Notes"`, E98=`"Assumption"`, F98..M98 = **city name formulas** (`F98=D13, G98=D14, ... M98=D20`). These are the canonical city-name references used by rows 25 and 38 headers.

**Rows 99–108 (10 cost lines, all variable, yellow inputs per city):**

| Row | Line name (col C) | Col D ("Notes") | Cols F..M (per-city $) |
|---|---|---|---|
| 99 | `Venue Fees` | `Variable` | 186666.66, 233333.33, 166666.66, 280000, 260000, 240000, 213333.33, 206666.66 |
| 100 | `Stage System` | `Variable` | 333333.33, 346666.66, 320000, 386666.66, 380000, 366666.66, 333333.33, 333333.33 |
| 101 | `Hospitality & Public Liability Insurance` | `Variable` | 80000, 86666.66, 86666.66, 100000, 93333.33, 86666.66, 86666.66, 86666.66 |
| 102 | `Advertising & Promotion` | `Variable` | 146666.66, 133333.33, 133333.33, 166666.66, 160000, 140000, 133333.33, 133333.33 |
| 103 | `Part Time Staffing` | `Variable` | 120000, 133333.33, 113333.33, 153333.33, 146666.66, 140000, 133333.33, 133333.33 |
| 104 | `Licenses & Permits` | `Variable` | 140000, 93333.33, 173333.33, 106666.66, 93333.33, 120000, 80000, 86666.66 |
| 105 | `Logistics & Transportation & Business & Accommodation` | `Variable` | 160000, 140000, 173333.33, 173333.33, 166666.66, 173333.33, 153333.33, 153333.33 |
| 106 | `Cancellation/Postponement Insurance to cover gross sales profit` | `Variable` | 0 (for all cities) |
| 107 | `Catering & Backstage Groceries` | `Variable` | 0 |
| 108 | `Miscellaneous Costs` | `Variable` | 0 |

**Rows 109–110 (percentage-based, case-aware):**

| Row | Line | Col D (Notes) | Col E | Cols F..M |
|---|---|---|---|---|
| 109 | `Music Copyright Fee` | `as a % of Gross Revenue` | `0` [Y, default %] | `=IF('Cash Flow'!$C$9=Assumptions!$C$10, <base_city_gross>*$E$109, <best_city_gross>*$E$109)` |
| 110 | `Goods & Services tax` | `as a % of Gross Revenue` | `0` [Y, default %] | same formula pattern as 109 |

**Row 111 (Total per city):** `F111=SUM(F99:F110), G111=SUM(G99:G110), ..., O111=SUM(O99:O110)`.

**Row 113:** `C113="Total Production Cost"`, `D113=SUM(F111:O111)`. **This is the grand total referenced by payment schedules.**

#### Rows 114–124: Production Payment Schedule

| Addr | Kind | Content |
|---|---|---|
| C114 | v | `"Concert Start Date"` |
| D114 | F | `=E13` (first show date) |
| C116 | v | `"Payment Schedule"` |
| D116 | v | `"Months before the first concert"` |
| E116 | v | `"% of Cost"` |
| F116 | v | `"Total Amount"` |
| C117 | v | `"1st Payment"` |
| A117 | F | `=TEXT(EDATE($D$114, -D117),"mmyy")` ← **month-shift join key** |
| D117 | Y | `4` (months before) |
| E117 | Y | `0.2` (20%) |
| F117 | F | `=$D$113*E117` |
| (rows 118–121) | | 2nd (-3,30%), 3rd (-2,20%), 4th (-1,20%), Final (-0,10%) — same pattern |
| C122 | v | `"Total"` |
| E122 | F | `=SUM(E117:E121)` ← **must equal 1.0 — validation** |
| F122 | F | `=SUM(F117:F121)` ← total matches D113 |

**Row 124:** Ticketing Platform Fees

| A124 | F | `=TEXT($E124,"mmyy")` |
| C124 | v | `"Ticketing Platform Fees %"` |
| D124 | Y | `0.06` (6%) |
| E124 | Y | `2026-08-01` (date fee posts) |

#### Rows 127–142: Artist MG (JISOO) Payment Schedule

| C127 | v | `"Fees and Loyalty"` |
| C129 | v | `"JISOO Fees and Royalty"` |
| C131 | v | `"MG Payment to JISOO"` |
| D131 | F | `=1066666.66*8` ← **this is JISOO-specific. Generalize to `=<per_show_mg> * <num_shows>` or a plain yellow input** |
| C132 | v | `"Concert Start Date"` |
| D132 | F | `=D114` |

**Payment rows 135–139** (5 tranches):

```
C135 = "1st Payment",   D135 = 4,  E135 = 0.10,   F135 = =E135*$D$131,   A135 = =TEXT(EDATE($D$132,-D135),"mmyy")
C136 = "2nd Payment",   D136 = 3,  E136 = 0.20,   F136 = =E136*$D$131,   A136 similar
C137 = "3rd Payment",   D137 = 2,  E137 = 0.30,   F137 = =E137*$D$131
C138 = "4th Payment",   D138 = 1,  E138 = 0.30,   F138 = =E138*$D$131
C139 = "5th Payment",   D139 = 0,  E139 = 0.10,   F139 = =E139*$D$131
F140 = =SUM(F135:F139)
```

**Row 142:** `C142="JISOO Sponsorship Royalty"`, `D142=0` (yellow, % of sponsorship rev).

#### Rows 145–151: Agency Fees

```
C145 = "Agency Fees"
C147 = "Agency Fees Upfront",   D147 = =106666.66*8     ← generalize to yellow input
C149 = "Payment Schedule",      D149 = "Date",  E149 = "Total Amount"
C150 = "1st Payment",   A150 = =TEXT($D150,"mmyy"),   D150 = 2026-03-01 [Y],   E150 = =D147*0.1  [Y: fraction]
C151 = "2nd Payment",   A151 = =TEXT($D151,"mmyy"),   D151 = 2026-06-01 [Y],   E151 = =D147-E150
```

**Note:** Agency has dated (not month-offset) schedule. `E151 = D147 - E150` balances to exact total. User edits the fractional pct in E150; the rest is derived.

#### Rows 153–159: Other Fees (BluFin)

Structure identical to Agency:
```
C153 = "Other Fees"
C155 = "Other Fees",   D155 = 0 [Y]
C157 = "Payment Schedule"
C158 = "1st Payment",   A158 = =TEXT($D158,"mmyy"),  D158 = 2026-03-01 [Y],  E158 = 0 [Y]
C159 = "2nd Payment",   A159 = =TEXT($D159,"mmyy"),  D159 = 2026-06-01 [Y],  E159 = =D155-E158
```

#### Rows 162–164: Investor's Equity Requirement

```
C162 = "Investor's Equity Requirement"
C164 = "Equity",   D164 = 0 [Y: total equity amount]
```

**Referenced by Cash Flow:** `Cash Flow!C4 = =Assumptions!$D$164`.

---

## 2. `Revenue Cash Flow` Sheet

Distributes per-city ticket revenue across the 13 monthly columns using the ticket curve.

### 2.1 Layout

| Row | Content |
|---|---|
| 1 | Title `"Ticket Revenue Cash Flow"` (merged, dark header) |
| 3 | `B3="Case"`, `C3==Assumptions!$C$10` (label "Base") |
| 5 | Month mmyy header: `C5=TEXT(C11,"mmyy")`, ..., `O5=TEXT(O11,"mmyy")` |
| 7 | Curve rung 1: `B7=Assumptions!C6` (0.8), `C7=TEXT(EDATE(C11, Assumptions!$D$6),"mmyy")`, ..., `O7` same pattern |
| 8 | Curve rung 2: `B8=Assumptions!C7` (0.2), `C8=TEXT(EDATE(C11, Assumptions!$D$7),"mmyy")` |
| 9 | Curve rung 3: `B9=Assumptions!C8` (0.0), `C9=TEXT(EDATE(C11, Assumptions!$D$8),"mmyy")` |
| 11 | Month date header: `C11='Cash Flow'!C12`, ..., `O11='Cash Flow'!O12` |
| 12–21 | 10 city rows (one per Assumptions city row 13–22) |
| 22 | `B22="Total"`, `C22=SUM(C12:C21)`, ..., `O22=SUM(O12:O21)` |

**City row idiom (e.g., row 12 for Bangkok, anchored to Assumptions row 13):**

```
B12 = =Assumptions!D13   ← city name
C12 = =IF(C$7=Assumptions!$A13, Assumptions!$J13, 0) * $B$7
    + IF(C$8=Assumptions!$A13, Assumptions!$J13, 0) * $B$8
    + IF(C$9=Assumptions!$A13, Assumptions!$J13, 0) * $B$9
```

For each curve rung, the formula tests whether "this month's mmyy shifted by the rung's months_before" matches the city's show mmyy (Assumptions!$A13). If yes, multiply the city's total ticket revenue (Assumptions!$J13) by the rung's percentage ($B$7 etc.). Sum across rungs.

**Col C..O repeats the same formula with $A13 unchanged but the month-under-test (C$7, C$8, C$9 → D$7,D$8,D$9 → etc.) advancing.**

**Format:** `"$"#,##0`. Zero rows should still be zero (not blank) to let SUMIF chains work.

### 2.2 Best case block (rows 25–44)

Same structure, rows 34–43 mirror rows 55–64 of Assumptions (Best city revenue), curve joins use rows 29–31 shifted, month header at row 33 references row 11.

**Row 25:** `B25="Case"`, `C25==Assumptions!$C$52` ("Best").

**Row 34 for Bangkok Best:**
```
C34 = =IF(C$29=Assumptions!$A55, Assumptions!$J55, 0)*$B$29
    + IF(C$30=Assumptions!$A55, Assumptions!$J55, 0)*$B$30
    + IF(C$31=Assumptions!$A55, Assumptions!$J55, 0)*$B$31
```

**Row 44:** `C44=SUM(C34:C43)` per month.

---

## 3. `Cash Flow` Sheet

Monthly cash-flow schedule + cumulative waterfall.

### 3.1 Top block (rows 1–9)

| Addr | Content |
|---|---|
| A1 | `"Cash Flow Schedule"` (title) |
| B3 | `"Equity Contributions"` [section header] |
| E3 | `"Distribution Assumptions"` |
| J3 | `"Distribution Timing Assumptions"` |
| B4 | `"Partner"` |
| C4 | `=Assumptions!$D$164` ← equity from Assumptions |
| E4..H4 | headers: `"Total Deal"`, `"Return"`, `"Invetsor"` [sic — typo preserved], `"BluFin"` |
| J4..L4 | headers: `"Total Deal"`, `"% of Equity"`, `"Month"` |
| B5 | `"Total"` |
| C5 | `=SUM(C4)` |
| E5 | `=" Absolute Return < "&TEXT($F$6, "0%")` (dynamic label) |
| G5 | `1` [Y: investor share below hurdle = 100%] |
| H5 | `=1-G5` (BluFin share below hurdle) |
| J5 | `"1st Distribution"` |
| K5 | `0.5` [Y: % of equity returned in 1st distribution] |
| L5 | `2026-06-01` [Y: 1st distribution date] |
| M5 | `=TEXT(L5, "mmyy")` |
| E6 | `="Above Hurdle of "&TEXT($F$6, "0%")` |
| F6 | `0.2` [Y: **HURDLE RATE**] |
| G6 | `0.5` [Y: investor share above hurdle] |
| H6 | `=1-G6` (BluFin share above hurdle) |
| J6 | `"2nd Distribution"` |
| K6 | `=1-K5` |
| L6 | `2026-09-01` [Y: 2nd distribution date] |
| M6 | `=TEXT(L6, "mmyy")` |
| J7 | `"Remaning + Upside"` [sic] |
| L7 | `2026-09-01` [Y: upside distribution date — same as 2nd in default] |
| M7 | `=TEXT(L7, "mmyy")` |
| E8 | `"Required minimum Cash Balance"` |
| F8 | `0` [Y: **MIN CASH BALANCE**] |
| B9 | `"Case"` |
| C9 | `"Best"` [Y: **CASE TOGGLE** — "Base" or "Best"] |

### 3.2 Monthly header (rows 11–13)

```
Row 11: C11=TEXT(C12,"mmyy"), D11=TEXT(D12,"mmyy"), ..., O11=TEXT(O12,"mmyy")
Row 12: B12="Item"
        C12=2026-03-01, D12=2026-04-01, E12=2026-05-01, F12=2026-06-01,
        G12=2026-07-01, H12=2026-08-01, I12=2026-09-01, J12=2026-10-01,
        K12=2026-11-01, L12=2026-12-01, M12=2027-01-01, N12=2027-02-01, O12=2027-03-01
        P12, Q12 = (wider range if needed — the JISOO file stops at O12)
Row 13: S13="Check"  (right-side reconciliation column)
```

**13 months total (Mar-26 → Mar-27)**. These dates MUST be plain values, not formulas, because everything else joins on `TEXT(...,"mmyy")` of them.

### 3.3 Revenue rows (14–18)

| Row | Label (B col) | Formula pattern (C col shown — applies D..O) |
|---|---|---|
| 14 | `Ticket Revenue` | `=IF($C$9=Assumptions!$C$10, 'Revenue Cash Flow'!C$22, 'Revenue Cash Flow'!C$44)` |
| 15 | `Merchandising Revenue` | `=IF($C$9=Assumptions!$C$10, SUMIF(Assumptions!$A$13:$A$22, C$11, Assumptions!$M$13:$M$22), SUMIF(Assumptions!$A$55:$A$64, C$11, Assumptions!$M$55:$M$64))` |
| 16 | `F&B Revenue` | same as 15 but `$P$13:$P$22` / `$P$55:$P$64` |
| 17 | `Sponsorship Revenue` | same as 15 but `$Q$13:$Q$22` / `$Q$55:$Q$64` |
| 18 | `Total Revenue` | `=SUM(C14:C17)` |

### 3.4 Cost rows (20–24)

```
Row 20 Production Cost: =SUMIF(Assumptions!$A$117:$A$121, C$11, Assumptions!$F$117:$F$121)
Row 21 Ticketing Platform Fees: =IF(C$11=Assumptions!$A$124, Assumptions!$D$124 * (IF($C$9=Assumptions!$C$10, C14, C14)), 0)
   (simplified form; the actual formula uses nested IF on case — but since ticket rev C14 already case-switches, this reduces to =IF(month_match, fee_pct * C14, 0))
Row 22 Total Operating Costs: =SUM(C20:C21)
Row 24 Net Operating Profit: =C18-C22
```

### 3.5 Artist fees (26–30)

```
Row 26: B26="Jisoo's Fee Schedule"
Row 28 MG Payment for Jisoo: =SUMIF(Assumptions!$A$135:$A$139, C$11, Assumptions!$F$135:$F$139)
Row 29 Jisoo's Sponsorship Royalty: =Assumptions!$D$142 * 'Cash Flow'!C$17
Row 30 Total Payment to Jisoo: =SUM(C28:C29)
```

### 3.6 Other payments (32–36)

```
Row 32: B32="Other Payment"
Row 34 Agency Fees: =SUMIF(Assumptions!$A$150:$A$151, C$11, Assumptions!$E$150:$E$151)
Row 35 BluFin Fees: =SUMIF(Assumptions!$A$158:$A$159, C$11, Assumptions!$E$158:$E$159)
Row 36 Total Payment to Agency and Producer: =SUM(C34:C35)
Row 38 Net Cash Flow: =C24 - C30 - C36
```

### 3.7 Cumulative block (rows 40–51)

```
Row 40: B40="Cummulative Cash Flow Schedule" [sic spelling preserved]
Row 42: mirrors row 12 (month dates): =B12, =C12, ..., =O12
Row 44 Investor's Capital: C44==Assumptions!D164,   D44=IF(D12>$L$7,,C51), E44=IF(E12>$L$7,,D51), ...
    ← cumulative balance carried forward UNTIL the upside distribution date L7, then stops
Row 45 Net Operating Profit: =C24   (repeats the monthly NOP)
Row 46 Jisoo's Fees: =-C30     (sign-flipped — costs are negative in cumulative)
Row 47 Agency Fees: =-C34
Row 48 BluFin Fees: =-C35
Row 49 Return of Capital: complex IF — returns capital at distribution dates L5/L6 until SUM(returns) >= equity
Row 50 Hurdle 20% (dynamic label): =-IF(C$11=$M$7, MIN($C$5*$F$6, SUM(C$44:C$49)), 0)
    ← at the upside month, pays MIN(equity × hurdle, remaining cash)
Row 51 Total Cash Flow: =SUM(C44:C50)    ← running cumulative
```

**Return of Capital formula (row 49, C col):**
```
=IF(C12 > $L$7, 0, IF(-SUM($B$49:B$49) >= $C$5, 0, -IF(C$11=$M$7, <distribution_amount>, <prior_month_amount>)))
```
(exact form: truncated in my extract; implementer should replicate cell-for-cell from the raw JSON)

### 3.8 Distribution waterfall (rows 53–64)

```
Row 53: B53 = ="Distribution after " & TEXT($F$6, "0%") & " absolute return"   (dynamic label)
Row 54 Investor: C54 = SUMIF($C$11:$O$11, $M$7, $C$51:$O$51) * $G$6
Row 55 BluFin:   C55 = SUMIF($C$11:$O$11, $M$7, $C$51:$O$51) * $H$6
Row 57 Total Investor Return: C57 = -SUM($C$49:$O$50) + $C$54
Row 58 Investor Profit:       C58 = $C$57 - $C$44
Row 59 MOIC:                  C59 = IFERROR($C$57/$C$5, "")        [number format "0.00\"x\""]
Row 60 Absolute Return:       C60 = IFERROR($C$57/$C$44 - 1, "")   [number format "0%"]
Row 62 Total BluFin Return:   C62 = $C$55 + SUM($C$35:$O$35)       (includes BluFin fees earned)
Row 64 Check:                 C64 = $C$58 - (-SUM($C$50:$O$50) + $C$54)    (must be 0 — reconciliation)
```

---

## 4. `Summary` Sheet

Pure references. No new logic.

| Section | Rows | Content |
|---|---|---|
| Title | 1 | `A1="Summary Chart"` |
| Month header | 3 | `C3='Cash Flow'!C42, ..., O3='Cash Flow'!O42` |
| Outflow block | 4–10 | B4="Outflow"; rows 5–7 pull from Cash Flow: Artist Fees (`'Cash Flow'!C28`), Agency Fees (`-SUM('Cash Flow'!C47:C48)`), Production Costs (`'Cash Flow'!C20`); row 8 = total; rows 9–10 are leftover text values — **discard in exporter** |
| Month header (repeat) | 11 | `C11=C3`, etc. |
| Inflow block | 12–15 | Investor's Capital Inflow (`'Cash Flow'!C44`), Return of Capital (`'Cash Flow'!C49`), Hurdle 20% (`'Cash Flow'!C50`) |
| KPI panel | 19–25 | `C19="Base", D19="Best"`, Total Expected Attendance (`Assumptions!H23, H65`), Avg Ticket Price (I23, I65), Expected Ticket Revenue (J23, J65), Absolute Return, MOIC rows (empty in sample but reserved) |
| Revenue Assumptions_Best matrix | 28–55 | Mirrors Assumptions rows 25–50 of the **Best** case pricing/count matrices via formulas |
| Cost Assumptions note | 57–59 | Total Production Costs = `Assumptions!D113`, label "for 8 shows" |

**Implementer note:** the KPI panel (rows 19–25) is the "investor-at-a-glance" section. Absolute Return and MOIC cells should reference `'Cash Flow'!C60` and `'Cash Flow'!C59` respectively (the JISOO file leaves these blank — we fix that).

---

## 5. `Total` Sheet

Aggregate P&L, both cases side-by-side. 63 cells total.

| Row | Col A (label) | Col B (value/formula) | Col C (note) |
|---|---|---|---|
| 1 | `Concert - JISOO` | | |
| 3 | `Base` [H] | | |
| 5 | `Ticket Revenue` | `=Assumptions!J23` | `for 8 shows` |
| 6 | `Merch Revenue` | `=Assumptions!J24` ← **bug in JISOO: should be M23**. Correct in exporter to `=Assumptions!M23` | `for 8 shows` |
| 7 | `F&B Revenue` | `=Assumptions!P23` | `for 8 shows` |
| 8 | `Sponsorship Revenue` | `=Assumptions!Q23` | `for 8 shows` |
| 9 | `Total Revenue` | `=SUM(B5:B8)` | |
| 11 | `Cost Assumptions` [H] | | |
| 13 | `Total Production Costs` | `=Assumptions!D113` | `for 8 shows` |
| 14 | `Ticketing Fees` | `=B5*0.06` ← **ticketing fee rate hardcoded. Generalize to `=B5*Assumptions!D124`** | `6% of Tkt Revenue` |
| 15 | `Artist Fees` | `=Assumptions!D131` | `for 8 shows` |
| 16 | `=Assumptions!C145` | `=Assumptions!D147` | (Agency Fees: label and amount pulled dynamically) |
| 17 | `=Assumptions!C155` | `=Assumptions!D155` | (Other Fees: label and amount) |
| 18 | `Total Costs` | `=SUM(B13:B17)` | |
| 20 | `Best` [H] | | |
| 22 | `Ticket Revenue` | `=Assumptions!J65` | `for 8 shows` |
| 23 | `Merch Revenue` | `=Assumptions!M65` | `for 8 shows` |
| 24 | `F&B Revenue` | `=Assumptions!P65` | `for 8 shows` |
| 25 | `Sponsorship Revenue` | `=Assumptions!Q65` | `for 8 shows` |
| 26 | `Total Revenue` | `=SUM(B22:B25)` | |
| 28 | `Cost Assumptions` [H] | | |
| 30 | `Total Production Costs` | `=Assumptions!D113` | `for 8 shows` |
| 31 | `Ticketing Fees` | `='Cash Flow'!H21` ← **fragile. Change to `=B22*Assumptions!D124`** | `6% of Tkt Revenue` |
| 32 | `Artist Fees` | `=Assumptions!D131` | `for 8 shows` |
| 33 | `=Assumptions!C145` | `=Assumptions!D147` | |
| 34 | `=Assumptions!C155` | `=Assumptions!D155` | |
| 35 | `Total Costs` | `=SUM(B30:B34)` | |

---

## 6. `Data` Sheet

Static reference. 108 cells, 100 values + 8 formulas.

| Rows | Content |
|---|---|
| 1–3 | Title / header row (`Country / Region`, `Stadium / Venue`, `Approx. Capacity`, `Notes`) |
| 3–16 | Stadium table: Singapore, Japan, Hong Kong, South Korea venues with capacities and notes |
| 18+ | Pricing Data table (Location, Approx. Avg Ticket Price (Standard GA), Reasoning/Notes) |
| bottom | JISOO-specific reference table: Capacity, Avg Ticket Price, Ticket Sales Revenue, Venue Rental, Security, Production, Artist Fee, Staff, Total Cost, Net, Margin — both "per show" and "3 shows" columns |

**Implementer note:** pull the stadium list from `data/touring-cities-venues.json` at export time. Filter to top ~15–20 venues by capacity in relevant regions. Pricing Data can be a hardcoded seed table (4 country tiers) since the dashboard doesn't yet maintain this.

---

## 7. Key Formula Idioms (Reusable Patterns)

### 7.1 mmyy join key
```
=TEXT(<date_cell>, "mmyy")
```
Used everywhere to build a month-key for SUMIF matching. Format `"mmyy"` produces e.g. `"0826"` for Aug 2026.

### 7.2 Month-shift via EDATE
```
=TEXT(EDATE(<anchor_date>, <months_offset>), "mmyy")
```
EDATE is month-aware and doesn't suffer the JS `setMonth` rollover bug. Exporter MUST emit this formula, not pre-compute the shifted date.

### 7.3 Per-month payment landing (SUMIF on mmyy)
```
=SUMIF(<mmyy_column_in_Assumptions>, <current_month_mmyy>, <amount_column>)
```
Example: `=SUMIF(Assumptions!$A$117:$A$121, C$11, Assumptions!$F$117:$F$121)` — sums all production payments whose mmyy code matches the current month column.

### 7.4 Case switch
```
=IF($C$9=Assumptions!$C$10, <base_ref>, <best_ref>)
```
`Cash Flow!$C$9` holds the case label. `Assumptions!$C$10` = `"Base"` literal (also pulled via formula). Any cell that has Base/Best divergence uses this pattern.

### 7.5 Seat-count balance formula
```
D39 = =D50 - SUM(D40:D49)
```
First tier (top of stack) auto-derives to force `SUM(seat_counts) = total_attendance (F*G)`. Invariant: user can edit other tier counts freely; top tier absorbs the difference.

### 7.6 Per-city ticket revenue
```
J13 = =SUMPRODUCT(D26:D36, D39:D49)
```
SUMPRODUCT of price column × count column within the city's pricing/count matrix. **One column per city in the matrix (D=city1, E=city2, ..., M=city8).**

### 7.7 Ticket curve distribution (Revenue Cash Flow)
```
C12 = =IF(C$7=Assumptions!$A13, Assumptions!$J13, 0)*$B$7
    + IF(C$8=Assumptions!$A13, Assumptions!$J13, 0)*$B$8
    + IF(C$9=Assumptions!$A13, Assumptions!$J13, 0)*$B$9
```
For each curve rung (rows 7, 8, 9), test whether this month's shifted mmyy matches the city's show mmyy. Multiply by rung percentage. Sum the rungs.

### 7.8 Dynamic label (string concatenation in labels)
```
E5 = =" Absolute Return < " & TEXT($F$6, "0%")
```
Labels reference the input they describe — if user changes hurdle, the label updates.

---

## 8. Exporter Implementation Checklist

Every one of these 224 yellow input cells must be settable by the profile data model:

| Category | Count | Source in profile |
|---|---:|---|
| Ticket sale curve (rung%, months_before) | 6 | `profile.ticket_curve[]` |
| Per-city (city#, date, capacity, occupancy%, merch$, split%, F&B/head, F&B buyers, sponsorship$) × 10 cities × Base | ~80 | `profile.tour_cities[]` |
| Per-city Best occupancy | 10 | `profile.case_overrides.best.fill_rate` or per-city override |
| Pricing matrix Base (7 tiers × 8 cities + 4 extras) | 56 | `profile.tour_cities[].seat_categories[].price` |
| Seat count matrix Base (6 non-P5 tiers × 8 cities + extras) | ~48 | `profile.tour_cities[].seat_categories[].count` (P5 auto-balances) |
| Pricing matrix Best | 56 | profile.best_case or profile.tour_cities[].seat_categories[].best_price |
| Seat count matrix Best | ~48 | same as Base by default; overridable |
| Cost lines (10 × 8 cities) | 80 | `profile.costs.cost_lines[].per_city[]` |
| Cost percentages (Music Copyright, GST) | 2 | `profile.costs.tax_lines[]` |
| Production payment schedule (5 tranches × months_before + pct) | 10 | `profile.costs.production_schedule[]` |
| Ticketing fee% + fee-posts date | 2 | `profile.costs.ticketing_fee_pct`, `profile.costs.ticketing_fee_date` |
| Artist MG total + 5 tranches × (months_before, pct) | 11 | `profile.costs.artist_mg`, `profile.costs.mg_schedule[]` |
| Artist Sponsorship Royalty % | 1 | `profile.costs.artist_sponsorship_royalty_pct` |
| Agency upfront + 2 dated tranches × (date, amount/pct) | 5 | `profile.costs.agency_fees`, `profile.costs.agency_schedule[]` |
| Other Fees (BluFin) upfront + 2 dated tranches | 5 | `profile.costs.blufin_fees`, `profile.costs.blufin_schedule[]` |
| Equity | 1 | `profile.investor_scenarios[0].equity` |
| Hurdle rate | 1 | `profile.investor_scenarios[0].hurdle_rate` |
| Above-hurdle investor share | 1 | `profile.investor_scenarios[0].above_hurdle_investor_pct` |
| Min cash balance | 1 | `profile.min_cash_balance` |
| Distribution schedule (2 entries × date + %) | 4 | `profile.distributions[]` |
| Case label (Base/Best) | 1 | `profile.case` |
| **Total** | **~428 cells** — slightly more than JISOO's 224 because we expose per-city Best occupancy + Best prices/counts as distinct inputs; JISOO mirrored the matrix so Best prices = Base by default. |

**Shape constraints the exporter must enforce:**
1. 10 city rows reserved (support up to 10 cities). Unused rows have city# in col C but blank D/E/F (Base) and Best.
2. 11 pricing rows reserved (7 standard tiers + 4 extras).
3. 11 count rows reserved (same).
4. 5 production payment rows; 5 MG payment rows; 2 agency + 2 BluFin rows.
5. 13 monthly columns (C..O) in Cash Flow / Revenue Cash Flow / Summary — span must cover earliest payment (Agency 1st ≈ 5 months pre-show) through upside distribution month.
6. Dates must be native Excel date values (serial numbers), not text. Number format `d-mmm-yy` for show dates, `mmm-yy` or `d-mmm-yy` for schedule dates.

---

## 9. Test Fixtures (for golden-file QC)

Fixtures to implement in `tests/financial_model_fixtures.json`:

1. **`jisoo_exact_replica`** — all 8 cities, prices, seat counts, costs exactly as JISOO. Exporter output should match AVECS file within ±$1 per computed cell.
2. **`single_city`** — 1 city, simple pricing, no investor equity. Cash Flow tabs should show a 5-month timeline (1 month pre-show to 1 month post).
3. **`legacy_no_timeline`** — legacy profile with no `timeline` field. Cash Flow/Revenue Cash Flow tabs show "Timeline not configured" banner. Total + Summary + Assumptions still populate.
4. **`best_case_divergent`** — Base and Best cases have different prices (user has manually edited Best pricing). Both matrices export independently.
5. **`ten_city_stadium`** — stress test with 10 cities, 7 tiers each, full cost line breakdown. No errors, no cell overflow.
6. **`edge_hurdle_not_met`** — equity = $12M, total profit = $1M. Hurdle 20% = $2.4M. Investor takes all $1M; BluFin = 0. MOIC = 1.083x.
7. **`edge_above_hurdle_50_50`** — equity = $12M, total profit = $5M. Hurdle $2.4M goes 100% to investor; remaining $2.6M splits 50/50. Investor total: $2.4M + $1.3M = $3.7M. MOIC = 1.308x.
8. **`min_cash_balance_breach`** — cumulative cash goes below min_cash_balance mid-project. UI should warn; export should include a cell indicating the breach.

Cross-app validation (Task 8):
- Excel (Mac / Windows)
- Google Sheets (upload → re-download)
- Apple Numbers (open / resave)
- LibreOffice Calc (headless `soffice --calc --headless --convert-to xlsx` for CI golden-file diff)

All must evaluate formulas identically. Any divergence → document and fix.

---

## 10. Known JISOO Bugs (Exporter Must FIX)

1. **`Total!B6 = =Assumptions!J24`** — J24 is empty. Should be `=Assumptions!M23` (total merch rev Base).
2. **`Total!B14 = =B5*0.06`** — hardcoded 6%. Should reference `=B5*Assumptions!$D$124`.
3. **`Total!B31 = ='Cash Flow'!H21`** — takes ONE month of ticketing fees (Aug-26). Should be `=B22*Assumptions!$D$124` (total Best ticket rev × fee pct).
4. **`Summary!C9..F9` = hardcoded values `2000000, 6000000, 9100000`** — leftover scratch data. **Omit in exporter.**
5. **`Summary!C24` and `C25` (Absolute Return, MOIC)** — labels exist, values blank. Exporter should fill: `C24=Cash Flow!C60`, `C25=Cash Flow!C59`, with a separate Best-case row if we add that feature.
6. **`Cash Flow!G4="Invetsor"`** — typo. Exporter writes `"Investor"`.
7. **`Cash Flow!B40="Cummulative Cash Flow Schedule"`** — misspelled. Exporter writes `"Cumulative..."`.
8. **`Cash Flow!J7="Remaning + Upside"`** — misspelled. Exporter writes `"Remaining + Upside"`.

---

**End of cell-map.**
