"""Persistence for FileRecord (no geospatial logic here)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import FileRecord, FileStatus


def create_file(
    db: Session,
    *,
    file_id: str,
    original_filename: str,
    storage_key: str,
    file_type: str,
) -> FileRecord:
    record = FileRecord(
        id=file_id,
        original_filename=original_filename,
        storage_key=storage_key,
        file_type=file_type,
        status=FileStatus.PENDING,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_file(db: Session, file_id: str) -> FileRecord | None:
    return db.get(FileRecord, file_id)


def set_status(db: Session, record: FileRecord, status: FileStatus) -> None:
    record.status = status
    db.commit()


def mark_ready(
    db: Session,
    record: FileRecord,
    *,
    feature_count: int,
    source_crs: str,
    measurement_crs_summary: str,
) -> None:
    record.status = FileStatus.READY
    record.feature_count = feature_count
    record.source_crs = source_crs
    record.measurement_crs_summary = measurement_crs_summary
    db.commit()


def mark_failed(
    db: Session,
    record: FileRecord,
    *,
    error_code: str,
    error_message: str,
) -> None:
    record.status = FileStatus.FAILED
    record.error_code = error_code
    record.error_message = error_message
    db.commit()
