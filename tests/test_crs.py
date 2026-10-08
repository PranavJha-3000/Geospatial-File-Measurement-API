"""Feature-level CRS selection: UTM/UPS, azimuthal fallback, antimeridian, guard."""

from __future__ import annotations

import pytest
from pyproj import Geod
from shapely.geometry import LineString, Point, Polygon

from app.geo.crs import (
    AREA_FALLBACK,
    LENGTH_FALLBACK,
    UPS_NORTH,
    choose_projected_crs_for_feature,
    crosses_antimeridian,
    transform_geometry,
)
from app.geo.measurement import process_feature

GEOD = Geod(ellps="WGS84")

BANGALORE_SQUARE = Polygon(
    [
        (77.594139, 12.971151),
        (77.595061, 12.971151),
        (77.595061, 12.972049),
        (77.594139, 12.972049),
        (77.594139, 12.971151),
    ]
)


def test_local_utm_northern_hemisphere():
    label, target, fallback = choose_projected_crs_for_feature(BANGALORE_SQUARE, "EPSG:4326")
    assert label == target == "EPSG:32643"  # zone 43N for lon ~77.6
    assert fallback is False


def test_local_utm_southern_hemisphere():
    sydney = Point(151.2093, -33.8688)
    label, target, fallback = choose_projected_crs_for_feature(sydney, "EPSG:4326")
    assert label == target == "EPSG:32756"  # zone 56S for lon ~151.2
    assert fallback is False


def test_polar_uses_ups():
    svalbard = Point(15.0, 86.0)
    label, target, fallback = choose_projected_crs_for_feature(svalbard, "EPSG:4326")
    assert label == target == UPS_NORTH
    assert fallback is False


def test_antimeridian_polygon_uses_equal_area_fallback():
    # Spans 179E -> 179W: no single UTM zone covers this.
    poly = Polygon(
        [
            (179.0, 10.0),
            (-179.0, 10.0),
            (-179.0, 11.0),
            (179.0, 11.0),
            (179.0, 10.0),
        ]
    )
    assert crosses_antimeridian(poly)
    label, target, fallback = choose_projected_crs_for_feature(poly, "EPSG:4326")
    assert fallback is True
    assert label == AREA_FALLBACK
    assert target.startswith("+proj=laea ")


def test_extensive_line_uses_equidistant_fallback():
    # 10 degrees of longitude exceeds one UTM zone width; a line must stay
    # distance-accurate, so the fallback is equidistant (AEQD), not equal-area.
    wide = LineString([(0.0, 60.0), (10.0, 60.0)])
    label, target, fallback = choose_projected_crs_for_feature(wide, "EPSG:4326")
    assert fallback is True
    assert label == LENGTH_FALLBACK
    assert target.startswith("+proj=aeqd ")


def test_extensive_polygon_uses_equal_area_fallback():
    wide = Polygon([(0.0, 0.0), (10.0, 0.0), (10.0, 1.0), (0.0, 1.0), (0.0, 0.0)])
    label, target, fallback = choose_projected_crs_for_feature(wide, "EPSG:4326")
    assert fallback is True
    assert label == AREA_FALLBACK
    assert target.startswith("+proj=laea ")


def test_antimeridian_heuristic_ignores_projected_sources():
    # Easting/northing bounds near +/-170 in a projected CRS would look "wrapped"
    # to a naive lon/lat heuristic; the guard keeps projected sources on UTM.
    projected = LineString([(-175.0, 1000.0), (175.0, 2000.0)])
    label, target, fallback = choose_projected_crs_for_feature(projected, "EPSG:3857")
    # Representative point is ~1 km west of the 3857 origin -> lon ~ -0.0016 -> zone 30N.
    assert label == target == "EPSG:32630"
    assert fallback is False


def test_hard_guard_rejects_geographic_target():
    with pytest.raises(ValueError, match="geographic"):
        transform_geometry(BANGALORE_SQUARE, "EPSG:4326", "EPSG:4326")


def test_transform_produces_projected_result():
    projected = transform_geometry(BANGALORE_SQUARE, "EPSG:4326", "EPSG:32643")
    # ~100 m side square -> area close to 10,000 m2 (UTM distortion small at this scale).
    assert projected.area == pytest.approx(10_000, rel=0.02)


def test_antimeridian_polygon_area_matches_geodesic():
    """Regression: a dateline strip must not be read as a ~358-degree-wide shape.

    The old EPSG:6933 fallback over-reported this area by ~180x. The centred
    equal-area fallback must land within 1% of the ellipsoidal truth.
    """
    poly = Polygon([(179.0, 10.0), (-179.0, 10.0), (-179.0, 11.0), (179.0, 11.0), (179.0, 10.0)])
    result = process_feature(poly, "EPSG:4326")
    assert result.is_valid
    assert result.crs_fallback is True
    true_area = abs(GEOD.geometry_area_perimeter(poly)[0])
    assert result.area_m2 == pytest.approx(true_area, rel=0.01)


def test_extensive_line_length_matches_geodesic():
    """Regression: the fallback must preserve LineString length, not distort it.

    A 10-degree line at 60N was overstated ~73% under the old equal-area fallback.
    """
    line = LineString([(0.0, 60.0), (10.0, 60.0)])
    result = process_feature(line, "EPSG:4326")
    assert result.is_valid
    assert result.crs_fallback is True
    true_len = GEOD.line_length(*zip(*line.coords, strict=True))
    assert result.length_m == pytest.approx(true_len, rel=0.01)
