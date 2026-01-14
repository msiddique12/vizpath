"""vizpath server - FastAPI application."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.config import settings
from app.database import check_db_connection, engine, init_db
from app.routes import projects, traces, ws

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    logger.info("vizpath server starting...")
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}", exc_info=True)
        raise RuntimeError(f"Could not connect to database: {e}") from e

    yield

    logger.info("vizpath server shutting down...")
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
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(traces.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(ws.router)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    logger.warning(f"Validation error: {exc}")
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
    logger.error(f"Runtime error: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/", tags=["Health"])
async def root() -> Dict[str, str]:
    """Root endpoint with API info."""
    return {"name": "vizpath", "version": __version__, "status": "ok"}


@app.get("/health", tags=["Health"])
async def health() -> Dict[str, Any]:
    """Basic health check."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/health/detailed", tags=["Health"])
async def health_detailed() -> Dict[str, Any]:
    """Detailed health check including dependencies."""
    db_healthy = check_db_connection()

    return {
        "status": "healthy" if db_healthy else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
        "checks": {
            "database": {"status": "healthy" if db_healthy else "unhealthy"},
        },
    }
