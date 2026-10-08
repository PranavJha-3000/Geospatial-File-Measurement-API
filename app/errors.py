"""Controlled application errors and FastAPI exception handlers.

Every anticipated failure maps to an explicit HTTP status and a stable error code
instead of leaking stack traces as generic 500 responses. All error responses —
business errors, request-validation errors, framework 404/405 — share one envelope:
{"detail": str, "code": str, "file_id": str | None}.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("gfma.errors")


class AppError(Exception):
    """Business error with a stable code and HTTP status."""

    def __init__(
        self,
        status_code: int,
        code: str,
        detail: str,
        file_id: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.file_id = file_id


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code, "file_id": exc.file_id},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Keep the shared envelope instead of FastAPI's default list-shaped detail.
        errors = exc.errors()
        first = errors[0] if errors else {}
        location = ".".join(str(part) for part in first.get("loc", ()))
        message = str(first.get("msg", "invalid request"))
        detail = f"{location}: {message}" if location else message
        return JSONResponse(
            status_code=422,
            content={"detail": detail, "code": "VALIDATION_ERROR", "file_id": None},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else f"HTTP_{exc.status_code}"
        detail = exc.detail if isinstance(exc.detail, str) else "request error"
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": detail, "code": code, "file_id": None},
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # Log the traceback server-side; the client only ever gets the stable envelope.
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "internal server error", "code": "INTERNAL_ERROR", "file_id": None},
        )


__all__ = ["AppError", "register_error_handlers"]
