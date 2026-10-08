"""Feature-level projected-CRS selection.

Rules (see README "CRS strategy"):
1. Antimeridian-spanning features -> EPSG:6933 fallback (no UTM zone is valid there).
2. Polar: lat > 84 -> UPS North (EPSG:32661); lat < -80 -> UPS South (EPSG:32761).
3. Normal features -> local UTM zone from the feature's representative point.
4. Extensive features (> 6 deg longitude span or > ~1000 km diagonal) -> EPSG:6933 fallback.

EPSG:6933 (EASE-Grid 2.0) is the documented fallback: global, metre-based and
equal-area, so areas stay meaningful; fallback lengths are approximate and flagged
via `crs_fallback`.
"""

from __future__ import annotations

import numpy as np
import shapely
from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry

FALLBACK_EPSG = "EPSG:6933"
UPS_NORTH = "EPSG:32661"
UPS_SOUTH = "EPSG:32761"

# Geographic spans beyond one UTM zone make zone distortion unacceptable.
_MAX_utm_lon_span_deg = 6.0
# Approx conversion: one degree of arc ~ 111 km; 1000 km diagonal guard.
_MAX_utm_diagonal_deg = 1000.0 / 111.0
_ANTIMERIDIAN_SPAN_deg = 180.0


def crosses_antimeridian(geom: BaseGeometry) -> bool:
    """Detect features whose lon/lat bounds wrap the antimeridian.

    Arrives either as an extreme bbox width (>180 deg) or as coordinates sitting on
    both sides of the seam (e.g. 179.5 and -179.5 in one feature).
    """
    minx, _, maxx, _ = geom.bounds
    if (maxx - minx) > _ANTIMERIDIAN_SPAN_deg:
        return True
    if minx < -170 and maxx > 170:
        return True
    return False


def _local_utm_epsg(lon: float, lat: float) -> str:
    zone = int((lon + 180.0) // 6.0) + 1
    zone = min(max(zone, 1), 60)
    return f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"


def choose_projected_crs_for_feature(
    geom: BaseGeometry,
    source_crs: str,
) -> tuple[str, bool]:
    """Return (measurement EPSG code, used_fallback) for one source-CRS geometry."""
    src = CRS.from_user_input(source_crs)
    # Antimeridian heuristic only makes sense for lon/lat coordinates; projected
    # easting/northing bounds near +/-170 would be false positives.
    if src.is_geographic and crosses_antimeridian(geom):
        return FALLBACK_EPSG, True

    # Representative point in source CRS -> WGS84 lon/lat for zone selection.
    to_wgs84 = Transformer.from_crs(src, CRS.from_epsg(4326), always_xy=True)
    point = geom.representative_point()
    lon, lat = to_wgs84.transform(point.x, point.y)

    # Extensive features exceed a single UTM zone -> global fallback.
    minx, miny, maxx, maxy = geom.bounds
    # Convert bounds to lon/lat for the span check.
    corners = [
        to_wgs84.transform(x, y)
        for x, y in ((minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy))
    ]
    lons = [c[0] for c in corners]
    lats = [c[1] for c in corners]
    lon_span = max(lons) - min(lons)
    lat_span = max(lats) - min(lats)
    diagonal_deg = (lon_span**2 + lat_span**2) ** 0.5
    if lon_span > _MAX_utm_lon_span_deg or diagonal_deg > _MAX_utm_diagonal_deg:
        return FALLBACK_EPSG, True

    if lat > 84.0:
        return UPS_NORTH, False
    if lat < -80.0:
        return UPS_SOUTH, False
    return _local_utm_epsg(lon, lat), False


def transform_geometry(geom: BaseGeometry, source_crs: str, target_epsg: str) -> BaseGeometry:
    """Reproject a copy of `geom`; raises if the target is not projected."""
    target = CRS.from_user_input(target_epsg)
    # Hard guard: measurements must never run in a geographic CRS.
    if target.is_geographic:
        raise ValueError(
            f"target CRS {target_epsg} is geographic; measurement requires projected CRS"
        )
    transformer = Transformer.from_crs(CRS.from_user_input(source_crs), target, always_xy=True)

    def _reproject(coords: np.ndarray) -> np.ndarray:
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        out = np.column_stack((x, y))
        if coords.shape[1] == 3:
            out = np.column_stack((out, coords[:, 2]))
        return out

    return shapely.transform(geom, _reproject)


def drop_z(geom: BaseGeometry) -> BaseGeometry:
    """Force 2D: measurement intent is planar (2D) geometry."""
    return shapely.force_2d(geom)
