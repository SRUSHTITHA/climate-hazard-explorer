import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.health import router as health_router
from app.config import get_settings
from app.db import get_db
from app.services.storage import ensure_indexes

_LOGGER = logging.getLogger(__name__)
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        ensure_indexes(get_db())
    except Exception:
        _LOGGER.warning("Could not create indexes on startup.", exc_info=True)
    yield

app = FastAPI(title="Climate Hazard Explorer", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST"],
    allow_credentials=False,
)
app.include_router(health_router)