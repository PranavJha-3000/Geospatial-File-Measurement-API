"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import features, files, measurements
from app.db import init_db
from app.errors import register_error_handlers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Geospatial File Measurement API",
        description=(
            "Upload KML or Shapefile ZIP files and retrieve per-feature geometry and "
            "measurements (polygon area in m², line length in m) computed in a "
            "feature-level projected CRS."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    app.include_router(files.router)
    app.include_router(features.router)
    app.include_router(measurements.router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
