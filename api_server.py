"""
Build & Analyse Passing Networks - standalone studio.

A FastAPI server + browser UI that runs the whole analysis pipeline on real
StatsBomb match data: passing networks, centrality algorithms, tactical maps
(25-zone heatmaps, sonars, zone flow), the match timeline and the verdict.

It wraps the course engine (predict_server.py) unchanged - that single file
holds all fourteen analysis modules (network construction, degree /
betweenness / eigenvector / clustering centrality, Grund centralisation,
weakest link, PPDA, field tilt, team shape, pass sequences, timeline &
momentum, and the match verdict). This server just loads the data once and
exposes those modules over HTTP for the browser UI.

Run:
    pip install -r requirements.txt
    python api_server.py
    # open http://localhost:8000
"""

import os
import sys
import json
import re
import time
import io
import base64

# Serve the HTML/CSS/JS and the Excel datasets by relative path regardless of
# where the server is launched from.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from contextlib import asynccontextmanager, redirect_stdout

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import pandas as pd

# The engine. Importing it is safe: all of its work sits behind a
# `if __name__ == "__main__"` guard, so nothing runs until we call load_data().
import predict_server as engine


def _clean(o):
    """Recursively turn NaN / Infinity floats into null so the JSON is valid
    for the browser's JSON.parse (NaN/Infinity are not legal JSON tokens)."""
    if isinstance(o, float):
        return None if (o != o or o == float("inf") or o == float("-inf")) else o
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    return o


URL = "http://localhost:8000"

# The built React app (run `npm run build` inside react-app/) lands here.
REACT_DIST = os.path.join("react-app", "dist")
REACT_INDEX = os.path.join(REACT_DIST, "index.html")


@asynccontextmanager
async def lifespan(app):
    n = engine.load_data()
    bar = "=" * 56
    built = os.path.isfile(REACT_INDEX)
    hint = (f"   Open  {URL}  in your browser."
            if built else
            "   React build not found yet - run:\n"
            "     cd react-app && npm install && npm run build\n"
            "   Until then, run the frontend separately with `npm run dev`\n"
            "   (http://localhost:5173) - it proxies /api to this server.")
    print(f"\n  {bar}\n   Passing Networks studio is ready ({n} matches).\n"
          f"  {hint}\n  {bar}\n", flush=True)
    yield


app = FastAPI(title="Passing Networks", lifespan=lifespan)

# Serve the built React app's JS/CSS bundle (react-app/dist/assets/*) at /assets.
if os.path.isdir(os.path.join(REACT_DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(REACT_DIST, "assets")), name="assets")


@app.get("/")
def index():
    # Serve the built React app if it exists...
    if os.path.isfile(REACT_INDEX):
        return FileResponse(REACT_INDEX)
    # ...otherwise don't crash the server - explain how to get it, since the
    # old main.html/script.js/style.css frontend no longer exists.
    return JSONResponse(
        status_code=404,
        content={
            "error": "React build not found.",
            "fix": [
                "Run the dev frontend instead: cd react-app && npm install && npm run dev, "
                "then open http://localhost:5173",
                "Or build it for production: cd react-app && npm run build, then reload this page.",
            ],
        },
    )


@app.post("/api/predict")
async def predict(req: Request):
    """One endpoint for the whole pipeline. The browser posts a command such as
    {command: 'network', match_date: '2019-06-01', team: 'Liverpool'} and gets
    that module's result. Valid commands: matches, teams, network, insights,
    tactical, tactical_map, zone_directions, zone_connections, timeline, goals,
    shots, compare, player, health."""
    cmd = await req.json()
    # Route the engine's own prints to stderr so the HTTP response is clean JSON.
    with redirect_stdout(sys.stderr):
        result = engine.handle_command(cmd)
    body = json.dumps(_clean(result), default=str)
    return Response(content=body, media_type="application/json")


def _json(obj):
    return Response(json.dumps(_clean(obj), default=str), media_type="application/json")


def _register(df, key_hint):
    """Validate one match dataframe and register it in the engine's in-memory
    store under a unique key. Returns a summary, or None if the schema is wrong."""
    if {"team_name", "event_type", "minute"} - set(df.columns):
        return None
    if "xt_added" not in df.columns:
        df["xt_added"] = 0.0
    key = re.sub(r"[^A-Za-z0-9_.\-']+", "_", str(key_hint)).strip("_") or ("upload_%d" % int(time.time()))
    base, i = key, 1
    while key in engine.MATCH_DATA:
        i += 1
        key = f"{base}_{i}"
    engine.MATCH_DATA[key] = df
    return {"match_date": key, "events": int(len(df)),
            "teams": df["team_name"].dropna().unique().tolist()}


@app.post("/api/upload")
async def upload(req: Request):
    """Add match(es). The browser sends either a single CSV as text, or a
    multi-sheet Excel workbook as base64 - and every valid sheet in the
    workbook becomes its own match in the dropdown. New matches show up in the
    match list exactly like the built-ins."""
    body = await req.json()

    # --- Excel workbook: register EVERY sheet as its own match ---
    b64 = body.get("xlsx_b64")
    if b64:
        try:
            xl = pd.ExcelFile(io.BytesIO(base64.b64decode(b64)))
        except Exception as e:
            return _json({"error": f"Could not read the Excel file: {e}"})
        return _register_workbook(xl)

    # --- Single CSV ---
    csv_text = body.get("csv_text") or ""
    if not csv_text.strip():
        return _json({"error": "No CSV or Excel content received."})
    name = (body.get("match_name") or "").strip()
    if name.lower().endswith(".csv"):
        name = name[:-4]
    info = _register(pd.read_csv(io.StringIO(csv_text)), name)
    if not info:
        return _json({"error": "CSV is missing required columns (team_name, event_type, minute)."})
    return _json({"status": "ok", "added": [info], "matches_loaded": len(engine.MATCH_DATA)})


def _register_workbook(xl):
    added = []
    for sheet in xl.sheet_names:
        if str(sheet).strip().lower() == "summary":
            continue
        info = _register(pd.read_excel(xl, sheet_name=sheet), sheet)
        if info:
            added.append(info)
    if not added:
        return _json({"error": "No valid match sheets found (each needs team_name, event_type, minute)."})
    return _json({"status": "ok", "added": added, "matches_loaded": len(engine.MATCH_DATA)})


if __name__ == "__main__":
    # log_level="warning" keeps the console to just the ready banner. The server
    # binds 0.0.0.0 (reachable on your network); open it at http://localhost:8000.
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")