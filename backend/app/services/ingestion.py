import datetime as dt
import logging
from typing import Any

import pandas as pd

from app.engine.cleaning import clean_daily, days_in_year
from app.services import open_meteo, regions, storage

HISTORY_START = 1990  # working.md locked ingest window (single code copy)
SOURCE = "open-meteo-era5"
UNIT = "C"

_LOGGER = logging.getLogger(__name__)


class IngestError(Exception):
    pass


def last_full_year() -> int:
    return dt.datetime.now(dt.UTC).year - 1


def missing_years(db: Any, cell_id: str) -> list[int]:
    window = range(HISTORY_START, last_full_year() + 1)
    present = storage.existing_years(db, cell_id, HISTORY_START, last_full_year())
    return sorted(set(window) - present)


def ingest_cell(db: Any, cell_id: str) -> dict:
    regions.cell_center(cell_id)
    missing = missing_years(db, cell_id)
    skipped = sorted(storage.existing_years(db, cell_id, HISTORY_START, last_full_year()))
    if not missing:
        return {
            "cell_id": cell_id,
            "fetched_years": [],
            "skipped_years": skipped,
            "status": "cached",
        }
    first, last = missing[0], missing[-1]
    payload = open_meteo.fetch_daily_tmax(cell_id, first, last)
    dates, values = payload["dates"], payload["tmax"]
    if len(dates) != len(values):
        raise IngestError("Fetched daily series is malformed.")
    if dates[0] != f"{first}-01-01" or dates[-1] != f"{last}-12-31":
        raise IngestError("Fetched response does not bound the full requested span.")
    try:
        clean = clean_daily(dates, values)
    except ValueError as exc:
        raise IngestError(str(exc)) from None
    missing_mask = clean.attrs["missing_mask"]
    invalid_mask = clean.attrs["invalid_mask"]
    suspect_mask = clean.attrs["suspect_mask"]
    years: list[dict] = []
    for year in missing:
        mask = clean.index.year == year
        length = int(mask.sum())
        if length != days_in_year(year):
            raise IngestError(
                f"Fetched data does not cover all {length} of {days_in_year(year)} days in {year}."
            )
        years.append(
            {
                "year": year,
                "tmax": [None if pd.isna(value) else float(value) for value in clean[mask]],
                "quality": {
                    "missing_days": int(missing_mask[mask].sum()),
                    "invalid_days": int(invalid_mask[mask].sum()),
                    "suspect_days": int(suspect_mask[mask].sum()),
                },
            }
        )
    for entry in years:
        storage.save_raw_year(
            db,
            cell_id=cell_id,
            year=entry["year"],
            tmax=entry["tmax"],
            source=SOURCE,
            unit=UNIT,
            grid_lat=payload["grid_lat"],
            grid_lon=payload["grid_lon"],
            elevation=payload["elevation"],
            utc_offset_seconds=payload["utc_offset_seconds"],
            quality=entry["quality"],
        )
    return {
        "cell_id": cell_id,
        "fetched_years": [year for year in missing],
        "skipped_years": skipped,
        "status": "ingested",
    }


def ingest_region(db: Any, cell_ids: list[str]) -> list[dict]:
    if len(cell_ids) > regions.MAX_CELLS:
        raise ValueError(f"A region is limited to {regions.MAX_CELLS} grid cells.")
    results: list[dict] = []
    for cell_id in cell_ids:
        try:
            results.append(ingest_cell(db, cell_id))
        except Exception as exc:
            error = str(exc) if str(exc) else type(exc).__name__
            results.append({"cell_id": cell_id, "status": "failed", "error": error[:120]})
    return results
