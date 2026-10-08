"""Shared helpers for file-scoped endpoints."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ErrorCode, FileRecord, FileStatus
from app.repositories import file_repo


def get_ready_file(db: Session, file_id: str) -> FileRecord:
    """Load a file or raise the controlled error matching its current state."""
    record = file_repo.get_file(db, file_id)
    if record is None:
        raise AppError(404, ErrorCode.NOT_FOUND, f"file {file_id} not found")
    if record.status in (FileStatus.PENDING, FileStatus.PROCESSING):
        raise AppError(
            409,
            ErrorCode.FILE_NOT_READY,
            "file is still being processed",
            file_id=file_id,
        )
    if record.status == FileStatus.FAILED:
        raise AppError(
            422,
            record.error_code or ErrorCode.CORRUPT_FILE,
            record.error_message or "file processing failed",
            file_id=file_id,
        )
    return record
