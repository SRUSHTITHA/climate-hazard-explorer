# working.md

## 1. Brief

Problem Statement

Build a web application that analyzes historical weather data and visualizes trends in climate hazards, such as heatwaves, droughts, or heavy rainfall events, for a selected region over time.

Key Features

Frontend (React)
Allow users to:
- Select a geographic region (city, state, or a custom lat-lon box).
- Use Heatwave as the hazard type, selected by default.
- Choose a time range (e.g. 1990-2020).
Display:
- Time-series plots of hazard frequency/intensity.
- Interactive visualizations (e.g. charts, maps).
- Summary insights such as "Heatwaves have increased by 40% in this region since 1990."

Backend (Python)
Ingest and cache historical weather data from public APIs such as:
- NOAA NCEI
- Copernicus Climate Data Store
- Open-Meteo API
- Or any other source
Define logic to detect climate hazards:
- Example (Heatwave): 3+ consecutive days with maximum temperature above the 95th percentile for that region.
- Analyze frequency and duration trends using rolling averages or regression.
- Store this data in a NoSQL database.
- On an API call, read this data from the database and return JSON summaries and trend plots.

Evaluation Dimensions

| Dimension | What we look for | Weight |
|---|---|---|
| Data Handling | Working with real-world noisy, inconsistent data: gaps, outliers, units, caching | 20% |
| Climate Logic | Ability to define and apply domain-specific rules (e.g. a percentile-based heatwave definition) | 20% |
| Backend Skills | Efficient data processing, clean API design, safe external API access | 20% |
| Frontend Skills | Clear, interactive visualization using Chart.js, D3.js, or similar | 15% |
| Critical Thinking | Deriving sound, honest insight from climate indicators | 10% |
| Security + Performance | API caching, rate-limiting, and safe handling of user inputs | 15% |

Optional (attempt only after the core features work)
- Use a map UI (e.g. Leaflet or Mapbox) for region selection.
- Provide PDF/CSV export of insights.
- Apply trend detection techniques such as linear regression or the Mann-Kendall test.

## 2. Locked Decisions
- Data source: Open-Meteo archive API (ERA5 reanalysis, ~0.25 degree grid), variable temperature_2m_max, units Celsius, explicit timezone parameter. Host is hardcoded in code, never user-supplied.
- Ingest window: 1990 through the last complete calendar year. Whole history fetched once per grid cell, in chunks.
- Grid: coordinates snapped to 0.25 degrees. cell_id format "{lat:.2f}_{lon:.2f}" using snapped values.
- Region input: point (city, state preset, geocoded place) or box. A box resolves to the set of grid cells inside it. Hard cap: 9 cells, otherwise HTTP 422.
- Baseline for thresholds: 1991-2020, always, regardless of the user's selected range.
- Selectable range: 1990 to last complete year, minimum span 10 years.
- Day index: leap-aligned day of year, 1..366, where Mar 1 is always 61 (Feb 29 occupies slot 60 only in leap years).
- Threshold: per day-index, 95th percentile (numpy nanpercentile, linear interpolation) of tmax over baseline years within a circular +/-7 slot window.
- Heatwave: 3 or more consecutive days with tmax strictly greater than that day's threshold. A missing value breaks a run. Events are detected on the continuous multi-year series and assigned to the year of their start date.
- Year validity: at least 90% non-null days. Invalid years are excluded from metrics and trends and listed in the quality report.
- Annual metrics: event_count, heatwave_days, longest_event_days, mean_duration_days, mean_intensity_c (mean exceedance over threshold), season_start_doy, season_end_doy.
- Region metrics: mean of per-cell annual metrics across valid cells.
- Trend: Theil-Sen slope (scipy) of heatwave_days per year, reported per decade; Mann-Kendall (pymannkendall) p-value; 5-year centered rolling mean with min 3 periods.
- Confidence: needs at least 15 valid years or result is "insufficient data". p < 0.05 "strong evidence", 0.05 to 0.15 "weak evidence", otherwise "no clear trend".
- Percent change: only when the first-5-year mean is at least 1.0 days per year; otherwise report absolute change.
- Insights are produced by deterministic code, never by an LLM.
- Backend: Python 3.11+, FastAPI sync endpoints, httpx sync, pymongo, pandas, numpy, scipy, pymannkendall, pydantic v2 and pydantic-settings, slowapi. Tests: pytest, mongomock. Lint: ruff.
- Frontend: Vite, React, plain JavaScript, Chart.js via react-chartjs-2, TanStack Query, Leaflet for the optional map. State lives in URL query params.
- Hosting: frontend on Vercel or Netlify, backend on Render, database on MongoDB Atlas M0.

## 3. Repo Layout
  working.md, README.md, .gitignore
  backend/app/{main.py, config.py, db.py}
  backend/app/api/        routes only
  backend/app/services/   ingestion, analysis orchestration
  backend/app/engine/     thresholds, events, metrics, trends, insights (pure functions)
  backend/app/models/     pydantic schemas
  backend/app/data/       indian_regions.json
  backend/tests/
  backend/{requirements.txt, requirements-dev.txt, pyproject.toml, .env.example}
  frontend/ (created in Task 17)

## 4. Data Contracts (MongoDB)
- raw_daily: one doc per cell-year. {cell_id, year, source, fetched_at, unit, tmax: [float|null, one entry per calendar day of that year], valid_days, total_days}. Unique index (cell_id, year).
- thresholds: {cell_id, baseline_start, baseline_end, window_days, percentile, values: [366 floats], computed_at}. Unique index on first five fields.
- events: {cell_id, hazard, year, start, end, duration_days, mean_exceedance_c, peak_tmax_c}. Dates as ISO strings.
- annual_metrics: {cell_id, hazard, year, event_count, heatwave_days, longest_event_days, mean_duration_days, mean_intensity_c, season_start_doy, season_end_doy, valid_fraction}. Unique index (cell_id, hazard, year).
- analyses: {key, region, cell_ids, hazard, start_year, end_year, created_at, result}. TTL index on created_at.

## 5. Conventions
- Naming, error format, commit style, test style (filled in as tasks establish them).

## 6. Domain Notes
(theory and rationale are appended here by tasks)

## 7. Assumptions
- Task 01. The only interpreter available in this environment is Python 3.14.1. Locked Decisions state Python 3.11+; 3.14.1 satisfies "3.11 or newer", so it is accepted and all packages were installed from cp314 wheels.
- Task 01. The virtual environment lives at the repository root as `.venv/` (git-ignored). Acceptance commands are run with that interpreter from `backend/`.
- Task 01. `uvicorn[standard]` is pinned to the resolved `uvicorn` version reported by `pip freeze`, since `pip freeze` reports the extra under the base package name.
- Task 01. The package-import test uses `importlib.import_module` over a tuple of names instead of five literal `import` statements, because literal imports would be flagged F401 by ruff and no module-level symbol is needed.

## 8. Task Log

### Task 01 - Repository scaffold, working.md, backend tooling
Changed:
- Created the Section 3 layout: `backend/app/{api,services,engine,models,data}`, `backend/tests`, plus empty `__init__.py` in `app`, `app/api`, `app/services`, `app/engine`, `app/models`, `tests`. `app/data` is a data directory, not a package, so it has no `__init__.py`. `frontend/` intentionally not created.
- `working.md` at repo root with all ten sections; Section 1 holds the problem statement and evaluation table verbatim.
- `README.md` (title plus one sentence), root `.gitignore`, `backend/pyproject.toml` (ruff line-length 100, rules E/F/I/B/UP; pytest testpaths `tests`), `backend/.env.example`, `backend/tests/test_package_imports.py`.
- `backend/requirements.txt` and `backend/requirements-dev.txt`, pinned from `pip freeze` of a fresh venv, not from memory.

Installed versions (pip freeze):
- fastapi==0.143.0, uvicorn[standard]==0.54.0, httpx==0.28.1, pymongo==4.18.3, pandas==3.0.6, numpy==2.5.4, scipy==1.18.1, pymannkendall==1.4.3, pydantic==2.14.0, pydantic-settings==2.15.0, slowapi==0.1.10
- pytest==9.1.1, mongomock==4.3.0, ruff==0.17.0

Decisions:
- Interpreter is Python 3.14.1 (see Assumptions); `.venv` kept at repo root and git-ignored.
- No application logic; `main.py`, `config.py`, `db.py` contents deferred to Task 02. No files created beyond the Task 01 scope.

Acceptance evidence:
- `python --version` -> Python 3.14.1.
- `pip install -r requirements.txt -r requirements-dev.txt` -> success (all requirements already satisfied).
- `ruff check .` -> "All checks passed!".
- `ruff format --check .` -> "7 files already formatted".
- `pytest` -> collected and passed exactly 1 test.
- `git status --short` -> only `.gitignore`, `README.md`, `backend/`, `working.md`; no `.env`, no venv, no cache files.

Self-challenge:
- Every pin in both requirements files matches `pip freeze` output (scripted comparison, "ALL PINS MATCH pip freeze").
- `working.md` contains all ten sections and Section 2 reproduces the locked decisions without alteration.
- Adversarial: an unused `import os` was added and ruff reported F401, then the file was removed and ruff passed again.
- Adversarial: renaming the `app/services` directory made the import test fail with `ModuleNotFoundError: No module named 'app.services'`, then it passed after restore.
- Adversarial (boundary): deleting only `app/services/__init__.py` did not fail the test, because Python treats the directory as an implicit namespace package. Recorded in Open Issues.

## 9. Open Issues
- The import test proves the five modules are importable but cannot assert the presence of the empty `__init__.py` files, because Python namespace packages make a directory without `__init__.py` still importable. The `__init__.py` files are present as required; this is only a verification gap.

## 10. My Notes
- Task 01: scaffolded the backend base exactly from the Section 3 tree, pinned every version from a real venv freeze, and left all application logic for later tasks. The only friction was ruff's F401 on the deliberate import test, solved with `importlib`.
