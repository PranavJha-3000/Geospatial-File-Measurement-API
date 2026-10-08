"""Pydantic response models.

Every measurement-bearing response includes an explicit `units` block
(measurements are always metres and square metres).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ErrorModel(BaseModel):
    detail: str
    code: str
    file_id: str | None = None


class Units(BaseModel):
    area: str = "m2"
    length: str = "m"


UNITS = Units()


class FileDetail(BaseModel):
    id: str
    original_filename: str
    file_type: str
    status: str
    feature_count: int
    source_crs: str | None = None
    measurement_crs_summary: str | None = None
    storage_key: str
    created_at: datetime
    error_code: str | None = None
    error_message: str | None = None


class FeatureItem(BaseModel):
    feature_index: int
    original_geometry_type: str | None = None
    geometry_type: str | None = None
    geometry: dict[str, Any] | None = None  # GeoJSON geometry in source CRS
    properties: dict[str, Any] = Field(default_factory=dict)
    source_crs: str | None = None
    measurement_crs: str | None = None
    crs_fallback: bool = False
    area_m2: float | None = None
    length_m: float | None = None
    units: Units = UNITS
    is_valid: bool = True
    error_code: str | None = None
    error: str | None = None


class MeasurementItem(BaseModel):
    feature_index: int
    geometry_type: str | None = None
    measurement_crs: str | None = None
    crs_fallback: bool = False
    area_m2: float | None = None
    length_m: float | None = None


class PageMeta(BaseModel):
    file_id: str
    page: int
    page_size: int
    total: int
    pages: int


class FeaturePage(PageMeta):
    items: list[FeatureItem]


class MeasurementPage(PageMeta):
    units: Units = UNITS
    items: list[MeasurementItem]
