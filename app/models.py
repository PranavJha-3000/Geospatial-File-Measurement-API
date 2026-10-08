"""SQLAlchemy ORM models.

Design notes:
- `storage_key` is a portable path relative to UPLOAD_DIR; absolute paths are never stored.
- Geometry is persisted as GeoJSON (JSON column) in the SOURCE CRS.
- `measurement_crs` is stored per feature because CRS selection is per feature.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FileStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ErrorCode(StrEnum):
    """Controlled error codes surfaced by the API (HTTP failures and per-feature records)."""

    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    CORRUPT_FILE = "CORRUPT_FILE"
    SHAPEFILE_INCOMPLETE = "SHAPEFILE_INCOMPLETE"
    NO_FEATURES = "NO_FEATURES"
    CRS_MISSING = "CRS_MISSING"
    FILE_NOT_READY = "FILE_NOT_READY"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    # Per-feature codes (never fail the whole file).
    FEATURE_INVALID = "FEATURE_INVALID"
    UNSUPPORTED_GEOMETRY = "UNSUPPORTED_GEOMETRY"
    EMPTY_GEOMETRY = "EMPTY_GEOMETRY"
    MEASUREMENT_FAILED = "MEASUREMENT_FAILED"


class FileRecord(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512))
    file_type: Mapped[str] = mapped_column(String(10))  # "kml" | "shapefile"
    status: Mapped[str] = mapped_column(String(16), index=True, default=FileStatus.PENDING)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    source_crs: Mapped[str | None] = mapped_column(String(32), nullable=True)
    measurement_crs_summary: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeatureRecord(Base):
    __tablename__ = "features"
    __table_args__ = (UniqueConstraint("file_id", "feature_index", name="uq_features_file_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("files.id", ondelete="CASCADE"), index=True
    )
    feature_index: Mapped[int] = mapped_column(Integer)
    original_geometry_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    geometry_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # GeoJSON geometry
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    source_crs: Mapped[str | None] = mapped_column(String(32), nullable=True)
    measurement_crs: Mapped[str | None] = mapped_column(String(32), nullable=True)
    crs_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
