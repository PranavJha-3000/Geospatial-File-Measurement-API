"""Filesystem persistence: uploads, safe extraction, storage_key resolution.

`storage_key` is always relative to UPLOAD_DIR (e.g. "<uuid>/wards.kml") so the
database never depends on absolute host paths.
"""

from __future__ import annotations

import uuid
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import UploadFile

from app.config import settings
from app.errors import AppError
from app.models import ErrorCode

_CHUNK = 1024 * 1024


def _upload_root() -> Path:
    root = settings.upload_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve(storage_key: str) -> Path:
    """Resolve a portable storage_key to an absolute path, enforcing containment."""
    root = _upload_root()
    candidate = (root / storage_key).resolve()
    if not candidate.is_relative_to(root):
        raise AppError(500, ErrorCode.CORRUPT_FILE, "invalid storage key")
    return candidate


def _safe_filename(filename: str) -> str:
    """Reduce a client-supplied filename to a plain basename.

    Clients may send full browser paths ("C:\\dir\\f.kml") and malicious ones
    ("../../evil.kml"); both must never escape the per-upload directory.
    Backslashes are normalised first so this behaves the same on POSIX and Windows.
    """
    name = PurePosixPath(filename.replace("\\", "/")).name
    if not name or name in (".", ".."):
        raise AppError(400, ErrorCode.UNSUPPORTED_MEDIA_TYPE, "invalid filename")
    return name[:255]  # matches FileRecord.original_filename column width


def save_upload(upload: UploadFile, file_id: str, filename: str) -> tuple[str, bytes]:
    """Stream an upload to UPLOAD_DIR/<uuid>/<sanitized name>; returns (storage_key, bytes).

    Returns raw bytes too: callers need them for magic-byte checks before any
    further I/O, and files are small (capped at MAX_UPLOAD_MB).
    """
    safe_name = _safe_filename(filename)
    dest_dir = _upload_root() / file_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe_name

    data = bytearray()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    while chunk := upload.file.read(_CHUNK):
        data.extend(chunk)
        if len(data) > max_bytes:
            dest.unlink(missing_ok=True)
            raise AppError(
                413,
                ErrorCode.FILE_TOO_LARGE,
                f"file exceeds {settings.max_upload_mb} MB limit",
            )
    dest.write_bytes(bytes(data))
    storage_key = f"{file_id}/{safe_name}"
    return storage_key, bytes(data)


def safe_extract_zip(file_id: str) -> Path:
    """Validate and extract an uploaded ZIP into UPLOAD_DIR/<uuid>/extracted/.

    Mitigations (comment explains the non-obvious security decisions):
    - zip-slip: reject absolute/parent-traversal paths via a resolved containment check;
    - zip-bomb: enforce uncompressed-size and file-count caps while streaming entries.
    """
    root = _upload_root()
    src = resolve(f"{file_id}/archive.zip")
    extract_dir = root / file_id / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    max_total = settings.max_uncompressed_mb * 1024 * 1024

    try:
        with zipfile.ZipFile(src) as zf:
            members = zf.infolist()
            if len(members) > settings.max_files_in_zip:
                raise AppError(
                    400,
                    ErrorCode.FILE_TOO_LARGE,
                    f"zip contains more than {settings.max_files_in_zip} entries",
                )

            # Map zip member names (lowercased) to the set of entries we expect to
            # be shapefile components. The .shp name defines the dataset stem, so
            # the sibling .shx/.dbf are derived from it.
            present: set[str] = set()
            total = 0
            for info in members:
                if info.is_dir():
                    continue
                name = info.filename
                p = PurePosixPath(name)
                if (
                    p.is_absolute()
                    or ".." in p.parts
                    or "\\" in name
                    or (p.parts and ":" in p.parts[0])
                ):
                    raise AppError(400, ErrorCode.CORRUPT_FILE, f"unsafe path in zip: {name}")
                # Symlink entries (unix mode in external_attr high bits) are rejected outright.
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise AppError(400, ErrorCode.CORRUPT_FILE, f"symlink entry in zip: {name}")
                # Fast-fail on claimed sizes...
                present.add(name.lower())
                total += info.file_size
                if total > max_total:
                    raise AppError(
                        413,
                        ErrorCode.FILE_TOO_LARGE,
                        f"uncompressed zip exceeds {settings.max_uncompressed_mb} MB",
                    )
                dest = (extract_dir / name).resolve()
                if not dest.is_relative_to(extract_dir.resolve()):
                    raise AppError(400, ErrorCode.CORRUPT_FILE, f"unsafe path in zip: {name}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                # ...then enforce the budget again on ACTUAL bytes: a crafted header
                # can under-report file_size, so claimed sizes alone are not trusted.
                budget = max_total - total
                with zf.open(info) as src_f, dest.open("wb") as out_f:
                    copied = 0
                    while chunk := src_f.read(_CHUNK):
                        copied += len(chunk)
                        if copied > budget:
                            raise AppError(
                                413,
                                ErrorCode.FILE_TOO_LARGE,
                                f"uncompressed zip exceeds {settings.max_uncompressed_mb} MB",
                            )
                        out_f.write(chunk)
                total += copied - info.file_size  # reconcile claimed vs actual

            # Shapefile completeness: exactly one .shp plus sibling .shx/.dbf.
            # find_shapefile is defined in app.geo.validation; importing here keeps
            # the processing layer free of storage concerns (no circular import).
            from app.geo.validation import find_shapefile

            shp_path = find_shapefile(extract_dir)
            expected = {
                shp_path.name.lower(),
                shp_path.with_suffix(".shx").name.lower(),
                shp_path.with_suffix(".dbf").name.lower(),
            }
            missing = expected - present
            if missing:
                raise AppError(
                    400,
                    ErrorCode.SHAPEFILE_INCOMPLETE,
                    f"zip archive is missing shapefile component(s): {', '.join(sorted(missing))}",
                )
    except zipfile.BadZipFile as exc:
        raise AppError(400, ErrorCode.CORRUPT_FILE, "corrupt zip archive") from exc

    return extract_dir


def new_file_id() -> str:
    return str(uuid.uuid4())
