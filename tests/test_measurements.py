"""Measurement correctness: deterministic values vs independent geodesic oracle."""

from __future__ import annotations

import pytest
from pyproj import Geod
from shapely.geometry import LineString, Point, Polygon

from app.geo.measurement import process_feature
from tests.conftest import upload_kml

GEOD = Geod(ellps="WGS84")

SQUARE = Polygon(
    [
        (77.594139, 12.971151),
        (77.595061, 12.971151),
        (77.595061, 12.972049),
        (77.594139, 12.972049),
        (77.594139, 12.971151),
    ]
)
LINE = LineString([(77.5946, 12.9716), (77.6046, 12.9716)])


def test_polygon_area_within_1pct_of_geodesic_oracle():
    result = process_feature(SQUARE, "EPSG:4326")
    assert result.is_valid
    expected = abs(GEOD.geometry_area_perimeter(SQUARE)[0])
    assert result.area_m2 == pytest.approx(expected, rel=0.01)
    assert result.length_m is None  # polygons carry area only
    assert result.measurement_crs == "EPSG:32643"


def test_line_length_within_1pct_of_geodesic_oracle():
    result = process_feature(LINE, "EPSG:4326")
    assert result.is_valid
    expected = GEOD.line_length(*zip(*LINE.coords, strict=True))
    assert result.length_m == pytest.approx(expected, rel=0.01)
    assert result.area_m2 is None  # lines carry length only


def test_point_needs_no_measurement():
    result = process_feature(Point(77.5946, 12.9716), "EPSG:4326")
    assert result.is_valid
    assert result.area_m2 is None
    assert result.length_m is None
    assert result.measurement_crs is None
    assert result.error_code is None


def test_api_measurements_units_and_values(client):
    resp = upload_kml(client, "mixed.kml")
    assert resp.status_code == 201, resp.text
    file_id = resp.json()["id"]

    page = client.get(f"/api/files/{file_id}/measurements/").json()
    assert page["units"] == {"area": "m2", "length": "m"}
    items = page["items"]
    assert page["total"] == 3
    assert items[0]["geometry_type"] == "Polygon"
    assert items[0]["area_m2"] is not None and items[0]["area_m2"] > 0
    assert items[0]["length_m"] is None
    assert items[0]["measurement_crs"] == "EPSG:32643"
    assert items[1]["geometry_type"] == "LineString"
    assert items[1]["length_m"] is not None and items[1]["length_m"] > 0
    assert items[1]["area_m2"] is None
    assert items[2]["geometry_type"] == "Point"
    assert items[2]["area_m2"] is None and items[2]["length_m"] is None


def test_feature_units_block_present(client, kml_ready):
    items = client.get(f"/api/files/{kml_ready['id']}/features/").json()["items"]
    for item in items:
        assert item["units"] == {"area": "m2", "length": "m"}


def test_pagination_envelope(client, kml_ready):
    first = client.get(f"/api/files/{kml_ready['id']}/features/?page=1&page_size=2").json()
    assert first["page"] == 1 and first["page_size"] == 2
    assert first["total"] == 3 and first["pages"] == 2
    assert len(first["items"]) == 2

    second = client.get(f"/api/files/{kml_ready['id']}/features/?page=2&page_size=2").json()
    assert len(second["items"]) == 1
    assert second["items"][0]["feature_index"] == 2  # source order across pages


def test_pagination_validation(client, kml_ready):
    resp = client.get(f"/api/files/{kml_ready['id']}/features/?page=0")
    assert resp.status_code == 422
    resp = client.get(f"/api/files/{kml_ready['id']}/features/?page_size=9999")
    assert resp.status_code == 422
