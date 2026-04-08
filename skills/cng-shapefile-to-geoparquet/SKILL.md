---
name: cng-shapefile-to-geoparquet
description: Convert Shapefiles (including zipped) to GeoParquet with column lowercasing and validation. Use when migrating legacy vector data for PostgreSQL, cloud storage, or columnar analytics.
---

# Shapefile to GeoParquet

Converts a Shapefile (or zipped Shapefile) to GeoParquet for efficient columnar storage, cloud access, and modern geospatial workflows. Handles nested zip archives and lowercases all column names for PostgreSQL compatibility.

## Prerequisites

- Python 3.10+
- `pip install geopandas pyarrow shapely numpy`

## Scripts

| File | Purpose |
|------|---------|
| `scripts/convert.py` | Convert a Shapefile to GeoParquet |
| `scripts/validate.py` | Validate that GeoParquet preserves all data from the source Shapefile |

## Quickstart

```bash
pip install geopandas pyarrow shapely numpy
python scripts/convert.py --input data.shp --output data.parquet
python scripts/validate.py --input data.shp --output data.parquet
```

## CLI flags

### convert.py

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--input` | Yes | -- | Path to input .shp file (companion .dbf, .shx, .prj resolved automatically) |
| `--output` | Yes | -- | Path for output .parquet file |
| `--overwrite` | No | False | Overwrite output if it exists |
| `--verbose` | No | False | Print detailed progress |

### validate.py

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--input` | No | -- | Path to original Shapefile (omit for self-test) |
| `--output` | No | -- | Path to converted GeoParquet (omit for self-test) |

When both `--input` and `--output` are omitted, runs a self-test that generates synthetic data, converts it, and validates the result.

## Known complexity

- **Column lowercasing:** The converter lowercases all column names on read. This prevents downstream issues with PostgreSQL tools that don't quote identifiers.
- **Zipped Shapefiles:** Accepts `.zip` archives. The converter extracts the zip and walks the directory tree to find the `.shp` file, handling nested directories.

## Known failure modes

- **CRS comparison via string fails**: Shapefile and GeoParquet serialize the same CRS differently (e.g. "EPSG:4326" vs full PROJJSON). Must use pyproj CRS equality (`src.crs == dst.crs`), not string comparison.
- **Zipped Shapefiles with nested directories**: `gpd.read_file("data.zip")` fails if the .shp is inside a subdirectory within the zip. The converter handles this by extracting and walking the directory tree.
- **Uppercase column names break PostgreSQL tools**: Shapefiles commonly have uppercase column names (e.g. `NAME`, `AREA_KM2`). PostgreSQL tools that query columns without quoting identifiers will fail. The converter lowercases all column names at read time.
- **Complex polygons cause PostGIS and MapLibre errors**: High-vertex polygon datasets (e.g. Natural Earth 1:10m admin-0 countries, HydroRIVERS) cause two failures: (1) PostGIS `ST_AsMVT` triggers "tolerance condition error (-20)" when vertex density is too high, returning HTTP 500; (2) MapLibre GL JS has a 65535 vertex limit per tile bucket, silently dropping features at low zoom. Fix: pre-simplify geometries before loading into PostGIS: `gdf.geometry.simplify(0.01, preserve_topology=True)`.

## Validation checks (10 total)

| Check | Pass condition |
|---|---|
| Row count | Same number of features |
| CRS preserved | pyproj equality check |
| Columns preserved | All columns present (case-insensitive) |
| Geometry type | Same geometry types |
| Geometry validity | No new invalid geometries introduced |
| Geometry fidelity | 100 sampled WKT comparisons match |
| Attribute fidelity | 100 sampled value comparisons match |
| Bounds preserved | Total bounds within tolerance |
| GeoParquet metadata | Valid `geo` key in parquet metadata |
| Column names lowercase | All column names are lowercase |
