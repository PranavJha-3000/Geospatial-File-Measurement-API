"""Pure per-feature measurement logic.

Pipeline per feature:
  drop Z -> make_valid() -> RE-CLASSIFY geometry type -> choose projected CRS
  -> reproject copy -> measure (m / m2) -> GeoJSON in source CRS

`make_valid()` can change a geometry's type (e.g. bowtie Polygon -> MultiPolygon
or GeometryCollection), so the type used for dispatch is always read AFTER repair.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely import make_valid
from shapely.geometry.base import BaseGeometry

from app.geo.crs import (
    choose_projected_crs_for_feature,
    drop_z,
    transform_geometry,
)
from app.geo.geometry import to_geojson_dict
from app.models import ErrorCode


@dataclass
class FeatureResult:
    original_geometry_type: str | None
    geometry_type: str | None
    geometry: dict[str, Any] | None  # GeoJSON in SOURCE CRS
    measurement_crs: str | None
    crs_fallback: bool
    area_m2: float | None
    length_m: float | None
    is_valid: bool
    error_code: str | None
    error: str | None


def _failed(
    original_type: str | None,
    code: str,
    message: str,
    geom: dict[str, Any] | None = None,
) -> FeatureResult:
    return FeatureResult(
        original_geometry_type=original_type,
        geometry_type=original_type,
        geometry=geom,
        measurement_crs=None,
        crs_fallback=False,
        area_m2=None,
        length_m=None,
        is_valid=False,
        error_code=code,
        error=message,
    )


def process_feature(geom: BaseGeometry | None, source_crs: str) -> FeatureResult:
    """Measure one feature; never raises for per-feature problems (isolated errors)."""
    if geom is None or geom.is_empty:
        return _failed(None, ErrorCode.EMPTY_GEOMETRY, "empty geometry")

    original_type = geom.geom_type
    original_geojson = to_geojson_dict(geom)

    try:
        geom_2d = drop_z(geom)
        if not geom_2d.is_valid:
            geom_2d = make_valid(geom_2d)
        # Re-classification AFTER repair: dispatch must use the repaired type.
        final_type = geom_2d.geom_type
    except Exception as exc:
        return _failed(
            original_type,
            ErrorCode.FEATURE_INVALID,
            f"geometry repair failed: {exc}",
            geom=original_geojson,
        )

    if geom_2d.is_empty:
        return _failed(original_type, ErrorCode.EMPTY_GEOMETRY, "geometry empty after repair")

    geojson = original_geojson

    # Points need no measurement, but remain valid features.
    if final_type in ("Point", "MultiPoint"):
        return FeatureResult(
            original_geometry_type=original_type,
            geometry_type=final_type,
            geometry=geojson,
            measurement_crs=None,
            crs_fallback=False,
            area_m2=None,
            length_m=None,
            is_valid=True,
            error_code=None,
            error=None,
        )

    if final_type not in ("Polygon", "MultiPolygon", "LineString", "MultiLineString"):
        # e.g. GeometryCollection produced by make_valid, or unsupported source type.
        return FeatureResult(
            original_geometry_type=original_type,
            geometry_type=final_type,
            geometry=geojson,
            measurement_crs=None,
            crs_fallback=False,
            area_m2=None,
            length_m=None,
            is_valid=False,
            error_code=ErrorCode.UNSUPPORTED_GEOMETRY,
            error=f"unsupported geometry type after repair: {final_type}",
        )

    try:
        measurement_crs, used_fallback = choose_projected_crs_for_feature(geom_2d, source_crs)
        projected = transform_geometry(geom_2d, source_crs, measurement_crs)
        # Hard guard: projected CRS only (transform_geometry also enforces this).
        if projected.is_empty:
            raise ValueError("projection produced empty geometry")
        area = length = None
        if final_type in ("Polygon", "MultiPolygon"):
            area = round(float(projected.area), 3)
        else:
            length = round(float(projected.length), 3)
        return FeatureResult(
            original_geometry_type=original_type,
            geometry_type=final_type,
            geometry=geojson,
            measurement_crs=measurement_crs,
            crs_fallback=used_fallback,
            area_m2=area,
            length_m=length,
            is_valid=True,
            error_code=None,
            error=None,
        )
    except Exception as exc:
        # Projection/measurement failure is contained to this feature only.
        return FeatureResult(
            original_geometry_type=original_type,
            geometry_type=final_type,
            geometry=geojson,
            measurement_crs=None,
            crs_fallback=False,
            area_m2=None,
            length_m=None,
            is_valid=False,
            error_code=ErrorCode.MEASUREMENT_FAILED,
            error=f"measurement failed: {exc}",
        )
