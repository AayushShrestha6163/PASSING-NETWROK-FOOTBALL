# Passing Networks Studio (React)

React port of the original `main.html` / `script.js` / `style.css` front end.
Talks to the same unmodified backend (`api_server.py` -> `predict_server.py`)
via `/api/predict` and `/api/upload`.

## Structure

```
react-app/
├── index.html          # Vite HTML entry, mounts <div id="root">
├── package.json         # deps + scripts (dev / build / preview)
├── vite.config.js        # dev-server proxy: /api -> your Python backend
├── .gitignore
└── src/
    ├── main.jsx          # React root render
    ├── App.jsx           # entire app: matches dropdown, upload, 6 steps,
    │                      #   network/heatmap/sonar SVG builders, tables
    └── style.css          # unchanged original stylesheet
```

## Run it

```bash
cd react-app
npm install
npm run dev
```

By default the dev server proxies `/api/*` requests to `http://localhost:5000`
(edit the `server.proxy` block in `vite.config.js` if your `api_server.py`
listens on a different port).

## Build for production

```bash
npm run build
```

This outputs `dist/index.html` + `dist/assets/*`. Point `api_server.py`'s
static file serving at `dist/` instead of the old `main.html` /
`script.js` / `style.css`, and everything else (all `/api/...` routes)
keeps working unchanged.
