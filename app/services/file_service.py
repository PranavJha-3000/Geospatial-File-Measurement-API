"""Upload ingestion orchestration.

Status transitions: PENDING -> PROCESSING -> READY | FAILED.
Business failures (CRS_MISSING, corrupt files, ...) are persisted on the file row
and re-raised as AppError so the API returns a controlled status, not a 500.
"""

from __future__ import annotations

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.errors import AppError
from app.geo import validation
from app.geo.geometry import sanitize_properties
from app.geo.loaders import load_kml, load_shapefile
from app.geo.measurement import FeatureResult, process_feature
from app.models import ErrorCode, FileRecord, FileStatus
from app.repositories import feature_repo, file_repo, storage


def _summarize_crs(results: list[FeatureResult], total_features: int) -> str:
    """File-level display summary of per-feature measurement CRSs (computed in memory
    so it participates in the same transaction as the feature rows)."""
    counts: dict[tuple[str, bool], int] = {}
    for result in results:
        if result.measurement_crs is None:
            continue
        key = (result.measurement_crs, result.crs_fallback)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "n/a"
    parts = [
        f"{crs}{' (fallback)' if fallback else ''} ({n}/{total_features} measured)"
        for (crs, fallback), n in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
    return ", ".join(parts)[:128]


def ingest_file(
    db: Session,
    upload: UploadFile,
    filename: str,
    content_type: str | None,
) -> FileRecord:
    """Validate -> store -> load -> measure -> persist. Returns the final FileRecord.

    Raises AppError for controlled failures; the file row always reflects the outcome.
    """
    file_type = validation.classify_upload(filename, content_type)

    # ZIPs are stored under a fixed name so extraction has a stable location;
    # the original filename lives on FileRecord.original_filename (capped at the
    # 255-char column width so PostgreSQL would not reject long browser paths).
    stored_name = "archive.zip" if file_type == "shapefile" else filename
    file_id = storage.new_file_id()
    storage_key, data = storage.save_upload(upload, file_id, stored_name)
    record = file_repo.create_file(
        db,
        file_id=file_id,
        original_filename=filename[:255],
        storage_key=storage_key,
        file_type=file_type,
    )

    try:
        validation.check_magic_bytes(file_type, data)
        file_repo.set_status(db, record, FileStatus.PROCESSING)

        if file_type == "shapefile":
            extract_dir = storage.safe_extract_zip(file_id)
            gdf, source_crs = load_shapefile(extract_dir)
        else:
            gdf, source_crs = load_kml(storage.resolve(storage_key))

        if len(gdf) == 0:
            raise AppError(422, ErrorCode.NO_FEATURES, "file contains no features")
        validation.check_max_features(len(gdf))

        results = []
        properties = []
        for _, row in gdf.iterrows():
            geom = row.geometry
            results.append(process_feature(geom, source_crs))
            attrs = {k: v for k, v in row.items() if k != gdf.geometry.name}
            properties.append(sanitize_properties(attrs))

        # One transaction for features + READY status: a failure between the two
        # can never leave committed features under a non-READY file.
        feature_repo.bulk_insert(db, record.id, source_crs, results, properties)
        summary = _summarize_crs(results, total_features=len(results))
        file_repo.mark_ready(
            db,
            record,
            feature_count=len(results),
            source_crs=source_crs,
            measurement_crs_summary=summary,
        )
        return record

    except AppError as exc:
        db.rollback()
        file_repo.mark_failed(db, record, error_code=exc.code, error_message=exc.detail)
        raise AppError(exc.status_code, exc.code, exc.detail, file_id=record.id) from exc
    except Exception as exc:
        # Unexpected processing error -> explicit FAILED state + controlled message.
        db.rollback()
        message = f"processing failed: {exc}"
        file_repo.mark_failed(db, record, error_code=ErrorCode.CORRUPT_FILE, error_message=message)
        raise AppError(
            400,
            ErrorCode.CORRUPT_FILE,
            f"could not process file: {exc}",
            file_id=record.id,
        ) from exc
