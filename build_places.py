"""Download NYC Open Data once and save it as data/nyc_places.json for the place tool.

Run once (or whenever you want fresher data):   uv run build_places.py
Then commit data/nyc_places.json so nobody else has to run this.

Sources (free, no key):
- New York City Museums     https://data.cityofnewyork.us/d/fn6f-htvy
- NYC Parks Properties      https://data.cityofnewyork.us/d/enfh-gkve
"""

import csv
import io
import json
from datetime import date
from pathlib import Path

import requests

MUSEUMS_CSV = "https://data.cityofnewyork.us/api/views/fn6f-htvy/rows.csv?accessType=DOWNLOAD"
PARKS_JSON = "https://data.cityofnewyork.us/resource/enfh-gkve.json"
OUT_FILE = Path(__file__).parent / "data" / "nyc_places.json"

MIN_PARK_ACRES = 20  # thousands of park properties exist; keep the ones worth a visit
SKIP_PARK_TYPES = {"parkway", "strip", "triangle/plaza", "mall", "lot", "undeveloped", "cemetery", "jointly operated playground"}
PARK_BOROUGHS = {"M": "Manhattan", "X": "Bronx", "B": "Brooklyn", "Q": "Queens", "R": "Staten Island"}


def borough_from_zip(zipcode: str) -> str | None:
    """NYC ZIP prefixes map cleanly to boroughs."""
    z = str(zipcode).strip()[:3]
    if z in {"100", "101", "102"}:
        return "Manhattan"
    if z == "103":
        return "Staten Island"
    if z == "104":
        return "Bronx"
    if z == "112":
        return "Brooklyn"
    if z in {"110", "111", "113", "114", "116"}:
        return "Queens"
    return None


def museum_row_to_place(row: dict) -> dict | None:
    r = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
    name = r.get("name")
    if not name:
        return None
    address = ", ".join(p for p in [r.get("adress1") or r.get("address1"), r.get("address2"), r.get("city")] if p)
    return {
        "name": name,
        "category": "museum",
        "borough": borough_from_zip(r.get("zip", "")),
        "address": address or None,
        "phone": r.get("tel") or None,
        "website": r.get("url") or None,
        "indoor": True,
        "source": "NYC Open Data: New York City Museums (fn6f-htvy)",
    }


def park_row_to_place(row: dict) -> dict | None:
    name = (row.get("signname") or row.get("name311") or "").strip()
    try:
        acres = float(row.get("acres") or 0)
    except ValueError:
        acres = 0
    kind = (row.get("typecategory") or "").strip()
    if not name or acres < MIN_PARK_ACRES or kind.lower() in SKIP_PARK_TYPES:
        return None
    return {
        "name": name,
        "category": "park",
        "borough": PARK_BOROUGHS.get((row.get("borough") or "").strip().upper()),
        "address": (row.get("address") or row.get("location") or "").strip() or None,
        "park_type": kind or None,
        "acres": round(acres, 1),
        "website": (row.get("url") or "").strip() or None,
        "indoor": False,
        "source": "NYC Open Data: Parks Properties (enfh-gkve)",
    }


def main():
    print("Downloading museums...")
    resp = requests.get(MUSEUMS_CSV, timeout=60)
    resp.raise_for_status()
    museum_rows = list(csv.DictReader(io.StringIO(resp.text)))
    print(f"  museum columns: {list(museum_rows[0].keys()) if museum_rows else 'none'}")

    print("Downloading parks...")
    resp = requests.get(PARKS_JSON, params={"$limit": 50000}, timeout=60)
    resp.raise_for_status()
    park_rows = resp.json()
    print(f"  park columns: {sorted(park_rows[0].keys()) if park_rows else 'none'}")

    museums = [p for p in map(museum_row_to_place, museum_rows) if p]
    parks = [p for p in map(park_row_to_place, park_rows) if p]
    parks.sort(key=lambda p: p["acres"], reverse=True)  # biggest first

    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps({
        "downloaded": date.today().isoformat(),
        "places": museums + parks,
    }, indent=1))

    print(f"\nSaved {len(museums)} museums and {len(parks)} parks to {OUT_FILE}")
    no_borough = sum(1 for p in museums + parks if not p["borough"])
    if no_borough:
        print(f"  note: {no_borough} places have no borough (missing or unusual ZIP)")
    if not museums or not parks:
        print("  WARNING: one source came back empty. Check the column names printed above.")


if __name__ == "__main__":
    main()