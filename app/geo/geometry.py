"""Geometry/property serialization helpers (no CRS or I/O logic here)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from shapely.geometry.base import BaseGeometry


def to_geojson_dict(geom: BaseGeometry) -> dict[str, Any]:
    """Shapely geometry -> GeoJSON geometry mapping (source CRS coordinates)."""
    from shapely.geometry import mapping

    return dict(mapping(geom))


def sanitize_properties(raw: dict[str, Any], max_str: int = 1000) -> dict[str, Any]:
    """Keep only JSON-safe scalars; dates/bytes become strings, long strings truncated."""
    out: dict[str, Any] = {}
    for key, value in list(raw.items())[:64]:
        if value is None or isinstance(value, bool):
            out[str(key)] = value
        elif isinstance(value, int | float):
            out[str(key)] = value
        elif isinstance(value, str):
            out[str(key)] = value[:max_str]
        elif isinstance(value, datetime | date):
            out[str(key)] = value.isoformat()
        else:
            out[str(key)] = str(value)[:max_str]
    return out
