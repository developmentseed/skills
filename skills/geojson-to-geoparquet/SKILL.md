---
name: geojson-to-geoparquet
description: Convert GeoJSON files to GeoParquet with validation. Use when preparing vector data for PostgreSQL, cloud storage, or columnar analytics.
---

# GeoJSON to GeoParquet

Converts a GeoJSON file to GeoParquet for efficient columnar storage, smaller file sizes, and cloud-native access. Includes a validation script that checks data integrity and GeoParquet spec compliance.

## Prerequisites

- GDAL CLI tools (`ogr2ogr`)
- For validation: Python 3.10+ with `pip install -r requirements.txt`

## Conversion

Use GDAL's `ogr2ogr`. No custom script needed.

```bash
ogr2ogr -f Parquet output.parquet input.geojson
```

### Column lowercasing

`ogr2ogr` preserves the original column casing. If you're loading into PostgreSQL, lowercase column names first to avoid issues with tools that don't quote identifiers:

```python
import geopandas as gpd
gdf = gpd.read_file("input.geojson")
gdf.columns = [c.lower() for c in gdf.columns]
gdf.to_parquet("output.parquet")
```

## Validation

The validation script checks that the GeoParquet preserves all data from the source and meets spec requirements.

```bash
python scripts/validate.py --input input.geojson --output output.parquet
```

Omit both flags to run a self-test with synthetic data:

```bash
python scripts/validate.py
```

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

## Known failure modes

- **CRS comparison via string fails**: GeoJSON and GeoParquet serialize the same CRS differently (e.g. "EPSG:4326" vs full PROJJSON). Must use pyproj CRS equality (`src.crs == dst.crs`), not string comparison.
- **Uppercase column names break PostgreSQL tools**: GeoJSON files often have uppercase property names (e.g. Natural Earth data uses `NAME`, `POP_EST`). PostgreSQL tools that query columns without quoting identifiers will fail. Lowercase column names before loading.
- **Complex polygons cause PostGIS and MapLibre errors**: High-vertex polygon datasets (e.g. Natural Earth 1:10m countries) cause two failures: (1) PostGIS `ST_AsMVT` triggers "tolerance condition error (-20)" when vertex density is too high, returning HTTP 500; (2) MapLibre GL JS has a 65535 vertex limit per tile bucket, silently dropping features at low zoom. Fix: pre-simplify geometries before loading into PostGIS: `gdf.geometry.simplify(0.01, preserve_topology=True)`.
