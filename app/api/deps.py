"""Shared route dependencies: DB session and pagination params."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query

from app.config import settings


@dataclass(frozen=True)
class PaginationParams:
    page: int
    page_size: int


def pagination_params(
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int | None = Query(
        None, ge=1, le=settings.max_page_size, description="items per page"
    ),
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size or settings.default_page_size)
