"""Endpoint tests: upload, metadata, validation errors, CRS_MISSING policy."""

from __future__ import annotations

from tests.conftest import upload_bytes, upload_kml, upload_zip


def test_upload_kml_ready(client):
    resp = upload_kml(client, "mixed.kml")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["file_type"] == "kml"
    assert body["feature_count"] == 3
    assert body["source_crs"] == "EPSG:4326"
    # Local UTM zone for Bangalore (lon ~77.6) is zone 43N.
    assert "EPSG:32643" in body["measurement_crs_summary"]
    # storage_key must be portable: relative, no drive letters / absolute roots.
    assert ":" not in body["storage_key"]
    assert not body["storage_key"].startswith("/")
    assert "\\" not in body["storage_key"]
    assert body["error_code"] is None


def test_upload_shapefile_zip_ready(client):
    resp = upload_zip(client, "shapefile_basic.zip")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["file_type"] == "shapefile"
    assert body["feature_count"] == 3
    assert body["source_crs"] == "EPSG:4326"
    assert "EPSG:32643" in body["measurement_crs_summary"]


def test_get_file_roundtrip(client, kml_ready):
    resp = client.get(f"/api/files/{kml_ready['id']}/")
    assert resp.status_code == 200
    assert resp.json()["id"] == kml_ready["id"]


def test_get_unknown_file_404(client):
    resp = client.get("/api/files/does-not-exist/")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_unsupported_extension(client):
    resp = upload_bytes(client, "notes.txt", b"hello")
    assert resp.status_code == 400
    assert resp.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_upload_too_large(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_upload_mb", 0)
    resp = upload_kml(client, "mixed.kml")
    assert resp.status_code == 413
    assert resp.json()["code"] == "FILE_TOO_LARGE"


def test_corrupt_kml_fails_controlled(client):
    resp = upload_kml(client, "invalid.kml")
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "CORRUPT_FILE"
    assert body["file_id"]  # failure persisted with an id
    detail = client.get(f"/api/files/{body['file_id']}/").json()
    assert detail["status"] == "failed"
    assert detail["error_code"] == "CORRUPT_FILE"


def test_shapefile_missing_prj_is_crs_missing(client):
    """Missing .prj must NEVER be silently assumed as EPSG:4326."""
    resp = upload_zip(client, "no_prj.zip")
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "CRS_MISSING"
    detail = client.get(f"/api/files/{body['file_id']}/").json()
    assert detail["status"] == "failed"
    assert detail["error_code"] == "CRS_MISSING"
    assert detail["source_crs"] is None


def test_features_on_failed_file_422(client):
    resp = upload_zip(client, "no_prj.zip")
    file_id = resp.json()["file_id"]
    features = client.get(f"/api/files/{file_id}/features/")
    assert features.status_code == 422
    assert features.json()["code"] == "CRS_MISSING"


def test_features_unknown_file_404(client):
    assert client.get("/api/files/nope/features/").status_code == 404


def test_unsupported_geometry_file_still_ready(client):
    """A GeometryCollection feature fails individually; the file itself succeeds."""
    resp = upload_kml(client, "unsupported.kml")
    assert resp.status_code == 201, resp.text
    file_id = resp.json()["id"]
    items = client.get(f"/api/files/{file_id}/features/").json()["items"]
    assert len(items) == 1
    assert items[0]["is_valid"] is False
    assert items[0]["error_code"] == "UNSUPPORTED_GEOMETRY"
    assert items[0]["area_m2"] is None
    assert items[0]["length_m"] is None
    # Geometry is still persisted for inspection.
    assert items[0]["geometry"]["type"] == "GeometryCollection"
