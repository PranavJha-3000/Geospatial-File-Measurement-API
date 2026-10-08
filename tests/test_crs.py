"""Feature-level CRS selection: UTM/UPS, fallback, antimeridian, geographic guard."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point, Polygon

from app.geo.crs import (
    FALLBACK_EPSG,
    UPS_NORTH,
    choose_projected_crs_for_feature,
    crosses_antimeridian,
    transform_geometry,
)

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
    epsg, fallback = choose_projected_crs_for_feature(BANGALORE_SQUARE, "EPSG:4326")
    assert epsg == "EPSG:32643"  # zone 43N for lon ~77.6
    assert fallback is False


def test_local_utm_southern_hemisphere():
    sydney = Point(151.2093, -33.8688)
    epsg, fallback = choose_projected_crs_for_feature(sydney, "EPSG:4326")
    assert epsg == "EPSG:32756"  # zone 56S for lon ~151.2
    assert fallback is False


def test_polar_uses_ups():
    svalbard = Point(15.0, 86.0)
    epsg, fallback = choose_projected_crs_for_feature(svalbard, "EPSG:4326")
    assert epsg == UPS_NORTH
    assert fallback is False


def test_antimeridian_polygon_uses_fallback():
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
    epsg, fallback = choose_projected_crs_for_feature(poly, "EPSG:4326")
    assert epsg == FALLBACK_EPSG
    assert fallback is True


def test_extensive_feature_uses_fallback():
    # 10 degrees of longitude exceeds one UTM zone width.
    wide = Polygon(
        [
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 1.0),
            (0.0, 1.0),
            (0.0, 0.0),
        ]
    )
    epsg, fallback = choose_projected_crs_for_feature(wide, "EPSG:4326")
    assert epsg == FALLBACK_EPSG
    assert fallback is True


def test_antimeridian_heuristic_ignores_projected_sources():
    # Easting/northing bounds near +/-170 in a projected CRS would look "wrapped"
    # to a naive lon/lat heuristic; the guard keeps projected sources on UTM.
    projected = LineString([(-175.0, 1000.0), (175.0, 2000.0)])
    epsg, fallback = choose_projected_crs_for_feature(projected, "EPSG:3857")
    # Representative point is ~1 km west of the 3857 origin -> lon ~ -0.0016 -> zone 30N.
    assert epsg == "EPSG:32630"
    assert fallback is False


def test_hard_guard_rejects_geographic_target():
    with pytest.raises(ValueError, match="geographic"):
        transform_geometry(BANGALORE_SQUARE, "EPSG:4326", "EPSG:4326")


def test_transform_produces_projected_result():
    projected = transform_geometry(BANGALORE_SQUARE, "EPSG:4326", "EPSG:32643")
    # ~100 m side square -> area close to 10,000 m2 (UTM distortion small at this scale).
    assert projected.area == pytest.approx(10_000, rel=0.02)
