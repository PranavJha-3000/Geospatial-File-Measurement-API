"""KML and Shapefile loaders (GeoPandas + pyogrio GDAL engine).

Both return a GeoDataFrame in SOURCE order with columns [geometry, ...attributes]
plus the declared source CRS string. CRS policy:
- KML: EPSG:4326 is mandated by the KML spec (explicit set_crs, not a guess).
- Shapefile: CRS must be declared (.prj); otherwise the file fails with CRS_MISSING.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from app.errors import AppError
from app.geo.validation import find_shapefile


def _normalize(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reset to source order; keep every row (invalid/empty rows are handled later)."""
    return gdf.reset_index(drop=True)


def load_kml(path: Path) -> tuple[gpd.GeoDataFrame, str]:
    try:
        gdf = gpd.read_file(path, driver="KML", engine="pyogrio")
    except IndexError as exc:
        # pyogrio raises IndexError when the dataset has no layers at all —
        # a valid-but-empty KML, not a corrupt one (probed behaviour of the KML driver).
        raise AppError(422, "NO_FEATURES", "file contains no features") from exc
    except Exception as exc:
        raise AppError(400, "CORRUPT_FILE", f"unable to read KML: {exc}") from exc
    if gdf.crs is None:
        # Per the OGC KML spec coordinates are always WGS84 lon/lat.
        gdf = gdf.set_crs("EPSG:4326")
    source_crs = gdf.crs.to_string()
    return _normalize(gdf), source_crs


def load_shapefile(extract_dir: Path) -> tuple[gpd.GeoDataFrame, str]:
    shp_path = find_shapefile(extract_dir)
    try:
        gdf = gpd.read_file(shp_path, engine="pyogrio")
    except UnicodeDecodeError:
        gdf = gpd.read_file(shp_path, encoding="latin-1", engine="pyogrio")
    except Exception as exc:
        raise AppError(400, "CORRUPT_FILE", f"unable to read shapefile: {exc}") from exc

    if gdf.crs is None:
        # Missing/undecodable .prj: never guess a CRS — controlled failure instead.
        raise AppError(
            422,
            "CRS_MISSING",
            "shapefile has no declared CRS (.prj missing or unreadable); "
            "re-export it with a defined coordinate reference system",
        )
    return _normalize(gdf), gdf.crs.to_string()
