"""Deterministic fixture generator for shapefile ZIPs.

Run from the repository root:
    python scripts/make_shapefile_fixture.py

Produces:
- tests/fixtures/shapefile_basic.zip : 3 Polygons, .prj = EPSG:4326
- tests/fixtures/no_prj.zip          : identical data WITHOUT .prj (CRS_MISSING case)

Note: the ESRI Shapefile format stores ONE geometry type per .shp (spec shape types
are Point/PolyLine/Polygon), so a mixed Polygon+Line+Point shapefile cannot exist.
Mixed-geometry coverage comes from tests/fixtures/mixed.kml instead.
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

# Same square as mixed.kml plus two deterministic neighbours (Bangalore area).
SQUARE = Polygon(
    [
        (77.594139, 12.971151),
        (77.595061, 12.971151),
        (77.595061, 12.972049),
        (77.594139, 12.972049),
        (77.594139, 12.971151),
    ]
)
BLOCK2 = Polygon(
    [
        (77.595061, 12.971151),
        (77.595983, 12.971151),
        (77.595983, 12.972049),
        (77.595061, 12.972049),
        (77.595061, 12.971151),
    ]
)
BLOCK3 = Polygon(
    [
        (77.594139, 12.972049),
        (77.595061, 12.972049),
        (77.595061, 12.972947),
        (77.594139, 12.972947),
        (77.594139, 12.972049),
    ]
)


def build_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"Name": ["square", "block2", "block3"]},
        geometry=[SQUARE, BLOCK2, BLOCK3],
        crs="EPSG:4326",
    )


def _write_shapefile(out_dir: Path, with_prj: bool) -> Path:
    shp_path = out_dir / "data.shp"
    build_gdf().to_file(shp_path, engine="pyogrio")
    if not with_prj:
        shp_path.with_suffix(".prj").unlink(missing_ok=True)
    return shp_path


def _zip_dir(src_dir: Path, dest_zip: Path) -> None:
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src_dir.iterdir()):
            if path.is_file():
                zf.write(path, arcname=path.name)


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        base = tmp_path / "base"
        base.mkdir()
        _write_shapefile(base, with_prj=True)
        _zip_dir(base, FIXTURES / "shapefile_basic.zip")

        no_prj = tmp_path / "no_prj"
        no_prj.mkdir()
        _write_shapefile(no_prj, with_prj=False)
        _zip_dir(no_prj, FIXTURES / "no_prj.zip")

    for name in ("shapefile_basic.zip", "no_prj.zip"):
        print(f"wrote {FIXTURES / name} ({(FIXTURES / name).stat().st_size} bytes)")


if __name__ == "__main__":
    main()
