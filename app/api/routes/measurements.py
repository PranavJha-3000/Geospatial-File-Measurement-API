"""Paginated measurement listing (explicit units: metres / square metres)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.common import get_ready_file
from app.api.deps import PaginationParams, pagination_params
from app.db import get_db
from app.repositories import feature_repo
from app.schemas import MeasurementItem, MeasurementPage

router = APIRouter(prefix="/api/files", tags=["measurements"])


@router.get("/{file_id}/measurements/", response_model=MeasurementPage)
def list_measurements(
    file_id: str,
    page: PaginationParams = Depends(pagination_params),
    db: Session = Depends(get_db),
) -> MeasurementPage:
    record = get_ready_file(db, file_id)
    rows, total = feature_repo.list_features(db, record.id, page.page, page.page_size)
    items = [
        MeasurementItem(
            feature_index=row.feature_index,
            geometry_type=row.geometry_type,
            measurement_crs=row.measurement_crs,
            crs_fallback=row.crs_fallback,
            area_m2=row.area_m2,
            length_m=row.length_m,
        )
        for row in rows
    ]
    return MeasurementPage(
        file_id=record.id,
        page=page.page,
        page_size=page.page_size,
        total=total,
        pages=feature_repo.pages(total, page.page_size),
        items=items,
    )
