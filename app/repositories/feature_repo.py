"""Persistence and paged reads for FeatureRecord."""

from __future__ import annotations

import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.geo.measurement import FeatureResult
from app.models import FeatureRecord


def bulk_insert(
    db: Session,
    file_id: str,
    source_crs: str,
    results: list[FeatureResult],
    properties: list[dict],
) -> None:
    """Stage features in source order (feature_index = enumeration order).

    Flushes but does NOT commit: the caller's mark_ready() commits features and
    the READY status in one transaction, so a failure can never leave committed
    features attached to a non-READY (or stuck PROCESSING) file.
    """
    for index, (result, props) in enumerate(zip(results, properties, strict=True)):
        db.add(
            FeatureRecord(
                file_id=file_id,
                feature_index=index,
                original_geometry_type=result.original_geometry_type,
                geometry_type=result.geometry_type,
                geometry=result.geometry,
                properties=props,
                source_crs=source_crs,
                measurement_crs=result.measurement_crs,
                crs_fallback=result.crs_fallback,
                area_m2=result.area_m2,
                length_m=result.length_m,
                is_valid=result.is_valid,
                error_code=result.error_code,
                error=result.error,
            )
        )
    db.flush()


def count_features(db: Session, file_id: str) -> int:
    return int(
        db.execute(
            select(func.count()).select_from(FeatureRecord).where(FeatureRecord.file_id == file_id)
        ).scalar_one()
    )


def list_features(
    db: Session, file_id: str, page: int, page_size: int
) -> tuple[list[FeatureRecord], int]:
    total = count_features(db, file_id)
    rows = list(
        db.execute(
            select(FeatureRecord)
            .where(FeatureRecord.file_id == file_id)
            .order_by(FeatureRecord.feature_index)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars()
    )
    return rows, total


def pages(total: int, page_size: int) -> int:
    return max(1, math.ceil(total / page_size))
