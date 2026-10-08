"""Geometry persistence: GeoJSON returned, source order, post-repair re-classification."""

from __future__ import annotations

import pytest
from shapely.geometry import Polygon

from app.geo.measurement import process_feature


def test_features_include_geojson_geometry(client, kml_ready):
    resp = client.get(f"/api/files/{kml_ready['id']}/features/")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 3
    # Source order preserved: polygon, line, point as declared in the fixture.
    assert [i["geometry_type"] for i in items] == ["Polygon", "LineString", "Point"]
    assert [i["feature_index"] for i in items] == [0, 1, 2]
    for item in items:
        assert item["geometry"]["type"] == item["geometry_type"]
        assert item["geometry"]["coordinates"]
        assert item["source_crs"] == "EPSG:4326"


def test_geometry_coordinates_match_source(client, kml_ready):
    items = client.get(f"/api/files/{kml_ready['id']}/features/").json()["items"]
    line = items[1]["geometry"]["coordinates"]
    # First vertex of the fixture LineString (lon, lat) — geometry stays in source CRS.
    assert line[0][0] == pytest.approx(77.5946, abs=1e-6)
    assert line[0][1] == pytest.approx(12.9716, abs=1e-6)


def test_make_valid_reclassification():
    """Self-intersecting bowtie polygon repairs into MultiPolygon; dispatch uses new type."""
    bowtie = Polygon(
        [
            (77.59, 12.97),
            (77.60, 12.98),
            (77.60, 12.97),
            (77.59, 12.98),
            (77.59, 12.97),
        ]
    )
    assert not bowtie.is_valid
    result = process_feature(bowtie, "EPSG:4326")
    assert result.original_geometry_type == "Polygon"
    assert result.geometry_type == "MultiPolygon"  # re-classified AFTER make_valid
    assert result.is_valid is True
    assert result.area_m2 is not None and result.area_m2 > 0
    assert result.geometry["type"] == "Polygon"  # persisted geometry = original source shape
