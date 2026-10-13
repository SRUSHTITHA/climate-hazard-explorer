import hashlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import _should_exempt, sync_check_limits
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.routing import Match
from app.api.analysis import router as analysis_router
from app.api.errors import (
    app_error_handler,
    http_exception_handler,
    limiter,
    rate_limit_handler,
    request_validation_handler,
    unhandled_exception_handler,
)
from app.errors import AppError
from app.api.health import router as health_router
from app.api.regions import router as regions_router
from app.config import Settings, get_settings
from app.db import get_db
from app.services.storage import ensure_indexes

_LOGGER = logging.getLogger(__name__)
_CACHE_MAX_AGE = 3600
_HARDENING_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        ensure_indexes(get_db())
    except Exception:
        _LOGGER.warning("Could not create indexes on startup.", exc_info=True)
    yield

class HardeningMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, max_age: int = _CACHE_MAX_AGE) -> None:
        super().__init__(app)
        self._max_age = max_age

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for name, value in _HARDENING_HEADERS.items():
            response.headers.setdefault(name, value)
        if response.status_code >= 400 or request.url.path == "/health":
            response.headers["Cache-Control"] = "no-store"
            return response
        if (
            request.method == "GET"
            and request.url.path == "/api/analysis"
            and response.status_code == 200
        ):
            return await self._with_validator(request, response)
        return response

    async def _with_validator(self, request: Request, response: Response) -> Response:
        body = b"".join([chunk async for chunk in response.body_iterator])
        etag = '"' + hashlib.sha256(body).hexdigest() + '"'
        cache_control = f"public, max-age={self._max_age}"
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": cache_control})
        headers = dict(response.headers)
        headers["ETag"] = etag
        headers["Cache-Control"] = cache_control
        return Response(content=body, status_code=200, headers=headers)

def _find_endpoint(routes: list, scope: dict) -> object | None:
    handler = None
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            handler = _find_endpoint(included.routes, scope) or handler
            continue
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None and route.matches(scope)[0] == Match.FULL:
            handler = endpoint
    return handler

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rate_limiter = request.app.state.limiter
        handler = _find_endpoint(request.app.routes, request.scope)
        if not rate_limiter.enabled or _should_exempt(rate_limiter, handler):
            return await call_next(request)
        error_response, inject = sync_check_limits(rate_limiter, request, handler, request.app)
        if error_response is not None:
            return error_response
        response = await call_next(request)
        if inject:
            response = rate_limiter._inject_headers(response, request.state.view_rate_limit)
        return response

def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Climate Hazard Explorer", lifespan=lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["If-None-Match"],
        expose_headers=["ETag", "Retry-After"],
        allow_credentials=False,
    )
    app.add_middleware(HardeningMiddleware)
    app.include_router(health_router)
    app.include_router(analysis_router)
    app.include_router(regions_router)
    return app
app = create_app()
