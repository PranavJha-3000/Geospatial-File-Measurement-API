"""File upload and file metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import ErrorCode, FileRecord
from app.repositories import file_repo
from app.schemas import FileDetail
from app.services.file_service import ingest_file

router = APIRouter(prefix="/api/files", tags=["files"])


def _to_detail(record: FileRecord) -> FileDetail:
    return FileDetail(
        id=record.id,
        original_filename=record.original_filename,
        file_type=record.file_type,
        status=record.status,
        feature_count=record.feature_count,
        source_crs=record.source_crs,
        measurement_crs_summary=record.measurement_crs_summary,
        storage_key=record.storage_key,
        created_at=record.created_at,
        error_code=record.error_code,
        error_message=record.error_message,
    )


@router.post("/", status_code=201, response_model=FileDetail)
def create_file(
    file: UploadFile = File(..., description=".kml file or .zip archive with a Shapefile"),
    db: Session = Depends(get_db),
) -> FileDetail:
    filename = file.filename or ""
    record = ingest_file(db, file, filename, file.content_type)
    return _to_detail(record)


@router.get("/{file_id}/", response_model=FileDetail)
def get_file(file_id: str, db: Session = Depends(get_db)) -> FileDetail:
    record = file_repo.get_file(db, file_id)
    if record is None:
        raise AppError(404, ErrorCode.NOT_FOUND, f"file {file_id} not found")
    return _to_detail(record)
