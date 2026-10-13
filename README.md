# Climate Hazard Explorer

A React + FastAPI application for historical heatwave analysis using Open-Meteo ERA5 daily maximum temperatures and MongoDB-backed caching.

## Features

- Preset regions and validated custom point / latitude-longitude box inputs.
- Heatwave detection based on a regional grid-cell percentile threshold and consecutive-day rule.
- Annual frequency, duration and intensity metrics, rolling averages, trend summaries, and event history.
- Data-quality indicators and API validation/error handling.
- Annual time-series CSV export and browser Print / Save as PDF.
- URL-persisted analysis selection.

## Requirements

- Node.js compatible with the Vite version in `frontend/package.json`
- Python version compatible with `backend/requirements.txt`
- MongoDB instance

## Run locally

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Copy `backend/.env.example` to `backend/.env` and set the MongoDB connection details. Then run:

```bash
uvicorn app.main:app --reload
```

The API's health endpoint can be used to check service readiness.

### Frontend

In another terminal:

```bash
cd frontend
npm install
```

Copy `frontend/.env.example` to `frontend/.env` and set `VITE_API_URL` to the backend base URL, then run:

```bash
npm run dev
```

For a production bundle, run `npm run build`.

## Export behavior

- **CSV** exports annual series values returned by the API for the selected analysis period.
- **Print / Save as PDF** opens the browser print dialog. Choose “Save as PDF” to create a PDF report.

## Climate interpretation notes

- A heatwave event is a rule-based indicator, not a direct measure of impacts on people.
- The percentile baseline and minimum valid-day requirements affect which years/events qualify.
- Missing or invalid observations must be interpreted as unavailable data, not as non-hazard days.
- Trend estimates and significance should be interpreted cautiously, especially with short or autocorrelated annual series.
- A custom bounding box is represented by sampled grid cells; it is not a full-resolution analysis of every location inside the box.

## Project layout

- `frontend/src`: React UI, API client, query state, and visualizations.
- `backend/app/api`: HTTP endpoints.
- `backend/app/engine`: cleaning, thresholds, event detection, annual metrics, trend analysis, and insights.
- `backend/app/services`: upstream data ingestion, region handling, analysis orchestration, and MongoDB persistence.

## Verification status for this packaged copy

Python source files pass bytecode compilation. The backend test suite was invoked before cleanup, but collection was blocked because several declared dependencies were not installed in the execution environment (`slowapi`, `pymannkendall`, and `mongomock`). The frontend production build could not be run because npm dependencies were not cached and package installation was unavailable offline. Run the checks in an environment with dependencies installed before deployment.
