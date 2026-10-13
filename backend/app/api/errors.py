import logging
import re
import traceback

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.errors import FORBIDDEN_MESSAGE_PARTS, AppError
from app.models.schemas import ErrorResponse

_LOGGER = logging.getLogger(__name__)
_INVALID_MESSAGE = "The request parameters are invalid."
_NOT_FOUND_MESSAGE = "The requested resource was not found."
_METHOD_MESSAGE = "The request method is not allowed for this resource."
_RATE_MESSAGE = "Too many requests. Please retry later."
_HTTP_MESSAGE = "The request could not be completed."
_INTERNAL_MESSAGE = "An internal error occurred."

_SAFE_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,30}$")
_SETTINGS = get_settings()


def client_identifier(request: Request) -> str:
    hops = _SETTINGS.trusted_proxy_hops
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return get_remote_address(request)


limiter = Limiter(
    key_func=client_identifier,
    default_limits=[_SETTINGS.rate_limit_default],
    headers_enabled=True,
)


def _response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(code=code, message=message)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(),
        headers={"Cache-Control": "no-store"},
    )


def _field_names(exc: RequestValidationError) -> list[str]:
    names: list[str] = []
    for error in exc.errors():
        loc = error.get("loc", ())
        candidate = str(loc[-1]) if loc else ""
        lowered = candidate.lower()
        if candidate in names or not _SAFE_FIELD.match(candidate):
            continue
        if any(part in lowered for part in FORBIDDEN_MESSAGE_PARTS):
            continue
        names.append(candidate)
    return names


def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    names = _field_names(exc)
    message = f"Invalid or missing field(s): {', '.join(names)}." if names else _INVALID_MESSAGE
    return _response(400, "invalid_request", message[:300])


def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return _response(404, "not_found", _NOT_FOUND_MESSAGE)
    if exc.status_code == 405:
        return _response(405, "method_not_allowed", _METHOD_MESSAGE)
    return _response(exc.status_code, "http_error", _HTTP_MESSAGE)


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    response = _response(429, "rate_limited", _RATE_MESSAGE)
    limiter_ = getattr(request.app.state, "limiter", None)
    rate_limit = getattr(request.state, "view_rate_limit", None)
    if limiter_ is not None and rate_limit is not None:
        limiter_._inject_headers(response, rate_limit)
    return response


def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return _response(exc.status, exc.code, exc.message)


def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    frames = traceback.extract_tb(exc.__traceback__)
    location = " <- ".join(f"{frame.filename}:{frame.lineno}:{frame.name}" for frame in frames)
    _LOGGER.error("Unhandled %s at %s", type(exc).__name__, location)
    return _response(500, "internal_error", _INTERNAL_MESSAGE)
