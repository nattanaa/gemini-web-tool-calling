# NYC Student Helper

## Who it's for and what it does

NYC Student Helper is a chat assistant for **international students who have just moved to New York City**. New arrivals face unfamiliar laws (Can my landlord keep my deposit?), unfamiliar units (Is 45°F cold?), and a huge city to explore. The assistant answers these questions by calling tools that look up real data, such as the official text of New York State law, instead of answering from memory, and it cites its sources.

**Live app:** `<paste your Cloud Run URL here>` (no setup or API key needed)

## Tools

| Tool | What it does |
|---|---|
| `list_ny_laws` | Lists New York State law codes and their 3-letter IDs (e.g. `GOB` = General Obligations Law). |
| `search_ny_law` | Searches New York State laws by keyword and returns matching section titles and links. |
| `get_ny_law_section` | Fetches the official text of one law section from the NY Senate Open Legislation API. |
| `convert_units` | Converts US and metric units (temperature, length, weight, cooking volume, speed, shoe sizes) with exact math. |
| `recommend_nyc_places` | Finds museums and parks from NYC Open Data, filtered by borough, type, name, or indoor/outdoor. |

## How to use it

Open the app and type a question in plain English in the chat box, then press **Enter** or **Send**. You can also click one of the suggested questions above the chat box to get started. Under each answer, the app shows which tools were called; click a tool row to see the exact request and data returned. Use **New chat** to start over.

**Example queries:**

1. *Can my landlord charge me two months' rent as a security deposit?*
   The assistant searches New York law, reads General Obligations Law § 7-108, and explains the one-month limit with a link to the official text.
2. *It's 45°F today. What is that in Celsius, and is it cold?*
   The assistant converts the temperature (about 7°C) and explains what that feels like.
3. *What are the biggest parks in the Bronx?*
   The assistant lists the largest Bronx parks from NYC Open Data, with their size and address.

Questions can also combine areas, for example *"It's 35°F, what's that in Celsius? If it's cold, suggest an indoor museum in Manhattan."*

## How it works

```
Browser (index.html)
   │  POST /chat {message, session_id}
   ▼
FastAPI (app.py) ── the harness loop ─────────────────────────┐
   │ 1. send conversation + tool descriptions to Gemini        │
   │ 2. model replies with text?  → return the answer          │
   │    model asks for a tool?    → run_tool(name, args)       │
   │ 3. append the tool result to the conversation, go to 1    │
   │    (stops after MAX_TOOL_ROUNDS)                          │
   └────────────────────────────────────────────────────────────┘
   │
   ▼
tools_nat.py   TOOLS (what the model sees) + TOOL_MAP (what Python runs)
```

The **model decides** which tool to call and when it has enough information; the **harness** only runs the tools and enforces a round limit. Behavior is steered by three pieces of text: the system prompt in `app.py`, each tool's description, and hints inside tool results (for example, search results say *"These are titles only. Call get_ny_law_section to read the actual text."*).

### Design choices

- **Tools return errors as JSON, never exceptions.** The model cannot see a Python traceback, but it can read `{"error": "PEN section '99999' was not found..."}` and recover. `run_tool` also catches anything unexpected so a tool bug never crashes the chat.
- **Law answers must be grounded.** The prompt forbids explaining a section the model has not read, and every law result includes a `source_url` to the official text.
- **Search tries the exact phrase first.** A plain search for `security deposit` matched sections about LIBOR and checks; quoting the phrase surfaces GOB § 7-107 and § 7-108.
- **Unit math is never done "in the model's head."** Conversions use exact factors (1 in = 0.0254 m), and heights also come back as feet + inches.


## Project structure

```
app.py                  FastAPI server + agent loop + system prompt
tools_nat.py            All 5 tools, their JSON descriptions, and run_tool
index.html              Chat UI
build_places.py          One-time download of NYC Open Data → data/nyc_places.json
data/nyc_places.json    Museums and parks used by recommend_nyc_places
test_student_tools.py   Tests for the converter and place finder
```

## Limitations

- Law tools cover **New York State** consolidated laws only, not NYC local law, regulations (such as labor rules in NYCRR), or case law.
- The NYC Museums dataset is outdated; always check a museum's website before visiting. Parks data is current (updated 2026).
- Neighborhood filtering is not supported; the smallest area is the borough.
- Shoe sizes are approximate, since sizing differs by brand.
- Conversations are stored in memory and reset when the server restarts.

> This app gives general information, not legal advice.