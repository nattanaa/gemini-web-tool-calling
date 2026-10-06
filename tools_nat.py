"""All tools for the NYC student assistant, and the JSON that describes them to the model.

Law tools       list_ny_laws, search_ny_law, get_ny_law_section
                Data: NY Senate Open Legislation API (free key from https://legislation.nysenate.gov),
                read from the NYSENATE_API_KEY environment variable.
Student tools   convert_units         exact math, no data source needed
                recommend_nyc_places  NYC Open Data, saved to data/nyc_places.json by build_places.py
"""

import json
import os
from pathlib import Path

import requests

BASE_URL = "https://legislation.nysenate.gov/api/3"
PUBLIC_URL = "https://www.nysenate.gov/legislation/laws"  # human-readable page for citations
MAX_TEXT_CHARS = 6000  # long sections can blow up the model's context; trim them

_law_list_cache = None  # the list of ~130 laws barely changes, so fetch it once


# ---------------------------------------------------------------- helpers

def _call(path: str, **params) -> dict:
    """GET an Open Legislation endpoint. Raises on network/HTTP/API errors."""
    key = os.environ.get("NYSENATE_API_KEY")
    if not key:
        raise RuntimeError("NYSENATE_API_KEY is not set on the server.")
    resp = requests.get(f"{BASE_URL}{path}", params={**params, "key": key}, timeout=15)
    data = resp.json()  # the API returns JSON even for errors, with success: false
    if not data.get("success"):
        raise LookupError(data.get("message", f"HTTP {resp.status_code}"))
    return data["result"]


def _clean(text: str | None) -> str:
    """The API returns literal backslash-n sequences instead of real newlines."""
    return (text or "").replace("\\n", "\n").strip()


def _error(msg: str) -> str:
    return json.dumps({"error": msg})


# ---------------------------------------------------------------- tools

def list_ny_laws(keyword: str = "") -> str:
    """List NY law codes (e.g. PEN = Penal), optionally filtered by a keyword in the name."""
    global _law_list_cache
    try:
        if _law_list_cache is None:
            items = _call("/laws", limit=1000)["items"]
            _law_list_cache = [{"law_id": i["lawId"], "name": i["name"]} for i in items]
    except (requests.RequestException, ValueError, KeyError, LookupError, RuntimeError) as e:
        return _error(f"Could not list laws: {e}")

    kw = keyword.lower().strip()
    matches = [law for law in _law_list_cache if kw in law["name"].lower()] if kw else _law_list_cache
    if not matches:
        return _error(f"No law name contains '{keyword}'. Try a broader word or no keyword.")
    return json.dumps({"laws": matches})


def search_ny_law(query: str, law_id: str = "", limit: int = 5) -> str:
    """Full-text search across NY laws, or within one law if law_id is given."""
    path = f"/laws/{law_id.upper()}/search" if law_id else "/laws/search"
    limit = max(1, min(int(limit), 10))
    clean_query = query.replace('"', "").strip()
    try:
        items = []
        if " " in clean_query:  # multi-word: try the exact phrase first
            items = _call(path, term=f'"{clean_query}"', limit=limit)["items"]
        if not items:           # single word, or the phrase found nothing
            items = _call(path, term=clean_query, limit=limit)["items"]
    except (requests.RequestException, ValueError, KeyError, LookupError, RuntimeError) as e:
        return _error(f"Search failed: {e}")

    results = []
    for item in items:
        doc = item.get("result", {})
        lid, loc = doc.get("lawId"), doc.get("locationId")
        results.append({
            "law_id": lid,
            "section": loc,
            "title": doc.get("title"),
            "doc_type": doc.get("docType"),
            "source_url": f"{PUBLIC_URL}/{lid}/{loc}" if lid and loc else None,
        })
    return json.dumps({
        "jurisdiction": "New York State",
        "results": results,
        "note": "These are titles only. Call get_ny_law_section to read the actual text.",
    })


def get_ny_law_section(law_id: str, section: str, as_of_date: str = "") -> str:
    """Fetch the official text of one section, optionally as it stood on a past date."""
    law_id, section = law_id.upper().strip(), section.strip()
    params = {"date": as_of_date} if as_of_date else {}
    try:
        doc = _call(f"/laws/{law_id}/{section}", **params)
    except LookupError as e:
        return _error(
            f"{law_id} section '{section}' was not found ({e}). "
            "Do not guess its contents; use search_ny_law to find the right section."
        )
    except (requests.RequestException, ValueError, KeyError, RuntimeError) as e:
        return _error(f"Law service failed: {e}")

    text = _clean(doc.get("text"))
    truncated = len(text) > MAX_TEXT_CHARS
    return json.dumps({
        "jurisdiction": "New York State",
        "law": doc.get("lawName"),
        "law_id": law_id,
        "section": section,
        "title": doc.get("title"),
        "part_of": [p.get("title") for p in doc.get("parents", [])],
        "text": text[:MAX_TEXT_CHARS] + ("\n[...truncated]" if truncated else ""),
        "version_date": doc.get("activeDate"),
        "source_url": f"{PUBLIC_URL}/{law_id}/{section}",
    })


# ---------------------------------------------------------------- unit converter

# Every unit maps to (category, factor to the category's base unit).
_LINEAR = {
    # length, base = meter
    "mm": ("length", 0.001), "cm": ("length", 0.01), "m": ("length", 1.0), "km": ("length", 1000.0),
    "in": ("length", 0.0254), "ft": ("length", 0.3048), "yd": ("length", 0.9144), "mi": ("length", 1609.344),
    # weight, base = gram
    "mg": ("weight", 0.001), "g": ("weight", 1.0), "kg": ("weight", 1000.0),
    "oz": ("weight", 28.349523125), "lb": ("weight", 453.59237),
    # volume (US customary), base = milliliter
    "ml": ("volume", 1.0), "l": ("volume", 1000.0),
    "tsp": ("volume", 4.92892159375), "tbsp": ("volume", 14.78676478125),
    "fl_oz": ("volume", 29.5735295625), "cup": ("volume", 236.5882365),
    "pint": ("volume", 473.176473), "quart": ("volume", 946.352946), "gallon": ("volume", 3785.411784),
    # speed, base = meters per second
    "mph": ("speed", 0.44704), "kmh": ("speed", 1 / 3.6),
}

# Shoe sizes: offset to add to get an approximate EU size. Brands vary by about half a size.
_SHOE_TO_EU = {
    "us_men_shoe": 33, "us_women_shoe": 31,
    "uk_men_shoe": 34, "uk_women_shoe": 33,
    "eu_shoe": 0,
}

_TEMPS = {"f", "c", "k"}

_ALIASES = {
    "fahrenheit": "f", "°f": "f", "celsius": "c", "°c": "c", "centigrade": "c", "kelvin": "k",
    "millimeter": "mm", "millimeters": "mm", "centimeter": "cm", "centimeters": "cm",
    "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "kilometer": "km", "kilometers": "km", "kilometre": "km", "kilometres": "km",
    "inch": "in", "inches": "in", '"': "in", "foot": "ft", "feet": "ft", "'": "ft",
    "yard": "yd", "yards": "yd", "mile": "mi", "miles": "mi",
    "gram": "g", "grams": "g", "kilogram": "kg", "kilograms": "kg", "kgs": "kg",
    "ounce": "oz", "ounces": "oz", "pound": "lb", "pounds": "lb", "lbs": "lb",
    "milliliter": "ml", "milliliters": "ml", "millilitre": "ml",
    "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "teaspoon": "tsp", "teaspoons": "tsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "fluid ounce": "fl_oz", "fluid ounces": "fl_oz", "fl oz": "fl_oz", "floz": "fl_oz",
    "cups": "cup", "pints": "pint", "quarts": "quart", "gallons": "gallon", "gal": "gallon",
    "km/h": "kmh", "kph": "kmh", "miles per hour": "mph",
}


def _norm(unit: str) -> str:
    u = str(unit).strip().lower()
    return _ALIASES.get(u, u)


def _to_celsius(v: float, u: str) -> float:
    return {"c": v, "f": (v - 32) * 5 / 9, "k": v - 273.15}[u]


def _from_celsius(v: float, u: str) -> float:
    return {"c": v, "f": v * 9 / 5 + 32, "k": v + 273.15}[u]


def _feet_inches(meters: float) -> str:
    total_in = round(meters / 0.0254)
    return f"{total_in // 12} ft {total_in % 12} in"


def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    """Convert a measurement between US and metric units, or between shoe size systems."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return _error(f"'{value}' is not a number.")
    src, dst = _norm(from_unit), _norm(to_unit)
    result, category, note = None, None, None

    if src in _TEMPS and dst in _TEMPS:
        category = "temperature"
        result = _from_celsius(_to_celsius(value, src), dst)
    elif src in _SHOE_TO_EU and dst in _SHOE_TO_EU:
        category = "shoe size"
        result = round((value + _SHOE_TO_EU[src] - _SHOE_TO_EU[dst]) * 2) / 2  # nearest half size
        note = "Approximate. Sizing differs by brand, so try shoes on or check the brand's chart."
    elif src in _LINEAR and dst in _LINEAR:
        (c1, f1), (c2, f2) = _LINEAR[src], _LINEAR[dst]
        if c1 != c2:
            return _error(f"Can't convert {c1} ({from_unit}) to {c2} ({to_unit}).")
        category = c1
        result = value * f1 / f2
        if category == "volume":
            note = "US customary units (a US cup is about 237 ml, not the 250 ml metric cup)."
    else:
        known = sorted(set(_LINEAR) | _TEMPS | set(_SHOE_TO_EU))
        return _error(f"Unsupported unit pair '{from_unit}' -> '{to_unit}'. Supported units: {known}")

    out = {
        "category": category,
        "input": f"{value:g} {from_unit}",
        "result": round(result, 2),
        "result_text": f"{round(result, 2):g} {to_unit}",
    }
    if category == "length" and dst in {"ft", "in"}:
        out["feet_inches"] = _feet_inches(value * _LINEAR[src][1])  # e.g. height 170 cm -> 5 ft 7 in
    if note:
        out["note"] = note
    return json.dumps(out)


# ---------------------------------------------------------------- NYC places

# Built from NYC Open Data by build_places.py. Loaded once, on first use.
PLACES_FILE = Path(__file__).parent / "data" / "nyc_places.json"
_BOROUGHS = ["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"]
_places_cache = None


def _load_places() -> dict:
    global _places_cache
    if _places_cache is None:
        _places_cache = json.loads(PLACES_FILE.read_text())
    return _places_cache


def recommend_nyc_places(category: str = "", borough: str = "", keyword: str = "",
                         indoor: str = "any", limit: int = 5) -> str:
    """Filter NYC museums and parks from the Open Data file. All filters are optional."""
    try:
        data = _load_places()
    except FileNotFoundError:
        return _error("Place data is missing on the server. Run build_places.py to create data/nyc_places.json.")
    except (OSError, ValueError) as e:
        return _error(f"Could not read place data: {e}")

    cat, bor, kw, ind = category.strip().lower(), borough.strip().lower(), keyword.strip().lower(), str(indoor).strip().lower()
    if cat and cat not in {"museum", "park"}:
        return _error(f"Unknown category '{category}'. Use 'museum' or 'park'.")
    if bor and bor not in {b.lower() for b in _BOROUGHS}:
        return _error(f"Unknown borough '{borough}'. Use one of: {_BOROUGHS}")
    if ind not in {"any", "indoor", "outdoor"}:
        return _error("indoor must be 'any', 'indoor', or 'outdoor'.")

    matches = [
        p for p in data["places"]
        if (not cat or p["category"] == cat)
        and (not bor or (p.get("borough") or "").lower() == bor)
        and (not kw or kw in p["name"].lower())
        and (ind == "any" or p["indoor"] == (ind == "indoor"))
    ]
    if not matches:
        return _error("No places match all those filters. Try removing the keyword or borough.")

    limit = max(1, min(int(limit), 10))
    return json.dumps({
        "places": matches[:limit],
        "total_matches": len(matches),
        "data_downloaded": data.get("downloaded"),
        "note": "From NYC Open Data. Parks are free; museum prices and hours vary, so check each website before going.",
    })


# ---------------------------------------------------------------- what the model sees

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_ny_laws",
            "description": (
                "List New York State law codes and their 3-letter IDs. Use this when you don't know "
                "which ID a law uses. Common ones: PEN (Penal), VAT (Vehicle and Traffic), "
                "RPP (Real Property), GOB (General Obligations), LAB (Labor), MDW (Multiple Dwelling)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Word in the law's name, e.g. 'labor'. Omit to list all."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_ny_law",
            "description": (
                "Full-text search of New York State laws. Returns section titles and IDs, not text. "
                "Use it to find which sections are relevant, then read them with get_ny_law_section."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search terms, e.g. 'security deposit'"},
                    "law_id": {"type": "string", "description": "Optional 3-letter law ID to search within, e.g. 'GOB'"},
                    "limit": {"type": "integer", "description": "Max results, 1-10 (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ny_law_section",
            "description": (
                "Get the official current text of one section of New York State law. Always use this "
                "before quoting or explaining a law, and cite the returned source_url."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "law_id": {"type": "string", "description": "3-letter law ID, e.g. 'PEN'"},
                    "section": {"type": "string", "description": "Section number, e.g. '125.25' or '7-108'"},
                    "as_of_date": {"type": "string", "description": "Optional ISO date (YYYY-MM-DD) to see an older version (back to Oct 2014)"},
                },
                "required": ["law_id", "section"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "convert_units",
            "description": (
                "Convert between US and metric units with exact math: temperature (f, c, k), "
                "length (in, ft, yd, mi, mm, cm, m, km), weight (oz, lb, g, kg), cooking volume "
                "(tsp, tbsp, fl_oz, cup, pint, quart, gallon, ml, l), speed (mph, kmh), and shoe sizes "
                "(us_men_shoe, us_women_shoe, uk_men_shoe, uk_women_shoe, eu_shoe). Always use this "
                "instead of converting in your head. For a height like 5'7\", convert 5.583 ft or 67 in."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"type": "number", "description": "The number to convert, e.g. 72"},
                    "from_unit": {"type": "string", "description": "Unit of the value, e.g. 'f' or 'lb'"},
                    "to_unit": {"type": "string", "description": "Target unit, e.g. 'c' or 'kg'"},
                },
                "required": ["value", "from_unit", "to_unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_nyc_places",
            "description": (
                "Find museums and parks in New York City from NYC Open Data, with address and website. "
                "Filters are optional. Parks are listed biggest first. Use indoor='indoor' (museums) for "
                "rainy or very cold days. Recommend only places this tool returns, and include their website."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["museum", "park"], "description": "Type of place"},
                    "borough": {"type": "string", "enum": _BOROUGHS, "description": "NYC borough"},
                    "keyword": {"type": "string", "description": "Word in the place name, e.g. 'art' or 'botanical'"},
                    "indoor": {"type": "string", "enum": ["any", "indoor", "outdoor"], "description": "Default 'any'"},
                    "limit": {"type": "integer", "description": "Max results, 1-10 (default 5)"},
                },
            },
        },
    },
]

TOOL_MAP = {
    "list_ny_laws": list_ny_laws,
    "search_ny_law": search_ny_law,
    "get_ny_law_section": get_ny_law_section,
    "convert_units": convert_units,
    "recommend_nyc_places": recommend_nyc_places,
}


def run_tool(name: str, args: dict) -> str:
    """Run one tool call. Models invent tool names and arguments; never let that crash the loop."""
    if name not in TOOL_MAP:
        return _error(f"Unknown tool '{name}'. Available: {list(TOOL_MAP)}")
    try:
        return TOOL_MAP[name](**args)
    except TypeError as e:
        return _error(f"Bad arguments for {name}: {e}")
    except Exception as e:  # last line of defense: a bug in a tool must not kill the agent loop
        return _error(f"Tool {name} crashed: {type(e).__name__}: {e}")