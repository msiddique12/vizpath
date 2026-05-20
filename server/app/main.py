"""vizpath server - FastAPI application."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.alert_dispatcher import (
    start_alert_notification_dispatcher,
    stop_alert_notification_dispatcher,
)
from app.alert_scheduler import run_alert_scheduler
from app.config import settings
from app.database import check_db_connection, engine, init_db
from app.rate_limit import rate_limit_middleware
from app.routes import alerts, curation, demo, intelligence, product, projects, traces, ws
from app.security import (
    build_error_response,
    redact_headers,
    request_id_middleware,
    request_size_limit_middleware,
    security_headers_middleware,
)

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    logger.info("vizpath server starting...")
    alert_scheduler_task: asyncio.Task[None] | None = None
    alert_scheduler_stop_event = asyncio.Event()

    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}", exc_info=True)
        raise RuntimeError(f"Could not connect to database: {e}") from e

    if settings.alert_scheduler_enabled:
        alert_scheduler_task = asyncio.create_task(
            run_alert_scheduler(alert_scheduler_stop_event)
        )
        logger.info(
            "Alert scheduler started: interval_seconds=%d notify=%s",
            settings.alert_scheduler_interval_seconds,
            settings.alert_scheduler_notify,
        )

    start_alert_notification_dispatcher()

    yield

    logger.info("vizpath server shutting down...")
    if alert_scheduler_task is not None:
        alert_scheduler_stop_event.set()
        try:
            await asyncio.wait_for(alert_scheduler_task, timeout=5.0)
        except asyncio.TimeoutError:
            alert_scheduler_task.cancel()
            logger.warning("Alert scheduler shutdown timed out; task cancelled")
        else:
            logger.info("Alert scheduler stopped")
    stop_alert_notification_dispatcher()
    engine.dispose()
    logger.info("Database connections closed")


app = FastAPI(
    title="vizpath",
    version=__version__,
    description="Agent observability and trace visualization API",
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(request_id_middleware)
app.middleware("http")(rate_limit_middleware)
app.middleware("http")(request_size_limit_middleware)
app.middleware("http")(security_headers_middleware)

app.include_router(traces.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(alerts.router, prefix="/api/v1")
app.include_router(curation.router, prefix="/api/v1")
app.include_router(intelligence.router, prefix="/api/v1")
app.include_router(product.router, prefix="/api/v1")
app.include_router(demo.router, prefix="/api/v1")
app.include_router(ws.router)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    logger.warning(
        "Validation error: %s; headers=%s",
        exc,
        redact_headers(dict(request.headers)),
    )
    return build_error_response(
        status_code=400,
        detail=str(exc),
        request_id=getattr(request.state, "request_id", None),
        code="bad_request",
    )


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
    logger.error(
        "Runtime error: %s; headers=%s",
        exc,
        redact_headers(dict(request.headers)),
        exc_info=True,
    )
    return build_error_response(
        status_code=500,
        detail="Internal server error",
        request_id=getattr(request.state, "request_id", None),
        code="runtime_error",
    )


@app.get("/", tags=["Health"])
async def root() -> dict[str, str]:
    """Root endpoint with API info."""
    return {"name": "vizpath", "version": __version__, "status": "ok"}


@app.get("/health", tags=["Health"])
async def health() -> dict[str, Any]:
    """Basic health check."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/health/detailed", tags=["Health"])
async def health_detailed() -> dict[str, Any]:
    """Detailed health check including dependencies."""
    db_healthy = check_db_connection()
    redis_healthy = False

    try:
        redis_client = redis.from_url(settings.redis_url)
        redis_healthy = bool(redis_client.ping())
    except Exception:
        redis_healthy = False

    return {
        "status": "healthy" if db_healthy and redis_healthy else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
        "checks": {
            "database": {"status": "healthy" if db_healthy else "unhealthy"},
            "redis": {"status": "healthy" if redis_healthy else "unhealthy"},
            "intelligence": {
                "status": "configured" if settings.nvidia_api_key else "not_configured",
            },
        },
    }
