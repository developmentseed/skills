---
name: cng-geojson-to-geoparquet
description: Convert GeoJSON files to GeoParquet with column lowercasing and validation. Use when preparing vector data for PostgreSQL, cloud storage, or columnar analytics.
---

# GeoJSON to GeoParquet

Converts a GeoJSON file to GeoParquet for efficient columnar storage, smaller file sizes, and cloud-native access. Lowercases all column names for PostgreSQL compatibility.

## Prerequisites

- Python 3.10+
- `pip install geopandas pyarrow shapely numpy`

## Scripts

| File | Purpose |
|------|---------|
| `scripts/convert.py` | Convert a GeoJSON file to GeoParquet |
| `scripts/validate.py` | Validate that GeoParquet preserves all data from the source GeoJSON |

## Quickstart

```bash
pip install geopandas pyarrow shapely numpy
python scripts/convert.py --input data.geojson --output data.parquet
python scripts/validate.py --input data.geojson --output data.parquet
```

## CLI flags

### convert.py

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--input` | Yes | -- | Path to input .geojson or .json file |
| `--output` | Yes | -- | Path for output .parquet file |
| `--overwrite` | No | False | Overwrite output if it exists |
| `--verbose` | No | False | Print detailed progress |

### validate.py

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--input` | No | -- | Path to original GeoJSON (omit for self-test) |
| `--output` | No | -- | Path to converted GeoParquet (omit for self-test) |

When both `--input` and `--output` are omitted, runs a self-test that generates synthetic data, converts it, and validates the result.

## Known complexity

- **Column lowercasing:** The converter lowercases all column names on read. This prevents downstream issues with PostgreSQL tools that don't quote identifiers.

## Known failure modes

- **CRS comparison via string fails**: GeoJSON and GeoParquet serialize the same CRS differently (e.g. "EPSG:4326" vs full PROJJSON). Must use pyproj CRS equality (`src.crs == dst.crs`), not string comparison.
- **Uppercase column names break PostgreSQL tools**: GeoJSON files often have uppercase property names (e.g. Natural Earth data uses `NAME`, `POP_EST`). PostgreSQL tools that query columns without quoting identifiers will fail. The converter lowercases all column names at read time.
- **Complex polygons cause PostGIS and MapLibre errors**: High-vertex polygon datasets (e.g. Natural Earth 1:10m countries) cause two failures: (1) PostGIS `ST_AsMVT` triggers "tolerance condition error (-20)" when vertex density is too high, returning HTTP 500; (2) MapLibre GL JS has a 65535 vertex limit per tile bucket, silently dropping features at low zoom. Fix: pre-simplify geometries before loading into PostGIS: `gdf.geometry.simplify(0.01, preserve_topology=True)`.

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
