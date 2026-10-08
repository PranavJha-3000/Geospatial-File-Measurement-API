# Geospatial File Measurement API

A FastAPI service that ingests geospatial files (`.kml`, or `.zip` containing an ESRI Shapefile), stores every feature with its geometry as GeoJSON, and computes **polygon area in square metres** and **line length in metres** using a per-feature projected CRS.

Measurements are never computed in a geographic (lon/lat) CRS — every area/length value is produced after an explicit reprojection to a metre-based projection chosen for that feature.

---

## Quickstart

### Docker (recommended)

```bash
docker compose up --build
# API:      http://localhost:8000
# OpenAPI:  http://localhost:8000/docs
```

### Local (Python ≥ 3.12)

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux
pip install -r requirements-dev.txt

uvicorn app.main:app --reload
```

Upload a file:

```bash
curl -X POST http://localhost:8000/api/files/ \
  -F "file=@tests/fixtures/mixed.kml"
```

Run the quality gates:

```bash
pytest -q
ruff check .
mypy app/
```

---

## API

All responses are JSON. All errors share one envelope: `{"detail": "...", "code": "...", "file_id": null | "..."}`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/files/` | Upload a `.kml` or `.zip` (Shapefile). Returns `201` with file metadata. |
| `GET` | `/api/files/{id}/` | File metadata, processing status, CRS audit fields. |
| `GET` | `/api/files/{id}/features/` | Paginated features **with GeoJSON geometry** (source CRS). |
| `GET` | `/api/files/{id}/measurements/` | Paginated measurements with explicit units. |
| `GET` | `/health` | Liveness probe. |

Pagination: `?page=1&page_size=50` (`page ≥ 1`, `1 ≤ page_size ≤ 200`).
Envelope: `{file_id, page, page_size, total, pages, items}`.

### Examples

`POST /api/files/` → `201`:

```json
{
  "id": "d1f5...",
  "original_filename": "mixed.kml",
  "file_type": "kml",
  "status": "ready",
  "feature_count": 3,
  "source_crs": "EPSG:4326",
  "measurement_crs_summary": "EPSG:32643 (2/3 measured)",
  "storage_key": "d1f5.../mixed.kml",
  "created_at": "2026-10-08T13:00:00Z",
  "error_code": null,
  "error_message": null
}
```

`GET /api/files/{id}/features/` → `200` (item shape):

```json
{
  "feature_index": 0,
  "original_geometry_type": "Polygon",
  "geometry_type": "Polygon",
  "geometry": {"type": "Polygon", "coordinates": [[[77.594139, 12.971151]]]},
  "properties": {"Name": "square"},
  "source_crs": "EPSG:4326",
  "measurement_crs": "EPSG:32643",
  "crs_fallback": false,
  "area_m2": 9987.412,
  "length_m": null,
  "units": {"area": "m2", "length": "m"},
  "is_valid": true,
  "error_code": null,
  "error": null
}
```

`GET /api/files/{id}/measurements/` → `200`:

```json
{
  "file_id": "d1f5...",
  "page": 1, "page_size": 50, "total": 3, "pages": 1,
  "units": {"area": "m2", "length": "m"},
  "items": [
    {"feature_index": 0, "geometry_type": "Polygon",
     "measurement_crs": "EPSG:32643", "crs_fallback": false,
     "area_m2": 9987.412, "length_m": null}
  ]
}
```

### Error codes

| Code | HTTP | Meaning |
|---|---|---|
| `UNSUPPORTED_MEDIA_TYPE` | 400 | Not a `.kml`/`.zip` upload (or mismatched content type). |
| `FILE_TOO_LARGE` | 413 | Upload, uncompressed archive, entry count, or feature count over limit. |
| `CORRUPT_FILE` | 400 | Bad magic bytes, malformed XML/ZIP, or unreadable dataset. |
| `SHAPEFILE_INCOMPLETE` | 400 | No `.shp`, multiple `.shp`, or missing `.shx`/`.dbf`. |
| `CRS_MISSING` | 422 | Shapefile has no readable `.prj` — file marked `failed`; **no CRS is ever guessed**. |
| `NO_FEATURES` | 422 | File parsed but contains zero features. |
| `NOT_FOUND` | 404 | Unknown file id. |
| `FILE_NOT_READY` | 409 | File still `pending`/`processing`. |
| `FEATURE_INVALID`, `UNSUPPORTED_GEOMETRY`, `EMPTY_GEOMETRY`, `MEASUREMENT_FAILED` | — | Per-feature errors: stored on the row (`is_valid=false`); the file still becomes `ready`. |

---

## Architecture

```
HTTP (app/api/routes)  →  orchestration (app/services)  →  geospatial (app/geo)
                              │                                │
                              ▼                                ▼
                        repositories (app/repositories: SQL + filesystem storage)
                              │
                              ▼
                        database (app/db, app/models) + UPLOAD_DIR on disk
```

| Layer | Modules | Responsibility |
|---|---|---|
| HTTP | `api/routes/*`, `api/deps.py`, `api/common.py`, `schemas.py`, `errors.py` | Request/response models, pagination, status-code mapping. No geo logic. |
| Orchestration | `services/file_service.py` | Status transitions `pending → processing → ready/failed`, per-feature error isolation. |
| Geospatial | `geo/loaders.py`, `geo/crs.py`, `geo/measurement.py`, `geo/geometry.py`, `geo/validation.py` | Pure processing. No FastAPI/SQLAlchemy imports. |
| Persistence | `repositories/file_repo.py`, `repositories/feature_repo.py`, `repositories/storage.py` | SQL only; `storage.py` owns disk paths and safe extraction. |
| Database | `db.py`, `models.py` | SQLAlchemy 2.0 models, SQLite locally. |

`geo/` is deliberately framework-free so measurement logic can be unit-tested without HTTP or a database.

---

## Processing flow

```
POST /api/files/
  ├─ validate: extension + content type → classify (kml | shapefile)
  ├─ stream to disk under UPLOAD_DIR/<uuid>/ with size cap
  ├─ magic-byte check (PK zip signature | XML/KML header)
  │    └─ failure → file row = failed(CORRUPT_FILE / FILE_TOO_LARGE) + 4xx
  ├─ status = processing
  ├─ [zip] safe extraction (zip-slip + zip-bomb guards) → exactly one .shp + .shx + .dbf
  ├─ load → GeoDataFrame in source order + declared CRS
  │    └─ shapefile without .prj → failed(CRS_MISSING) + 422  ← never assumed as 4326
  ├─ for each feature (source order):
  │    drop Z → make_valid() → RE-CLASSIFY type → choose projected CRS
  │    → reproject copy → measure (m² / m) → store GeoJSON (source CRS)
  │    └ any failure stays on the row (is_valid=false, error_code=...)
  ├─ bulk insert features (one transaction) → status = ready
  └─ GETs: pending/processing → 409, failed → 422 with the file's error code
```

File-level failures (corrupt archive, incomplete shapefile, missing CRS, no features) set `status=failed` with a stable `error_code`; per-feature failures never fail the file.

---

## CRS strategy

### Policy

- **KML → `EPSG:4326`** — mandated by the OGC KML specification; set explicitly (`set_crs`), not guessed.
- **Shapefile → declared CRS only.** The `.prj` (or the CRS reported by GDAL) is the source of truth. If it is missing/unreadable, ingestion fails with `CRS_MISSING`. Guessing `4326` would silently produce wrong measurements, so the API refuses.
- **Measurements never run in a geographic CRS.** `transform_geometry()` rejects any target where `crs.is_geographic` is true; the choice function only returns projected EPSG codes.

### Feature-level projected-CRS selection

Applied per feature (not per file), because a dataset can mix a small urban parcel with a country-spanning polygon:

1. **Antimeridian** (geographic sources only): bbox width > 180° or coordinates on both sides of ±170° → fallback `EPSG:6933`. No UTM zone is valid across the seam.
2. **Polar**: representative latitude > 84° → UPS North `EPSG:32661`; < −80° → UPS South `EPSG:32761`.
3. **Normal**: local UTM zone from the representative point — `zone = ⌊(lon+180)/6⌋+1` → `EPSG:326xx` (north) / `EPSG:327xx` (south). E.g. Bengaluru (≈77.6°E) → `EPSG:32643`.
4. **Extensive**: lon-span > 6° or diagonal > ~1000 km → fallback `EPSG:6933` (EASE-Grid 2.0): global, metre-based, equal-area.

Every feature row stores its own `measurement_crs` and a `crs_fallback` flag; the file stores a display summary (e.g. `EPSG:32643 (2/3 measured)` — points need no measurement, so they are excluded).

### Trade-offs

| Decision | Why | Cost |
|---|---|---|
| Per-feature UTM over one dataset-wide CRS | Local accuracy for small features; honest fallback flags for large ones | Features in one file can have different measurement CRS — comparability is per-zone |
| `EPSG:6933` fallback | Global, metre-based, equal-area; areas stay meaningful | Lengths on fallback features are approximate (flagged via `crs_fallback`) |
| Strict `CRS_MISSING` failure | No silent wrong answers | Some real-world files must be re-exported with a `.prj` before use |
| Stored geometry stays in **source** CRS | Faithful to the uploaded data; measurements carry their own CRS record | Consumers must reproject themselves if they want to map-measure from the API geometry |

---




## Design decisions

- **Synchronous processing.** Files are capped (50 MB / 20k features) and process comfortably within a request timeout. The `pending/processing` states already encode an async contract, so a worker queue can be added later without an API change — adding Celery/Redis now would be speculative infrastructure.
- **SQLite as the canonical evaluation database.** One file, zero setup, identical SQL through SQLAlchemy. PostgreSQL is a *compatible deployment target*: the schema uses only portable types (`String`, `JSON`, `Float`, `DateTime`) — but it needs the driver: `pip install -r requirements-postgres.txt` (installs `psycopg2-binary==2.9.13`) and `DATABASE_URL=postgresql+psycopg2://...`. A URL alone is not enough without a driver; SQLite remains the default everywhere, including Docker.
- **Geometry persisted as GeoJSON** in a `JSON` column. The assignment requires returning geometry per feature; JSON behaves identically on SQLite (TEXT) and PostgreSQL (`jsonb`-compatible), and avoids adding SpatiaLite/PostGIS.
- **Portable `storage_key`** (`"<uuid>/<filename>"`, relative to `UPLOAD_DIR`). The database never contains absolute host paths; containers and hosts resolve the same key differently.
- **Measurements stored, not recomputed.** `GET measurements/` is a projection of stored values → cheap, deterministic, auditable.
- **`make_valid()` then re-classify.** Repair can turn a Polygon into a MultiPolygon (or a GeometryCollection). The dispatch type is read *after* repair; both `original_geometry_type` and the final `geometry_type` are stored.
- **Per-feature error isolation.** One bad ring does not sink a 5 000-feature upload; the row records an `error_code` and the file still becomes `ready`.
- **UUID primary keys.** URL-safe, non-enumerable, identical behaviour on SQLite and PostgreSQL.

### Security

- Upload caps: 50 MB body, 200 MB uncompressed, 50 archive entries, 20 000 features — enforced while streaming.
- ZIP extraction rejects absolute paths, `..` traversal, drive letters and symlinks; every target path is resolved and verified to stay inside the extraction root; uncompressed sizes are accumulated during extraction (zip-bomb).
- Magic-byte checks run before any GDAL call, so renamed executables never reach the parser.
- Uploaded data is scoped to `UPLOAD_DIR/<uuid>/`.

---

## Testing

```bash
pytest -q          # 36 tests
ruff check .       # lint
ruff format --check .
mypy app/          # types
```

| File | Covers |
|---|---|
| `tests/test_api_files.py` | Upload happy paths, metadata, 404, validation errors, `CRS_MISSING` policy, failed-file reads |
| `tests/test_features_geometry.py` | GeoJSON presence + coordinates, source order, bow-tie repair → `MultiPolygon` re-classification |
| `tests/test_measurements.py` | Area/length vs independent `pyproj.Geod` ellipsoidal oracle (±1 %), point semantics, units blocks, pagination |
| `tests/test_crs.py` | UTM N/S, UPS, antimeridian fallback, extensive-feature fallback, projected-source guard, geographic-target guard |
| `tests/test_security.py` | Zip-slip, absolute paths, incomplete/corrupt archives, storage-key scoping |

Determinism: fixtures are checked in with fixed coordinates (`mixed.kml`, `unsupported.kml`, `invalid.kml`); shapefile ZIPs are regenerated deterministically by `python scripts/make_shapefile_fixture.py`. No network, no randomness, no wall-clock assertions.

> The ESRI Shapefile format allows exactly one geometry type per `.shp`, so the Shapefile fixture is polygon-only; mixed Polygon/Line/Point coverage comes from `mixed.kml`.

---

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./app.db` | SQLAlchemy URL (SQLite canonical; `postgresql+psycopg2://` with `requirements-postgres.txt`) |
| `UPLOAD_DIR` | `./uploads` | Root for stored files; keys are relative to it |
| `MAX_UPLOAD_MB` | `50` | Upload size cap |
| `MAX_UNCOMPRESSED_MB` | `200` | Zip-bomb cap |
| `MAX_FILES_IN_ZIP` | `50` | Archive entry cap |
| `MAX_FEATURES` | `20000` | Feature count cap |

---

## Stack

Python 3.12 · FastAPI 0.143 · SQLAlchemy 2.1 · GeoPandas 1.2 (pyogrio/GDAL engine) · Shapely 2.2 · pyproj 3.8 · pytest · Ruff · mypy — exact pins in `requirements*.txt`. pyogrio's wheels bundle GDAL, so neither Docker nor local installs need system GDAL packages.

---

## Learning & future scope

What this exercise made explicit: geodesic vs projected measurement error is not academic (a lon/lat "area" is meaningless), CRS choice is a *measurement decision*, and GDAL's tolerance for broken real-world files (missing `.prj`, non-UTF-8 DBFs, self-intersecting rings) must be wrapped in deliberate policy rather than blanket try/except.

Reasonable next steps, each deliberately **out of scope** here:

- **Async processing** (worker queue) for much larger files — the status model already allows it.
- **PostgreSQL + PostGIS** deployment as a real target (driver already pinned) for concurrent writes and spatial indexing.
- **GeoJSON/CSV export endpoints** and ETag caching for feature pages.
- **Auth + rate limiting** — only once the API is exposed beyond evaluation.

