from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from pymongo.database import Database

from app.api.errors import limiter
from app.config import get_settings
from app.db import get_db
from app.models.schemas import AnalysisRequest, AnalysisResponse
from app.services.analysis import run_analysis

router = APIRouter(prefix="/api")
_COMPUTE_LIMIT = get_settings().rate_limit_compute


@router.get("/analysis", response_model=AnalysisResponse)
@limiter.limit(_COMPUTE_LIMIT)
def analysis(
    request: Request,
    response: Response,
    query: Annotated[AnalysisRequest, Query()],
    db: Annotated[Database, Depends(get_db)],
) -> AnalysisResponse:
    return run_analysis(db, query)
