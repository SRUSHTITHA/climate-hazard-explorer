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
- Data source: Open-Meteo archive API (ERA5 reanalysis, ~0.25 degree grid), variable temperature_2m_max, units Celsius, explicit timezone parameter. Host is hardcoded in code, never user-supplied. Request parameters are fixed: daily=temperature_2m_max, temperature_unit=celsius, timezone=auto, models=era5. ERA5 is pinned because the default "Best match" blends ECMWF IFS 9 km data from 2017 onward, which would introduce an artificial discontinuity in a multi-decade series; Open-Meteo's documentation recommends ERA5 or ERA5-Land only for climate-change studies. cell_selection and elevation are left at their defaults.
- Ingest window: 1990 through the last complete calendar year. Whole history fetched once per grid cell, in chunks.
- Grid: coordinates snapped to 0.25 degrees. cell_id format "{lat:.2f}_{lon:.2f}" using snapped values.
- Region input: point (city, state preset, geocoded place) or box. A box resolves to the set of grid cells inside it. Hard cap: 9 cells, otherwise HTTP 422.
- Baseline for thresholds: 1991-2020, always, regardless of the user's selected range.
- Selectable range: 1990 to last complete year, minimum span 10 years.
- Day index: leap-aligned day of year, 1..366, where Mar 1 is always 61 (Feb 29 occupies slot 60 only in leap years).
- Threshold: per day-index, 95th percentile (numpy nanpercentile, linear interpolation) of tmax over baseline years within a circular +/-7 slot window.
- Heatwave: 3 or more consecutive days with tmax strictly greater than that day's threshold. A missing value breaks a run. Events are detected on the continuous multi-year series and assigned to the year of their start date.
- Year validity: at least 90% non-null days. Invalid years are excluded from metrics and trends and listed in the quality report.
- Physical validity bounds: -90.0 to 60.0 degrees Celsius inclusive. Values outside, non-finite values, and non-numeric values are invalid and become NaN.
- Suspect flag (flag only, never removed): absolute deviation greater than 15 degrees Celsius from the centred 15-day rolling median (min_periods 8).
- Missing values and missing dates are never imputed.
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

### API Contracts
- GET /health -> always HTTP 200 with body {"status": "ok", "database": "up"|"down"}. "up" only when db.command("ping") succeeds; exceptions are swallowed, never leaked in the response. The endpoint never returns non-200 and never reveals the exception text.

### Upstream Contract
- Request (GET https://archive-api.open-meteo.com/v1/archive), exactly eight params: latitude, longitude (from regions.cell_center), start_date "YYYY-01-01", end_date "YYYY-12-31", daily=temperature_2m_max, temperature_unit=celsius, timezone=auto, models=era5. No api key on the free tier. Redirects not followed.
- Response fields observed in the three real calls: latitude, longitude, generationtime_ms, utc_offset_seconds, timezone, timezone_abbreviation, elevation, daily_units {time, temperature_2m_max}, daily {time: [ISO dates], temperature_2m_max: [numbers with null for missing]}. daily_units.temperature_2m_max is literally "°C".
- With models=era5 the response latitude/longitude equal the requested coordinates exactly (call 1: 28.5, 77.25). Without models (default Best match) they are the nearest ~9 km IFS grid point (call 2: 28.50615, 77.20136). Error responses are HTTP 400 with body {"error": true, "reason": "..."} (call 3).

## 5. Conventions
- Code is minimal and reuse-first (see Standing Preamble). Shared helpers live in one place and are imported, never duplicated.
- Settings are read only through app.config.get_settings(). The database is obtained only through the app.db.get_db dependency.
- Each router lives in its own file under app/api/ and is registered in main.py.
- services raise RegionError for invalid regions; the API layer translates it to HTTP 422 in Task 13. Other modules import cell_id, cell_center and cells_in_box and never re-implement snapping or cell_id formatting.
- External HTTP access happens only through app/services/open_meteo.py; no other module imports httpx to call upstream services.
- app/engine contains pure functions only; it never imports from app.services, app.api or app.db.

## 6. Domain Notes
- Fixed 0.25-degree grid as cache key: adjacent or overlapping requests snap to the same cell_ids, so cached raw data and thresholds are shared across requests and the fan-out of upstream Open-Meteo calls per request is bounded. The grid is the identity of cached data, not a projection; it exists for determinism and cache reuse.
- Cap of 9 cells per region: limits upstream calls and per-request compute, protecting the free API tier and bounding response latency. The cap is checked from index counts before any list is built, so absurd boxes (e.g. the whole world) are rejected in microseconds, not enumerated.
- Half-up rounding (floor(v/0.25 + 0.5) * 0.25) is deterministic and free of banker's-rounding surprises; Python's round() uses round-half-even, which would make tie behaviour depend on the parity of the preceding digit. Negative zero is normalised so IDs are "0.00" and never "-0.00".
- Antimeridian: boxes crossing longitude 180/-180 (west > east) are intentionally unsupported; every cell_id is still a legal lon in [-180, 180], and any grid near the antimeridian is addressable by individual cell_id.
- Verified against Open-Meteo docs (https://open-meteo.com/en/docs/historical-weather-api): the Historical Weather API resolves a requested coordinate to the nearest model grid cell; the response's latitude/longitude are "WGS84 of the center of the weather grid-cell which was used to generate this forecast. This coordinate might be a few kilometres away from the requested coordinate." ERA5 is listed as Global, 0.25 deg (~25 km), hourly, 1940-present. So our 0.25-degree cache grid matches the ERA5 native grid, and the resolved cell center is what the API actually returns for tmax.
- Locked Decision amendment, 2026-10-11 (Task 04): pinned models=era5. Open-Meteo's default "Best match" combines ECMWF IFS (9 km) from 2017 onward with ERA5 before that, which would inject a resolution change mid-series and fake a trend; the docs explicitly advise using ERA5 or ERA5-Land only for climate-change studies over decades. Pinning era5 keeps one homogeneous model across 1990-present.
- ERA5 homogeneity: a single reanalysis product at fixed 0.25-degree resolution with a consistent assimilation system means year-to-year differences reflect weather/climate, not model changes. This matters because the whole product is about multi-decade trends, where a model discontinuity would dominate the signal.
- ERA5's native 0.25-degree grid coincides with our cache grid: with models=era5 the archive API returned exactly the requested snapped coordinates (28.5, 77.25), so one cell_id maps to exactly one ERA5 grid point and cached data cannot be silently served for a different upstream cell.
- Daily maxima are aggregated on the timezone's calendar-day boundaries. With timezone=auto the UTC offset is resolved once, at request time, and any DST change inside the requested range is ignored (documented by Open-Meteo). Accepted limitation: a one-hour shift moves the 24-hour window by an hour, which has a negligible effect on a daily maximum (and our ingest window is whole years).
- The returned grid cell can sit a few km from the requested point. Observed in the pasted real responses: call 2 (default Best match) requested (28.5, 77.25) and returned (28.50615, 77.20136), a great-circle distance of 4.802 km; call 1 (models=era5) returned the requested point exactly (0 km). This is why the client stores grid_lat/grid_lon from the response rather than assuming the request coordinates.
- Open-Meteo free-tier limits (read 2026-10-11 from https://open-meteo.com/en/pricing and https://open-meteo.com/en/terms): 600 calls/minute, 5,000 calls/hour, 10,000 calls/day, 300,000 calls/month; free tier is non-commercial use only. The Historical Weather API is available on the free tier.
- Attribution (read 2026-10-11 from https://open-meteo.com/en/licence): API data are offered under CC BY 4.0, which mandates giving appropriate credit and indicating modifications. Open-Meteo requires a link next to any location where its data is displayed, e.g. `<a href="https://open-meteo.com/">Weather data by Open-Meteo.com</a>`. The underlying ERA5 reanalysis comes from Copernicus Climate Change Service (C3S) and must also be acknowledged. Server code is AGPLv3; the data licence is what binds us.
- Statistical outliers are flagged, never removed: in a heatwave study the extreme days are the signal, not noise. Dropping a suspect 50 C day would bias event counts and mean exceedance intensities downward; keeping it lets the event logic (Task 07) decide, with the suspect flag available as context.
- No imputation: interpolation across a missing day could create or erase consecutive above-threshold runs - hand-inserting a plausible 34 C instead of 29 C decides whether a heatwave "happened". Instead, a missing day stays a gap (a run is inherently broken) and metrics stay honest.
- The [-90, 60] C bounds are far wider than any real ERA5 daily maximum but narrow enough to catch unit mix-ups and keying errors: a Fahrenheit-style 104 (about 40 C) and anything misread or sign-flipped is rejected. A units bug surfaces in the quality report as invalid_days instead of silently warping trends and thresholds.
- Partial years fail the 90% coverage rule by construction: coverage is scored against the full 365/366 days of the calendar year, not against the days present, so e.g. a July-to-December probe scores ~0.5 and is excluded. This protects threshold and trend statistics from years that are missing a whole season.
- ERA5 is documented as a gap-free reanalysis product, so for real data the gap count is expected to be near zero (the live 2000-2009 probe shows missing_days 0). The tests carry machine-checked proof that clean_daily both represents gaps when genuinely present and yields none for clean data.

## 7. Assumptions
- Task 01. The only interpreter available in this environment is Python 3.14.1. Locked Decisions state Python 3.11+; 3.14.1 satisfies "3.11 or newer", so it is accepted and all packages were installed from cp314 wheels.
- Task 01. The virtual environment lives at the repository root as `.venv/` (git-ignored). Acceptance commands are run with that interpreter from `backend/`.
- Task 01. `uvicorn[standard]` is pinned to the resolved `uvicorn` version reported by `pip freeze`, since `pip freeze` reports the extra under the base package name.
- Task 01. The package-import test uses `importlib.import_module` over a tuple of names instead of five literal `import` statements, because literal imports would be flagged F401 by ruff and no module-level symbol is needed.
- Task 02. Settings load `backend/.env` by absolute path computed from `config.py` location (independent of CWD); env vars take precedence over the dotenv file, and explicit `Settings(...)` kwargs take precedence over both, which is how the tests stay hermetic without a real .env.
- Task 02. pydantic-settings 2.15.0 does NOT parse a comma-separated string into a list automatically (a `list[str]` field fed `"a, b"` raises SettingsError). Verified by running code; therefore `cors_allowed_origins` stays `str` with a `cors_origins` property. This is the simplest working approach.
- Task 02. mongomock 4.3.0 supports `db.command("ping")` (returns {"ok": 1.0}), verified by running it, so no patching was needed for the "up" test.
- Task 02. A `tests/conftest.py` sets MONGODB_URI to a dummy localhost string (setdefault) so importing `app.main` works during pytest without a real .env; tests never connect because `get_db` is overridden in the health tests.
- Task 02. FastAPI/Starlette version raises a StarletteDeprecationWarning suggesting `httpx2` for TestClient; not actionable because no new dependency may be added (constraint), noted in Open Issues.
- Task 02 (live). A live {"status":"ok","database":"up"} against MongoDB Atlas could not be verified: no mongod, no cluster creds, no .env in this environment. The "down" path was verified live instead (see Task Log). Deferred in Open Issues.
- Task 03. Coordinates passed as strings raise TypeError ("must be real number, not str") rather than RegionError. Type coercion is deliberately not added: the API is typed `float` and the FastAPI layer (Task 13) rejects wrong types with 422 before the module runs. Reported as an honest observation, not papered over.
- Task 03 (superseded in Task 04). `cell_center` originally did not validate its input. Task 04 requires that an invalid cell_id (e.g. "abc", "999.00_0.00") cannot reach the network, so `cell_center` now parses, range-checks and raises RegionError before any client is built.
- Task 04. The deliverable's test bullet "success with 5 days" cannot pass through `fetch_daily_tmax`: requests are whole-year (start=YYYY-01-01, end=YYYY-12-31) and the response length must equal the calendar days in that range, so a 5-day response fails the length check by design. The success test therefore uses a full 2024 year (366 days) with one null preserved; the pasted 5-day payloads are recorded under Upstream Contract.
- Task 04. Free-tier numbers and the attribution requirement were read from the official pages on 2026-10-11 (URLs in Domain Notes); no figure was recalled from memory.
- Task 05. Missing vs invalid: a day is missing when the input value is `None` or the date is absent from the range; invalid means a value was present but unusable - non-numeric (strings, booleans), non-finite (NaN or inf passed as a value), or outside [-90, 60]. The task text's "missing_days counts None, NaN and absent dates" conflicts with its own required test "nan ... counted in invalid_days"; the test decides: a raw NaN passed as a value is non-finite data and counts invalid, while the NaN left by None/absent dates counts missing. The two masks are recorded in series.attrs during cleaning and never re-derived.
- Task 05. Vectorisation holds on the happy path: every per-day classification is a numpy/pandas vectorised op. `_parse_index` runs one `all(isinstance(...))` generator over the date strings - input validation, not a data loop.
- Task 05. `pd.to_numeric(errors="coerce")` raises OverflowError for Python ints too large for float64 (e.g. 10**400). A guarded `np.frompyfunc(_as_float, ...)` fallback converts such entries to NaN so they are handled as out-of-tolerance instead of crashing; covered by a test.

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

### Task 02 - Backend skeleton: configuration, MongoDB connection, health endpoint
Changed:
- `app/config.py` (25 lines): pydantic-settings `Settings` with mongodb_uri (no default), mongodb_db_name, cors_allowed_origins, rate_limit_default, rate_limit_compute (defaults suit local dev); `cors_origins` property returns a cleaned list; `get_settings()` lru_cached; `.env` loaded by absolute path from `backend/`.
- `app/db.py` (15 lines): lru_cached `MongoClient` with `serverSelectionTimeoutMS=5000`; `get_db()` returns the configured database for use as a FastAPI dependency (overridable in tests).
- `app/api/health.py` (18 lines): GET /health using `Annotated[Database, Depends(get_db)]` (Annotated form required because ruff B008 bans Depends in defaults), returns 200 with "down" on any exception.
- `app/main.py` (14 lines): FastAPI app with CORSMiddleware (allow_origins from settings, methods GET/POST, allow_credentials=False), includes the health router.
- `tests/test_config.py` (11 lines), `tests/test_health.py` (38 lines), `tests/conftest.py` (3 lines) per Assumptions.

Decisions:
- `cors_allowed_origins` kept as plain `str`; list-field parsing verified by code to fail in pydantic-settings 2.15.0 before deciding.
- No connection at import time: `MongoClient` is constructed lazily on first `get_db()` call and even then connects only on the first operation; the app starts when MongoDB is unreachable.
- No new dependencies; `httpx`/`starlette` deprecation warning is not fixed (cannot add httpx2).

Acceptance evidence:
- `ruff check .` -> All checks passed; `ruff format --check .` -> 16 files already formatted.
- `pytest` -> 24 passed (5 from this task incl. both /health tests via mongomock override).
- MONGODB_URI unset, `import app.main` -> pydantic ValidationError "mongodb_uri Field required" (clear settings error, no stack of unrelated errors).
- Wrong host `mongodb://127.0.0.1:27100/db`: live uvicorn -> `{"status":"ok","database":"down"}` after ~5.6 s, server kept running (SERVER_ALIVE=True), subsequent requests fine.
- CORS: `curl -s -i -H "Origin: http://evil.example" localhost:8000/health` -> HTTP 200 with NO `access-control-allow-origin` header.
- No secret/URI value appears in log lines or response body (logs inspected).
- Live {"status":"ok","database":"up"} against Atlas NOT run (no cluster); recorded in Open Issues.

Self-challenge:
- Adversarial: MONGODB_URI unset -> clean ValidationError; MONGODB_URI bogus -> graceful "down" and server survives; CORS evil origin -> no ACAO header; `.env` never created meanwhile, `git status --short` shows no `.env`.
- Files over 25 lines: test_health.py (38) is tests (fixtures + two integration-style cases); no app file exceeds 25.

### Task 03 - Grid snapping and region resolver
Changed:
- `app/services/regions.py` (54 lines total, 39 non-blank): GRID_STEP=0.25, MAX_CELLS=9, `RegionError(ValueError)` with end-user messages, `cell_id`, `cell_center`, `cells_in_box`; validation and snapping are private helpers (`_validate`, `_snap_index`, `_snap`) reused by the public functions; the 9-cell cap is checked from index counts before enumeration so huge boxes fail instantly.
- `tests/test_regions.py` (89 lines): the exact expected values from the spec plus parametrized rejection cases.

Justification for size (39 non-blank vs ~35 target): the module packs the spec-mandated coordinate rules (finite + range checks, half-up tie handling, negative-zero normalisation, inversion checks) and five distinct end-user error messages that cannot be shortened without losing required clarity; the enumeration is index-based per spec and reuses `cell_id` for identity (no re-implementation).

Decisions:
- Deterministic half-up via `math.floor(value / 0.25 + 0.5)`, index*GRID_STEP for both snapping and enumeration (no float accumulation).
- Negative zero normalised to 0.0 inside `_snap`; indices are ints so enumeration can never produce -0.00.
- `cells_in_box` reuses `cell_id(lat_idx*GRID_STEP, lon_idx*GRID_STEP)`, keeping cell identity in one place.

Acceptance evidence:
- `ruff check .`, `ruff format --check .` -> clean; `pytest` -> 24 passed.
- `cell_id(28.6139, 77.2090)` -> `28.50_77.25`.
- World-box check: prints "A region is limited to 9 grid cells." then True (< 0.1 s).

Self-challenge:
- Repo search: only `app/services/regions.py` implements snapping/cell_id formatting (GRID_STEP, _snap, ":2f"); tests and docs reference the module but never re-implement it.
- Adversarial inputs (run): strings `cell_id('28','77')` -> TypeError (recorded in Assumptions, not coerced); zero-area box (s==n, w==e) -> exactly 1 cell; sub-cell box (28.55..28.57, 77.05..77.07) -> 1 cell; `cell_id(-90, 180)` -> "-90.00_180.00"; Indian subcontinent (6,68,36,98) -> RegionError (121x121 cells, far over cap; entire-subcontinent analysis is impossible under the 9-cell cap and must use point/preset queries instead); `cell_id(0.2499,0.2499)` -> 0.25_0.25; `cell_id(-0.25,-0.25)` -> -0.25_-0.25 (exact tie floors down, consistent with half-up).
- Error hygiene: all five RegionError messages collected and scanned; none contains a stack trace, file path, Python type name or hex address.

### Task 04 - Open-Meteo archive client
Changed:
- `app/services/open_meteo.py` (136 lines total, 119 non-blank): constants ARCHIVE_URL, TIMEOUT_SECONDS, MAX_ATTEMPTS=3, BACKOFF_BASE_SECONDS, MAX_RETRY_AFTER_SECONDS, MIN_YEAR; `UpstreamError`; `fetch_daily_tmax` plus `_validate_year_range`, `_fetch_with_retries`, `_retry_delay`, `_validated_payload`. Coordinates come only from `regions.cell_center`; params are passed via httpx `params=`; redirects not followed; own client is closed, injected client is not; one generic end-user message, upstream reason logged server-side only.
- `app/services/regions.py`: `cell_center` now validates and raises RegionError for malformed/out-of-range ids (required so bad ids fail before any request).
- `tests/test_open_meteo.py` (232 lines) using httpx.MockTransport and a monkeypatched `time.sleep`; `tests/test_regions.py` gained a `cell_center` rejection test.

Size justification (119 non-blank vs ~60 target): the file contains six tested behaviours that do not fit in 60 lines without either duplicating the error path or hiding rules: three-attempt retry with Retry-After capping, transport-vs-4xx-vs-retryable status handling, eight distinct response checks each mandated to raise, typed result assembly, client ownership, and year validation. The generic-error constant plus five `raise UpstreamError(...)` sites and the two data dicts (request params, result) alone are ~18 lines; the validation function is 28. No dead code and no speculative options remain.

Decisions:
- HTTP 200 with unparseable JSON raises UpstreamError (not retried); 4xx other than 429 raises immediately; 429/5xx and transport errors retry with `min(Retry-After, 5s)` or `1s * 2**attempt`.
- `Retry-After` supports numeric seconds only; an HTTP-date value falls back to exponential backoff.
- `expected_days` computed from real dates (leap-aware), not assumed 365.

Acceptance evidence:
- `ruff check .` and `ruff format --check .` clean; `pytest` 53 passed, no test touches the network (all use MockTransport; `time.sleep` monkeypatched).
- Live one-call check: `fetch_daily_tmax('28.50_77.25', 2024, 2024)` -> 366 values, first three [14.8, 13.3, 14.4], grid_lat 28.5, grid_lon 77.25, utc_offset_seconds 19800 (India) - all as expected.

Self-challenge:
- `models=era5` presence is asserted in `test_request_has_exactly_the_fixed_parameters_and_constant_host` (params["models"] == "era5", len(params) == 8, host == archive-api.open-meteo.com), not assumed.
- Bad ids could not reach the network: `fetch_daily_tmax` on 'abc', '999.00_0.00', '28.50', '28.50_77.25_1' each raised RegionError before any client was created (run directly, no network).
- Every response check was sabotaged and each raised UpstreamError: malformed JSON, non-object body, missing daily, time not a list, non-numeric value, mismatched list lengths, wrong length vs range, wrong unit.
- A 400 whose reason text embedded a marker ("SECRET_REASON_42") and a full URL produced the message "Weather data is temporarily unavailable. Please try again later." with none of the marker/URL/exception-type name present; the reason was logged server-side.
- Line counts: open_meteo.py 136/119, regions.py 58/43, test_open_meteo.py 232/189, test_regions.py 98/78.

### Task 05 - Cleaning and data-quality report
Changed:
- `app/engine/cleaning.py` (111 lines total, 95 non-blank): constants MIN_VALID_FRACTION=0.9, LOWER_BOUND_C=-90.0, UPPER_BOUND_C=60.0, SUSPECT_DEVIATION_C=15.0; public `clean_daily`, `coverage_by_year`, `drop_unusable_years`, `quality_report`; private `_as_float`, `_parse_index`, `_days_in_year`. Imports only datetime/numpy/pandas (repo grep confirms no app.services/app.api/app.db).
- `tests/test_cleaning.py` (262 lines total, 208 non-blank): every required case plus adversarial extras.
- `working.md`: Locked Decisions amendments (physical bounds incl. 60, suspect flag rule, no imputation), Domain Notes (5 bullets), Conventions (engine purity), Assumptions (3), this entry, My Notes.
- Whitespace-only ruff formatting applied to `tests/test_regions.py` (Task 03) and `tests/test_open_meteo.py` (Task 04): both carried pre-existing I001 import-ordering violations that earlier acceptance runs reported clean on only because ruff's incremental cache served stale results; they fail under `ruff check --no-cache`. Repaired and re-verified, noted here so later diffs are understandable.

Size justification (95 non-blank vs ~45 target): the file implements the exact spec surface, which spans both row-level cleaning rules (non-finite, non-numeric, out-of-bounds classification; suspect deviation; None/absent-date handling; duplicate/unparseable/unsorted-date validation) and year-level aggregation (coverage, drop_unusable_years, quality_report) plus the masked missing/invalid bookkeeping the report contract requires. Vectorised numpy/object-array classification is inherently line-hungry but deliberately nest-free; no dead code and no speculative options remain.

Decisions:
- Missing vs invalid partition is recorded as numpy bool masks in `series.attrs` at clean time (`missing` = None + absent dates; `invalid` = non-numeric/non-finite/out-of-bounds among present values); `quality_report` reads the masks when present and falls back to treating all NaN as missing for a series without attrs.
- Raw NaN passed as a value counts invalid (non-finite), not missing (see Assumptions).
- Dates parsed with `format="mixed"` (verified against pandas 3.0.6 for "2024-01-01", "2024/02/05", "2024-03-05"); non-str, NaT and duplicate inputs raise ValueError.
- Suspect computed on cleaned values via a centred 15-day rolling median (min_periods 8); the value is flagged, never removed.
- `coverage_by_year` divides each year's valid count by the calendar-year length (365/366), so partial years score low by construction.
- `drop_unusable_years` masks sub-threshold years to NaN, preserves the index, and clears attrs (stale masks would mis-describe the masked series).

Acceptance evidence:
- `ruff check .` -> "All checks passed!"; `ruff format --check .` -> "20 files already formatted" (re-verified 4 consecutive runs and with `--no-cache`).
- `pytest` -> 82 passed.
- Live: `fetch_daily_tmax('28.50_77.25', 2000, 2009)` -> `clean_daily` -> `quality_report`: total_days 3653, valid_days 3653, valid_fraction 1.0, missing/invalid/suspect 0, excluded_years [] (exact).

Self-challenge:
- Repo search: `cleaning.py` imports only datetime/numpy/pandas; no services/api/db module is touched.
- Corrupt-live-data proof (throwaway script, real 2000-2009 fetch): baseline 0/0/3653; after 40 days -> None, one value -> 999, and one date row removed - missing 0->41, invalid 0->1, valid 3653->3611 (=-42), total unchanged 3653, and the year that absorbed the 40 None days (2001, now 324/365 < 0.9) correctly appears in excluded_years. Re-run with the corrected expectation -> PASS.
- Adversarial inputs (each run and reported): single-day input -> len 1, all valid; a single 2024-02-29 -> len 1, valid, coverage 1/366; mixed int/float -> both valid; mixed date formats -> parsed and expanded to the full span (62 days missing, correct); booleans -> invalid; all-bool input -> 2 invalid (also exercises the all-bool object-dtype `to_numeric` edge via `to_numpy(dtype=float64)`); 10**400 -> invalid via the OverflowError fallback, no crash; empty-string/int/non-str dates and duplicates via differing formats -> ValueError; "104" as a string -> invalid (Fahrenheit covered as numeric 104 and as string "104").
- Line counts: cleaning.py 111/95, test_cleaning.py 262/208.

## 9. Open Issues
- The import test proves the five modules are importable but cannot assert the presence of the empty `__init__.py` files, because Python namespace packages make a directory without `__init__.py` still importable. The `__init__.py` files are present as required; this is only a verification gap.
- Live /health check against MongoDB Atlas pending: expected {"status":"ok","database":"up"}. Must be verified before Task 06.
- pytest emits a StarletteDeprecationWarning about httpx/starlette.testclient suggesting `httpx2`; not actionable under the no-new-dependency constraint, and harmless while tests pass.
- Attribution of Open-Meteo and Copernicus/ERA5 must appear in the UI and README (Tasks 19 and 24).
- `ruff check`'s incremental cache can serve a stale "clean" verdict for files whose formatting later regressed; the Task 03/04 test files only failed once `--no-cache` was used. No format/lint gate should be trusted solely from a hot cache.

## 10. My Notes
- Task 01: scaffolded the backend base exactly from the Section 3 tree, pinned every version from a real venv freeze, and left all application logic for later tasks. The only friction was ruff's F401 on the deliberate import test, solved with `importlib`.
- Task 02: pydantic-settings turned out to be the crux - a list field does not parse comma-separated strings in 2.15.0, so a str field plus a property is the honest answer. mongomock happily answers ping, and B008 forced the Annotated form for the dependency. Live "down" behaved exactly as specified (~5.6 s, server survives).
- Task 03: index-based half-up snapping is close to a free win - deterministic, no float creep, and the -0.00 trap is handled by normalising inside ONE helper used everywhere. The cap-before-list check makes world boxes a microsecond error. The 9-cell cap is a real product constraint: whole-subcontinent analysis is impossible by design.
- Task 04: the client stayed honest by pinning models=era5, which the two real curls proved changes the returned point from an ~4.8 km-off IFS cell back to exactly our snapped coordinate. Building the request through httpx params (never strings) and one generic error message kept URLs, coords and upstream reasons out of anything a caller sees. The only place I diverged from the task text was the "5 days" success test, which is impossible against whole-year requests - documented rather than faked.
- Task 05: the crux was the missing-vs-invalid split, on which the task text contradicted its own test (missing_days "counts None, NaN and absent dates" vs raw nan in invalid_days) - the tests decided. The long-tail risk was the OverflowError path: pandas to_numeric raises on Python ints too big for float64, and a guarded frompyfunc keeps clean_daily crash-proof. The vectorised classification leans on three numpy object-array tricks (np.equal(obj, None), astype(str)==obj for strings, and the "True"/"False" string forms for bools) that I verified interactively against pandas 3.0.6 before relying on them. Corrupting the live 2000-2009 series and watching exactly +41 missing, +1 invalid, -42 valid and a year fall below 90% come out of the report is the most convincing acceptance evidence I produced in this project.
