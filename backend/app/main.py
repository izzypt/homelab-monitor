"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api import auth, errors, health, incidents, monitors
from app.config import get_settings
from app.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="homelab-monitor",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

# Ops probes live at /api/healthz and /api/readyz; versioned resources go under /api/v1.
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(monitors.router, prefix="/api/v1")
app.include_router(incidents.router, prefix="/api/v1")
errors.install(app)
