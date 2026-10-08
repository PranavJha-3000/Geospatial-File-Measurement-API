"""Feature-level projected-CRS selection.

Rules (see README "CRS strategy"):
1. Antimeridian-spanning features (geographic sources) -> feature-centred
   azimuthal projection. No UTM zone is valid across the seam, and a cylindrical
   equal-area grid (e.g. EPSG:6933) reads a +/-179 degree strip as ~358 degrees
   wide, so it is deliberately NOT used.
2. Polar: lat > 84 -> UPS North (EPSG:32661); lat < -80 -> UPS South (EPSG:32761).
3. Normal features -> local UTM zone from the feature's representative point.
4. Extensive features (> 6 deg longitude span or > ~1000 km diagonal) ->
   feature-centred azimuthal projection.

No single planar projection is both equal-area and equidistant, so the fallback is
chosen by what is being measured:
- Polygons -> Lambert Azimuthal Equal-Area (LAEA): area is correct.
- Lines    -> Azimuthal Equidistant (AEQD): distance from the centre is correct.
Both are metre-based and projected (never geographic). PROJ measures angles
relative to the projection centre (lon_0), so a dateline-spanning feature does not
need to be manually unwrapped: a +/-179 degree strip centred on lon_0 ~ 180
projects to its true (thin) shape.
"""

from __future__ import annotations

import numpy as np
import shapely
from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry

# Human-readable labels stored in FeatureRecord.measurement_crs for fallbacks.
AREA_FALLBACK = "Lambert Azimuthal Equal-Area"
LENGTH_FALLBACK = "Azimuthal Equidistant"

UPS_NORTH = "EPSG:32661"
UPS_SOUTH = "EPSG:32761"

# Geographic spans beyond one UTM zone make zone distortion unacceptable.
_MAX_utm_lon_span_deg = 6.0
# Approx conversion: one degree of arc ~ 111 km; 1000 km diagonal guard.
_MAX_utm_diagonal_deg = 1000.0 / 111.0
_ANTIMERIDIAN_SPAN_deg = 180.0

_AREA_TYPES = ("Polygon", "MultiPolygon")


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


def _center_lonlat(geom: BaseGeometry, src: CRS) -> tuple[float, float]:
    """Representative point as WGS84 lon/lat.

    For a geographic feature that wraps the dateline the representative point is
    computed on a longitude-unwrapped copy, so the projection centre lands on the
    seam instead of at lon 0 (which would push the feature near the antipode).
    """
    work = geom
    if src.is_geographic and crosses_antimeridian(geom):

        def _unwrap(coords: np.ndarray) -> np.ndarray:
            x = np.where(coords[:, 0] < 0, coords[:, 0] + 360.0, coords[:, 0])
            return np.column_stack((x, coords[:, 1]))

        work = shapely.transform(geom, _unwrap)
    point = work.representative_point()
    if src.is_geographic:
        return float(point.x), float(point.y)
    to_wgs84 = Transformer.from_crs(src, CRS.from_epsg(4326), always_xy=True)
    lon, lat = to_wgs84.transform(point.x, point.y)
    return float(lon), float(lat)


def _azimuthal_proj4(geom: BaseGeometry, src: CRS) -> tuple[str, str]:
    """Feature-centred azimuthal CRS: (label, proj4). Equal-area for polygons,
    equidistant for lines."""
    lon, lat = _center_lonlat(geom, src)
    if geom.geom_type in _AREA_TYPES:
        proj, label = "laea", AREA_FALLBACK
    else:
        proj, label = "aeqd", LENGTH_FALLBACK
    target = f"+proj={proj} +lat_0={lat:.6f} +lon_0={lon:.6f} +datum=WGS84 +units=m +no_defs"
    return label, target


def choose_projected_crs_for_feature(
    geom: BaseGeometry,
    source_crs: str,
) -> tuple[str, str, bool]:
    """Return (label, target, used_fallback) for one source-CRS geometry.

    `label` is stored/displayed as the measurement CRS (an EPSG code for UTM/UPS,
    or a projection name for the azimuthal fallback). `target` is what
    `transform_geometry` consumes (an EPSG code or a proj4 string).
    """
    src = CRS.from_user_input(source_crs)
    # Antimeridian heuristic only makes sense for lon/lat coordinates; projected
    # easting/northing bounds near +/-170 would be false positives.
    if src.is_geographic and crosses_antimeridian(geom):
        label, target = _azimuthal_proj4(geom, src)
        return label, target, True

    # Representative point in source CRS -> WGS84 lon/lat for zone selection.
    to_wgs84 = Transformer.from_crs(src, CRS.from_epsg(4326), always_xy=True)
    point = geom.representative_point()
    lon, lat = to_wgs84.transform(point.x, point.y)

    # Extensive features exceed a single UTM zone -> azimuthal fallback.
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
        label, target = _azimuthal_proj4(geom, src)
        return label, target, True

    if lat > 84.0:
        return UPS_NORTH, UPS_NORTH, False
    if lat < -80.0:
        return UPS_SOUTH, UPS_SOUTH, False
    utm = _local_utm_epsg(lon, lat)
    return utm, utm, False


def transform_geometry(geom: BaseGeometry, source_crs: str, target: str) -> BaseGeometry:
    """Reproject a copy of `geom`; raises if the target is not projected.

    `target` may be an EPSG code or a proj4 string (the azimuthal fallback).
    """
    target_crs = CRS.from_user_input(target)
    # Hard guard: measurements must never run in a geographic CRS.
    if target_crs.is_geographic:
        raise ValueError(f"target CRS {target} is geographic; measurement requires projected CRS")
    transformer = Transformer.from_crs(CRS.from_user_input(source_crs), target_crs, always_xy=True)

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
