---
name: shapefile-to-geoparquet
description: Convert Shapefiles (including zipped) to GeoParquet with validation. Use when migrating legacy vector data for PostgreSQL, cloud storage, or columnar analytics.
---

# Shapefile to GeoParquet

Converts a Shapefile (or zipped Shapefile) to GeoParquet for efficient columnar storage, cloud access, and modern geospatial workflows. Includes a validation script that checks data integrity and GeoParquet spec compliance.

## Prerequisites

- GDAL CLI tools (`ogr2ogr`)
- For validation: Python 3.10+ with `pip install -r requirements.txt`

## Conversion

Use GDAL's `ogr2ogr`. No custom script needed.

```bash
# From a .shp file:
ogr2ogr -f Parquet output.parquet input.shp

# From a zipped shapefile:
ogr2ogr -f Parquet output.parquet /vsizip/path/to/archive.zip
```

### Zipped shapefiles with nested directories

If `ogr2ogr` can't find the .shp inside a zip (nested directories), extract first:

```bash
unzip archive.zip -d extracted/
ogr2ogr -f Parquet output.parquet extracted/path/to/data.shp
```

### Column lowercasing

`ogr2ogr` preserves the original column casing. Shapefiles commonly have uppercase column names (e.g. `NAME`, `AREA_KM2`). If you're loading into PostgreSQL, lowercase them first:

```python
import geopandas as gpd
gdf = gpd.read_file("input.shp")
gdf.columns = [c.lower() for c in gdf.columns]
gdf.to_parquet("output.parquet")
```

## Validation

The validation script checks that the GeoParquet preserves all data from the source and meets spec requirements.

```bash
python scripts/validate.py --input input.shp --output output.parquet
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

- **CRS comparison via string fails**: Shapefile and GeoParquet serialize the same CRS differently (e.g. "EPSG:4326" vs full PROJJSON). Must use pyproj CRS equality (`src.crs == dst.crs`), not string comparison.
- **Zipped Shapefiles with nested directories**: `gpd.read_file("data.zip")` fails if the .shp is inside a subdirectory within the zip. Use GDAL's `/vsizip/` path or extract manually.
- **Uppercase column names break PostgreSQL tools**: Shapefiles commonly have uppercase column names. PostgreSQL tools that query columns without quoting identifiers will fail. Lowercase column names before loading.
- **Complex polygons cause PostGIS and MapLibre errors**: High-vertex polygon datasets (e.g. Natural Earth 1:10m admin-0 countries, HydroRIVERS) cause two failures: (1) PostGIS `ST_AsMVT` triggers "tolerance condition error (-20)" when vertex density is too high, returning HTTP 500; (2) MapLibre GL JS has a 65535 vertex limit per tile bucket, silently dropping features at low zoom. Fix: pre-simplify geometries before loading into PostGIS: `gdf.geometry.simplify(0.01, preserve_topology=True)`.
