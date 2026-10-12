from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.api.errors import limiter
from app.config import get_settings
from app.db import get_db
from app.engine.events import EventError
from app.engine.insights import InsightError
from app.engine.metrics import MetricsError
from app.engine.thresholds import ThresholdError
from app.engine.trends import TrendError
from app.models.schemas import AnalysisRequest, AnalysisResponse, ErrorResponse
from app.services.analysis import AnalysisError, run_analysis
from app.services.ingestion import IngestError
from app.services.open_meteo import UpstreamError
from app.services.regions import RegionError

router = APIRouter(prefix="/api")

_UPSTREAM_MESSAGE = "Weather data is temporarily unavailable. Please try again later."
_DATA_MESSAGE = "Not enough data is available to compute the analysis."
_INVALID_MESSAGE = "The request parameters are invalid."
_DATABASE_MESSAGE = "The service database is temporarily unavailable."
_INTERNAL_MESSAGE = "An internal error occurred while computing the analysis."
_ANALYSIS_STATUS = {"year_out_of_range": 400, "data_unavailable": 502}
_COMPUTE_LIMIT = get_settings().rate_limit_compute


@router.get("/analysis", response_model=AnalysisResponse)
@limiter.limit(_COMPUTE_LIMIT)
def analysis(
    request: Request,
    response: Response,
    query: Annotated[AnalysisRequest, Query()],
    db: Annotated[Database, Depends(get_db)],
) -> AnalysisResponse | JSONResponse:
    try:
        return run_analysis(db, query)
    except Exception as exc:
        return _error_response(exc)


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, AnalysisError):
        return _json(_ANALYSIS_STATUS.get(exc.code, 500), exc.code, exc.message)
    if isinstance(exc, (UpstreamError, IngestError)):
        return _json(502, "upstream_error", _UPSTREAM_MESSAGE)
    if isinstance(exc, (ThresholdError, MetricsError, LookupError)):
        return _json(502, "data_unavailable", _DATA_MESSAGE)
    if isinstance(exc, PyMongoError):
        return _json(503, "database_unavailable", _DATABASE_MESSAGE)
    if isinstance(exc, RegionError):
        return _json(400, "invalid_region", _INVALID_MESSAGE)
    if isinstance(exc, (EventError, TrendError, InsightError)):
        return _json(500, "internal_error", _INTERNAL_MESSAGE)
    if isinstance(exc, ValueError):
        return _json(400, "invalid_request", _INVALID_MESSAGE)
    return _json(500, "internal_error", _INTERNAL_MESSAGE)


def _json(status: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(code=code, message=message)
    return JSONResponse(status_code=status, content=body.model_dump())
