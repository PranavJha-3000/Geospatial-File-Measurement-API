"""Paginated feature listing (includes persisted GeoJSON geometry)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.common import get_ready_file
from app.api.deps import PaginationParams, pagination_params
from app.db import get_db
from app.repositories import feature_repo
from app.schemas import FeatureItem, FeaturePage

router = APIRouter(prefix="/api/files", tags=["features"])


@router.get("/{file_id}/features/", response_model=FeaturePage)
def list_features(
    file_id: str,
    page: PaginationParams = Depends(pagination_params),
    db: Session = Depends(get_db),
) -> FeaturePage:
    record = get_ready_file(db, file_id)
    rows, total = feature_repo.list_features(db, record.id, page.page, page.page_size)
    items = [
        FeatureItem(
            feature_index=row.feature_index,
            original_geometry_type=row.original_geometry_type,
            geometry_type=row.geometry_type,
            geometry=row.geometry,
            properties=row.properties or {},
            source_crs=row.source_crs,
            measurement_crs=row.measurement_crs,
            crs_fallback=row.crs_fallback,
            area_m2=row.area_m2,
            length_m=row.length_m,
            is_valid=row.is_valid,
            error_code=row.error_code,
            error=row.error,
        )
        for row in rows
    ]
    return FeaturePage(
        file_id=record.id,
        page=page.page,
        page_size=page.page_size,
        total=total,
        pages=feature_repo.pages(total, page.page_size),
        items=items,
    )
