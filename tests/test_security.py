"""Security tests: zip-slip, unsafe members, corrupt archives, incomplete shapefiles."""

from __future__ import annotations

import io
import zipfile

from tests.conftest import upload_bytes, upload_zip


def _zip_with(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


def test_zip_slip_parent_traversal_rejected(client):
    payload = _zip_with([("../evil.shp", b"evil"), ("data.shx", b"x"), ("data.dbf", b"d")])
    resp = upload_bytes(client, "slip.zip", payload, "application/zip")
    assert resp.status_code == 400
    assert resp.json()["code"] == "CORRUPT_FILE"


def test_zip_absolute_path_rejected(client):
    payload = _zip_with([("/etc/passwd", b"root")])
    resp = upload_bytes(client, "abs.zip", payload, "application/zip")
    assert resp.status_code == 400
    assert resp.json()["code"] == "CORRUPT_FILE"


def test_zip_without_shapefile_rejected(client):
    payload = _zip_with([("readme.txt", b"hello")])
    resp = upload_bytes(client, "empty.zip", payload, "application/zip")
    assert resp.status_code == 400
    assert resp.json()["code"] == "SHAPEFILE_INCOMPLETE"


def test_shapefile_missing_dbf_rejected(client):
    # shp + shx present, dbf missing -> incomplete shapefile.
    payload = _zip_with([("data.shp", b"not-a-real-shp"), ("data.shx", b"x")])
    resp = upload_bytes(client, "incomplete.zip", payload, "application/zip")
    assert resp.status_code == 400
    assert resp.json()["code"] == "SHAPEFILE_INCOMPLETE"


def test_not_a_zip_rejected_by_magic_bytes(client):
    resp = upload_bytes(client, "fake.zip", b"definitely not a zip", "application/zip")
    assert resp.status_code == 400
    assert resp.json()["code"] == "CORRUPT_FILE"


def test_truncated_zip_rejected(client):
    # Valid PK signature but structurally broken archive.
    resp = upload_bytes(client, "trunc.zip", b"PK\x03\x04garbage", "application/zip")
    assert resp.status_code == 400
    assert resp.json()["code"] == "CORRUPT_FILE"


def test_upload_uses_uuid_scoped_storage(client):
    resp = upload_zip(client, "shapefile_basic.zip")
    assert resp.status_code == 201
    storage_key = resp.json()["storage_key"]
    # Scoped under the file id, relative to UPLOAD_DIR.
    assert storage_key.startswith(f"{resp.json()['id']}/")
    assert ".." not in storage_key
