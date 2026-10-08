"""Upload content validation (extension, magic bytes, shapefile completeness).

All checks run before any GDAL/OGR call so bad input never reaches the geospatial
stack in an uncontrolled way.
"""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.errors import AppError
from app.models import ErrorCode


def classify_upload(filename: str, content_type: str | None) -> str:
    """Return "kml" or "shapefile"; raise AppError for anything else."""
    lower = filename.lower()
    if lower.endswith(".kml"):
        kind = "kml"
    elif lower.endswith(".zip"):
        kind = "shapefile"
    else:
        raise AppError(
            400,
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "only .kml files and .zip archives containing a Shapefile are supported",
        )
    # Cross-check content type when the client provides one (never trust it alone).
    if content_type and content_type not in (
        "application/octet-stream",
        "application/zip",
        "application/vnd.google-earth.kml+xml",
        "application/xml",
        "text/xml",
        "application/x-zip-compressed",
    ):
        raise AppError(
            400,
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            f"unexpected content type: {content_type}",
        )
    return kind


def check_magic_bytes(kind: str, data: bytes) -> None:
    if kind == "shapefile":
        if not data.startswith(b"PK\x03\x04"):
            raise AppError(400, ErrorCode.CORRUPT_FILE, "file is not a valid zip archive")
    else:  # kml
        head = data[:4096].lstrip()
        if not head.startswith(b"<?xml") and not head.startswith(b"<kml"):
            raise AppError(400, ErrorCode.CORRUPT_FILE, "file is not an XML/KML document")


def find_shapefile(extract_dir: Path) -> Path:
    """Locate exactly one .shp with sibling .shx/.dbf; ignore macOS junk files.

    Matching is case-insensitive: ArcGIS/QGIS exports commonly use .SHP/.SHX/.DBF
    and the API must behave identically on case-sensitive (Linux/Docker) filesystems.
    """
    all_files = [p for p in extract_dir.rglob("*") if p.is_file()]
    shp_files = sorted(
        p
        for p in all_files
        if p.suffix.lower() == ".shp" and "__MACOSX" not in p.parts and not p.name.startswith("._")
    )
    if len(shp_files) == 0:
        raise AppError(
            400,
            ErrorCode.SHAPEFILE_INCOMPLETE,
            "zip archive contains no .shp file",
        )
    if len(shp_files) > 1:
        raise AppError(
            400,
            ErrorCode.SHAPEFILE_INCOMPLETE,
            "zip archive contains multiple .shp files; upload exactly one Shapefile",
        )
    shp = shp_files[0]
    siblings = {p.name.lower() for p in shp.parent.iterdir() if p.is_file()}
    missing = [ext for ext in (".shx", ".dbf") if f"{shp.stem.lower()}{ext}" not in siblings]
    if missing:
        raise AppError(
            400,
            ErrorCode.SHAPEFILE_INCOMPLETE,
            f"shapefile is missing required component(s): {', '.join(missing)}",
        )
    return shp


def check_max_features(count: int) -> None:
    if count > settings.max_features:
        raise AppError(
            400,
            ErrorCode.FILE_TOO_LARGE,
            f"file has {count} features; limit is {settings.max_features}",
        )
