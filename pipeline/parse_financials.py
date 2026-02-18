"""
parse_financials.py — Convert a financial model CSV into a clean JSON file.

Usage:
  python pipeline/parse_financials.py "path/to/model.csv" "Artist Name"

Output:
  data/financials/<slug>.json
  data/financials/index.json  (updated with this artist)
"""

import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional, List, Dict

BASE_DIR = Path(__file__).parent.parent
FINANCIALS_DIR = BASE_DIR / "data" / "financials"


# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def parse_money(val: str) -> Optional[float]:
    """'$1,234,567.89' or '24.43%' → float, or None if empty."""
    if not val:
        return None
    v = val.strip().replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(v)
    except ValueError:
        return None


def is_blank_row(row: list[str]) -> bool:
    return all(c.strip() == "" for c in row)


def first_cell(row: list[str]) -> str:
    return row[0].strip() if row else ""


# ── Section parsers ───────────────────────────────────────────────────────────

def parse_revenue(rows: list) -> dict:
    """
    Rows after the 'Revenue Assumptions' header.
    Header row: Country, Schedule, Venue Capacity, Occupancy Rate,
                Expected Attendance, Avg Ticket Price, Ticket Revenue
    Data rows until blank + Total row.
    """
    shows = []
    markets_seen = {}  # city → list of show indices
    total_row = None

    for row in rows:
        fc = first_cell(row)
        if fc.lower() == "total":
            total_row = row
            break
        if fc.lower() in ("country", ""):
            continue
        city = fc
        show = {
            "city": city,
            "schedule": row[1].strip() if len(row) > 1 else "",
            "venue_capacity": int(parse_money(row[2]) or 0) if len(row) > 2 else 0,
            "occupancy_rate": parse_money(row[3]) if len(row) > 3 else None,
            "expected_attendance": int(parse_money(row[4]) or 0) if len(row) > 4 else 0,
            "avg_ticket_price": parse_money(row[5]) if len(row) > 5 else None,
            "ticket_revenue": parse_money(row[6]) if len(row) > 6 else None,
        }
        shows.append(show)
        markets_seen.setdefault(city, []).append(len(shows) - 1)

    # Build per-market rollups
    markets = []
    for city, indices in markets_seen.items():
        city_shows = [shows[i] for i in indices]
        markets.append({
            "city": city,
            "shows": city_shows,
            "total_capacity": sum(s["venue_capacity"] for s in city_shows),
            "total_revenue": sum(s["ticket_revenue"] or 0 for s in city_shows),
        })

    result = {"shows": shows, "markets": markets}
    if total_row:
        result["grand_total"] = {
            "total_capacity": int(parse_money(total_row[2]) or 0) if len(total_row) > 2 else 0,
            "avg_ticket_price": parse_money(total_row[5]) if len(total_row) > 5 else None,
            "total_revenue": parse_money(total_row[6]) if len(total_row) > 6 else None,
        }
    return result


def parse_seat_assumptions(rows: list) -> dict:
    """
    Two sub-sections:
      1. Category / Price  — columns: category, market1 (aggressive), market1 (conservative), ...
      2. Category / Number of Seats — columns: category, market1, Price * Seats
    """
    pricing = {}   # category → { market: { aggressive, conservative } }
    counts = {}    # category → { market: count }
    seat_totals = {}  # market → { count, revenue }

    # Split into two sub-sections by looking for the second header
    price_rows = []
    count_rows = []
    count_header_row = None
    in_counts = False

    for row in rows:
        fc = first_cell(row)
        if "number of seats" in fc.lower():
            in_counts = True
            count_header_row = row  # save the actual header row
            continue
        if "price" in fc.lower() and "category" in fc.lower():
            in_counts = False
            continue
        if is_blank_row(row):
            continue
        if in_counts:
            count_rows.append(row)
        else:
            price_rows.append(row)

    # Price rows — first row is the header: [category_label, market (aggressive), market (conservative), ...]
    if price_rows:
        header = price_rows[0]
        # Parse market + scenario from header cells like "Tokyo (aggressive)"
        col_markets = []
        for cell in header[1:]:
            m = re.match(r"(.+?)\s*\((aggressive|conservative)\)", cell.strip(), re.IGNORECASE)
            if m:
                col_markets.append({"city": m.group(1).strip(), "scenario": m.group(2).lower()})
            elif cell.strip():
                col_markets.append({"city": cell.strip(), "scenario": "default"})
            else:
                col_markets.append(None)

        for row in price_rows[1:]:
            cat = first_cell(row)
            if not cat or cat.lower() in ("catergory / price", "category / price"):
                continue
            pricing.setdefault(cat, {})
            for i, cm in enumerate(col_markets):
                if cm is None or i + 1 >= len(row):
                    continue
                val = parse_money(row[i + 1])
                pricing[cat].setdefault(cm["city"], {})
                pricing[cat][cm["city"]][cm["scenario"]] = val

    # Count rows — use the saved header row; data rows are all of count_rows
    if count_rows:
        # Use the header row captured before the section (count_header_row),
        # falling back to the first data row only if the header wasn't found.
        hdr = count_header_row if count_header_row is not None else count_rows[0]
        col_cities = [c.strip() for c in hdr[1:] if c.strip() and "price" not in c.lower()]
        data_rows = count_rows if count_header_row is not None else count_rows[1:]

        for row in data_rows:
            cat = first_cell(row)
            if not cat:
                continue
            if cat.lower() == "total":
                for i, city in enumerate(col_cities):
                    if i + 1 < len(row):
                        seat_totals.setdefault(city, {})
                        seat_totals[city]["total_seats"] = int(parse_money(row[i + 1]) or 0)
                # revenue total is usually in the next column
                rev_idx = len(col_cities) + 1
                if rev_idx < len(row):
                    for city in col_cities:
                        seat_totals[city]["total_revenue"] = parse_money(row[rev_idx])
                continue
            for i, city in enumerate(col_cities):
                if i + 1 < len(row):
                    counts.setdefault(cat, {})
                    counts[cat][city] = int(parse_money(row[i + 1]) or 0)

    return {"pricing": pricing, "counts": counts, "totals": seat_totals}


def parse_costs(rows: list) -> dict:
    """
    Header row: Particulars, Notes, Assumption, Market, Market, Market, ...
    Data rows until blank.
    Returns: { "columns": [...], "line_items": [...], "total": {...} }
    """
    if not rows:
        return {"columns": [], "line_items": [], "total": {}}

    header = rows[0]
    # cols 0-2 are fixed: Particulars, Notes, Assumption
    # cols 3+ are market columns (may be duplicate city names like "Tokyo", "Tokyo", "Tokyo")
    market_cols = []
    for i, cell in enumerate(header[3:], start=3):
        c = cell.strip()
        if c:
            # Disambiguate duplicate city names by adding show number
            count = sum(1 for mc in market_cols if mc["city"] == c)
            market_cols.append({"col_idx": i, "city": c, "show": count + 1,
                                 "label": c if count == 0 else f"{c} (show {count + 1})"})

    line_items = []
    totals = {}

    for row in rows[1:]:
        fc = first_cell(row)
        if not fc or is_blank_row(row):
            continue
        if fc.lower() == "total":
            for mc in market_cols:
                if mc["col_idx"] < len(row):
                    totals[mc["label"]] = parse_money(row[mc["col_idx"]])
            continue

        item = {
            "particulars": fc,
            "notes": row[1].strip() if len(row) > 1 else "",
            "assumption": row[2].strip() if len(row) > 2 else "",
            "values": {},
        }
        has_any_value = False
        for mc in market_cols:
            v = parse_money(row[mc["col_idx"]]) if mc["col_idx"] < len(row) else None
            item["values"][mc["label"]] = v
            if v is not None:
                has_any_value = True

        # Include line items that have notes/assumption or at least one value
        if has_any_value or item["notes"] or item["assumption"]:
            line_items.append(item)

    columns = [mc["label"] for mc in market_cols]
    return {"columns": columns, "line_items": line_items, "total": totals}


def parse_summary(rows: list) -> dict:
    """
    Label rows followed by value rows:
      Broker Fee → $500,000
      Total Cost → $18,500,000
      Total Ticket Revenue → $23,019,175.46
      Profit → $4,519,175.46
      ROI → 24.43%
    """
    summary = {}
    key_map = {
        "broker fee": "broker_fee",
        "total cost": "total_cost",
        "total ticket revenue": "total_ticket_revenue",
        "profit": "profit",
        "roi": "roi",
    }
    i = 0
    while i < len(rows):
        fc = first_cell(rows[i]).lower().strip()
        key = key_map.get(fc)
        if key and i + 1 < len(rows):
            val_row = rows[i + 1]
            raw = first_cell(val_row)
            v = parse_money(raw)
            if v is not None:
                # ROI: store as fraction (e.g. 0.2443) not 24.43
                summary[key] = round(v / 100, 6) if key == "roi" else v
        i += 1
    return summary


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_csv(filepath: str, artist_name: str) -> dict:
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    # Split into sections by section header keywords
    sections = {
        "revenue": [],
        "seat": [],
        "cost": [],
        "summary": [],
    }

    current = None
    SECTION_MARKERS = {
        "revenue assumptions": "revenue",
        "seat assumptions": "seat",
        "cost assumptions": "cost",
    }
    SUMMARY_STARTS = {"broker fee", "total cost", "total ticket revenue", "profit", "roi"}

    for row in rows:
        fc = first_cell(row).lower().strip().rstrip()
        # Check for section header
        matched = next((v for k, v in SECTION_MARKERS.items() if fc.startswith(k)), None)
        if matched:
            current = matched
            continue
        if fc in SUMMARY_STARTS:
            current = "summary"

        if current:
            sections[current].append(row)

    revenue = parse_revenue(sections["revenue"])
    seats = parse_seat_assumptions(sections["seat"])
    costs = parse_costs(sections["cost"])
    summary = parse_summary(sections["summary"])

    return {
        "artist": artist_name,
        "slug": slugify(artist_name),
        "revenue": revenue,
        "seat_assumptions": seats,
        "costs": costs,
        "summary": summary,
    }


def update_index(slug: str, artist_name: str):
    index_path = FINANCIALS_DIR / "index.json"
    if index_path.exists():
        with open(index_path) as f:
            index = json.load(f)
    else:
        index = []

    existing = next((e for e in index if e["slug"] == slug), None)
    if existing:
        existing["artist"] = artist_name
    else:
        index.append({"slug": slug, "artist": artist_name})

    index.sort(key=lambda e: e["artist"])
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)
    print(f"Updated index: {index_path}")


def main():
    if len(sys.argv) < 3:
        print("Usage: python pipeline/parse_financials.py <csv_path> <artist_name>")
        sys.exit(1)

    csv_path = sys.argv[1]
    artist_name = sys.argv[2]

    FINANCIALS_DIR.mkdir(parents=True, exist_ok=True)

    data = parse_csv(csv_path, artist_name)
    slug = data["slug"]

    out_path = FINANCIALS_DIR / f"{slug}.json"
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote: {out_path}")

    update_index(slug, artist_name)
    print(f"Done. Artist: {artist_name} → {slug}")


if __name__ == "__main__":
    main()
