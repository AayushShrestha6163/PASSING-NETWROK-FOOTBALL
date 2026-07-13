# Passing Networks Studio

A standalone version of the course studio: build and analyse a complete
passing network from real match event data, end to end, through six steps -
network, centrality, tactical maps, the match story, and a printable report.

## Run it

```bash
pip install -r requirements.txt
python api_server.py
# then open http://localhost:8000
```

First start takes ~20 seconds while it loads the 31 matches from the Excel
datasets; after that it is instant. The console prints the link when ready.

## The six steps

1. **Load** - pick one of 31 real matches (the 2018 and 2019 Champions League
   finals, plus Euro 2024, World Cup 2022, Copa America 2024, the 2023 Women's
   World Cup and AFCON 2023).
2. **Network** - both teams' passing networks on the pitch, with density, the
   hub, and a per-player table.
3. **Centrality** - betweenness / eigenvector / clustering, Grund
   centralisation, and the weakest link (the man to press) for each team.
4. **Tactical** - 25-zone passing map, direction sonar, zone flow, PPDA, field
   tilt and team shape.
5. **Match Story** - the 5-minute timeline coloured by who led, the match
   verdict (justice score), goal build-up xT trails, and the shot maps.
6. **Report** - a print-ready summary; the Print button saves it as a PDF.

## Add your own match

Use the **Upload** control in the top bar to add StatsBomb-format event data.
A single `.csv` adds one match; a multi-sheet Excel workbook (`.xlsx`) adds
**every sheet as its own match**, all at once (a workbook with ten matches
gives you ten new entries in the dropdown). The new matches appear in the match
list like any of the built-ins.

The minimum required columns are `team_name`, `event_type` and `minute`; the
rest of the StatsBomb schema (player names, pass recipients, locations,
`xt_added`, ...) unlock the full analysis. If a file has no `xt_added` column it
is filled with 0, so the timeline and verdict still run. The Load step lists the
exact columns the bundled matches use as a reference.

## What's in the box

| File | Purpose |
|------|---------|
| `api_server.py` | FastAPI server: serves the UI and exposes the engine over HTTP. |
| `predict_server.py` | The engine - all fourteen analysis modules (unchanged from the course). |
| `main.html`, `style.css`, `script.js` | The browser UI. |
| `champions_league_finals_with_xt.xlsx` | The two CL finals, xT pre-computed. |
| `additional_matches_with_xt.xlsx` | 29 more matches, xT pre-computed. |
| `requirements.txt` | fastapi, uvicorn, pandas, numpy, openpyxl. |
| `CODE_EXPLAINED.pdf` | `api_server.py` explained, plus a tour of the engine's modules. |

## The fourteen modules

Network construction, basic metrics, degree / betweenness / eigenvector /
clustering centrality, Grund centralisation, weakest link, PPDA, field tilt,
team shape, pass sequences, timeline & momentum, and the match verdict +
narrative. They all live in `predict_server.py`; `api_server.py` just loads the
data once and exposes each as a command over `POST /api/predict`.

## Under the hood

The browser posts a single endpoint for everything, for example:

```
POST /api/predict
{ "command": "network", "match_date": "2019-06-01", "team": "Liverpool" }
```

Valid commands: `matches`, `teams`, `network`, `insights`, `tactical`,
`tactical_map`, `zone_directions`, `zone_connections`, `timeline`, `goals`,
`shots`, `compare`. The data is real StatsBomb event data with an `xt` column
already computed for every action.
