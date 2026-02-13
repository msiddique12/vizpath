"""Security middleware and shared error response helpers."""

from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import settings

REQUEST_ID_HEADER = "X-Request-ID"
MINIMAL_CSP = "default-src 'self'; frame-ancestors 'none'; object-src 'none'"


def build_error_response(
    *,
    status_code: int,
    detail: str,
    request_id: str | None,
    code: str,
) -> JSONResponse:
    """Create a consistent JSON error shape while keeping `detail` for compatibility."""
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": detail,
            "error": {
                "code": code,
                "message": detail,
                "request_id": request_id,
            },
        },
    )


async def request_id_middleware(request: Request, call_next):
    """Ensure every request/response carries a stable request ID."""
    request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


async def security_headers_middleware(request: Request, call_next):
    """Apply baseline security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"

    if settings.security_strict_mode:
        response.headers["Content-Security-Policy"] = MINIMAL_CSP

    return response
