"""Test bootstrap: env isolation must happen BEFORE app imports."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="gfma_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TMP, 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(Path(_TMP, "uploads"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client() -> TestClient:
    """One client per test; schema created on startup, rows cleared between tests."""
    with TestClient(app) as test_client:
        yield test_client
    for table in reversed(Base.metadata.sorted_tables):
        with engine.begin() as conn:
            conn.execute(table.delete())
    shutil.rmtree(settings.upload_dir, ignore_errors=True)


def _post_file(client: TestClient, path: Path, filename: str, content_type: str):
    with path.open("rb") as fh:
        return client.post(
            "/api/files/",
            files={"file": (filename, fh, content_type)},
        )


def upload_kml(client: TestClient, name: str = "mixed.kml"):
    return _post_file(client, FIXTURES / name, name, "application/vnd.google-earth.kml+xml")


def upload_zip(client: TestClient, name: str):
    return _post_file(client, FIXTURES / name, name, "application/zip")


def upload_bytes(
    client: TestClient,
    filename: str,
    data: bytes,
    content_type: str = "application/octet-stream",
):
    return client.post(
        "/api/files/",
        files={"file": (filename, data, content_type)},
    )


@pytest.fixture()
def kml_ready(client: TestClient) -> dict:
    resp = upload_kml(client, "mixed.kml")
    assert resp.status_code == 201, resp.text
    return resp.json()
