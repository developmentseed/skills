---
name: cng-conversions
description: Convert geospatial files (GeoTIFF, NetCDF, GeoJSON, Shapefile) to cloud-native formats (COG, GeoParquet) with validation. Use when converting spatial data for tiling, STAC catalogs, or cloud-native workflows.
---

# CNG Conversions

Geospatial file conversion and validation toolkit. Converts common geospatial formats to cloud-native equivalents optimized for tiling, object storage, and web map visualization.

| Conversion | Input | Output | Use case |
|---|---|---|---|
| GeoTIFF to COG | `.tif` | Cloud-Optimized GeoTIFF | Raster tiling via titiler, storage on S3/R2/GCS |
| NetCDF to COG | `.nc`, `.nc4` | Cloud-Optimized GeoTIFF | Climate/weather data for web visualization |
| GeoJSON to GeoParquet | `.geojson` | GeoParquet | Columnar vector storage, PostGIS loading |
| Shapefile to GeoParquet | `.shp` (or `.zip`) | GeoParquet | Legacy format migration, PostGIS loading |

Each conversion includes a **convert** script and a **validate** script. The validator runs automated checks to verify the output preserves all data from the source.

## Prerequisites

- Python 3.10+
- Raster conversions: `pip install rasterio rio-cogeo numpy pyproj`
- Vector conversions: `pip install geopandas pyarrow shapely numpy`
- NetCDF: additionally `pip install xarray netcdf4`

## Scripts

All scripts live under `scripts/<format>/` and are runnable as standalone CLI tools.

### GeoTIFF to COG

```bash
python scripts/geotiff-to-cog/convert.py --input data.tif --output data_cog.tif
python scripts/geotiff-to-cog/validate.py --input data.tif --output data_cog.tif
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--input` | Yes | -- | Path to input GeoTIFF |
| `--output` | Yes | -- | Path for output COG |
| `--compression` | No | `DEFLATE` | Compression: DEFLATE, ZSTD, or LZW |
| `--overwrite` | No | False | Overwrite output if it exists |
| `--verbose` | No | False | Print detailed progress |

Omit `--input` and `--output` from the validator to run a self-test with synthetic data.

### NetCDF to COG

```bash
python scripts/netcdf-to-cog/convert.py --input data.nc --output data_cog.tif --variable temperature
python scripts/netcdf-to-cog/validate.py --input data.nc --output data_cog.tif --variable temperature
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--input` | Yes | -- | Path to input .nc file |
| `--output` | Yes | -- | Path for output COG |
| `--variable` | No | first data var | NetCDF variable name to extract |
| `--time-index` | No | `0` | Timestep index for temporal variables |
| `--compression` | No | `DEFLATE` | Compression: DEFLATE, ZSTD, or LZW |
| `--overwrite` | No | False | Overwrite output if it exists |
| `--verbose` | No | False | Print detailed progress |

### GeoJSON to GeoParquet

```bash
python scripts/geojson-to-geoparquet/convert.py --input data.geojson --output data.parquet
python scripts/geojson-to-geoparquet/validate.py --input data.geojson --output data.parquet
```

### Shapefile to GeoParquet

```bash
python scripts/shapefile-to-geoparquet/convert.py --input data.shp --output data.parquet
python scripts/shapefile-to-geoparquet/validate.py --input data.shp --output data.parquet
```

Accepts `.shp` files directly or `.zip` archives (handles nested directories inside the zip).

## Known complexity

### Raster conversions

- **CRS reprojection:** If the input is not EPSG:4326, it is automatically reprojected. The shared `reproject.py` module uses `gdalwarp` when available (handles large files with disk-based chunking) and falls back to `rasterio.warp` otherwise. Output is always EPSG:4326.
- **Multi-variable NetCDFs:** Only one variable is extracted per conversion. If no `--variable` is specified, the first data variable is used.
- **Temporal dimensions:** Only one timestep is extracted per conversion. Use `--time-index` to select.
- **Geostationary projection:** Satellite files (GOES-R, Himawari, Meteosat) store x/y as scanning angles in radians. The converter automatically multiplies by `perspective_point_height` and reprojects. The `sweep_angle_axis` attribute is critical: GOES uses `x`, Meteosat uses `y`.
- **CF conventions:** Any projected CRS expressible in CF conventions is supported via `pyproj.CRS.from_cf()`.
- **Dimension naming:** The NetCDF converter recognizes `lat`/`latitude`/`y` and `lon`/`longitude`/`x`. Non-standard names produce a clear error.

### Vector conversions

- **Column lowercasing:** Both converters lowercase all column names on read. This prevents downstream issues with PostgreSQL tools that don't quote identifiers.

## Known failure modes

### GeoTIFF to COG

- **Do not write COGs directly with `rasterio.open()`**: Writing tiled GeoTIFFs with overviews directly produces invalid IFD ordering. Must use `rio-cogeo`'s `cog_translate` function.
- **Projected CRS bounds not compatible with STAC**: COGs with projected CRS have bounds in meters, not degrees. STAC requires WGS84 bounding boxes. Downstream ingest must reproject bounds via `rasterio.warp.transform_bounds(src.crs, "EPSG:4326", *src.bounds)`. Without this, tile servers like titiler-pgstac return empty tiles (204) because the STAC item bbox doesn't intersect any web mercator tiles.
- **Polar CRS datasets produce out-of-range WGS84 bounds**: Polar projections (e.g. EPSG:3412, EPSG:3413) produce bounds where `south=-90` or `north=90` after `transform_bounds`. Web Mercator is undefined at the poles. Passing these bounds to `WebMercatorViewport.fitBounds` (deck.gl) produces NaN viewport values, causing the map layer to fail silently. Fix: clamp bounds to +/-85.051129 degrees before fitting the viewport. The validate script flags this.
- **Colormap on multi-band COGs causes tile server 500**: Applying `colormap_name` (e.g. `viridis`) to an RGB/multi-band COG causes titiler to return HTTP 500. Colormaps only work on single-band data. Check band count before adding colormap parameters.
- **Single-band non-byte COGs need `rescale` for colormap rendering**: Applying `colormap_name` without `rescale` to float32/int16 COGs causes titiler to return 500 ("arrays used as indices must be of integer type"). Raw values can't index into a 256-entry colormap. Fix: pass `rescale=min,max` alongside `colormap_name`. Use p2/p98 percentiles for a good visual range. The validate script reports recommended rescale values.

### NetCDF to COG

- **NetCDF4 files report as HDF5 MIME type**: NetCDF4 is built on HDF5. `libmagic` reports their MIME type as `application/x-hdf5`, not `application/x-netcdf`. Any MIME-based format detection must whitelist both types.
- **Geostationary x/y not scaled to meters**: If scanning-angle coordinates are not multiplied by `perspective_point_height` before building the affine transform, the data appears as a tiny dot near (0,0). The converter handles this automatically.
- **Single-band float COGs need `rescale`**: NetCDF-to-COG always produces single-band float32 output. Same rescale requirement as GeoTIFF above.

### GeoJSON / Shapefile to GeoParquet

- **CRS comparison via string fails**: GeoJSON and GeoParquet serialize the same CRS differently (e.g. "EPSG:4326" vs full PROJJSON). Must use pyproj CRS equality (`src.crs == dst.crs`), not string comparison.
- **Uppercase column names break PostgreSQL tools**: GeoJSON and Shapefile files often have uppercase property names. PostgreSQL tools that query columns without quoting identifiers will fail. The converters lowercase all column names at read time.
- **Zipped Shapefiles with nested directories** (Shapefile only): `gpd.read_file("data.zip")` fails if the .shp is inside a subdirectory within the zip. The converter extracts the zip and walks the directory tree to find the .shp file.
- **Complex polygons cause PostGIS and MapLibre errors**: High-vertex polygon datasets (e.g. Natural Earth 1:10m countries) cause two failures: (1) PostGIS `ST_AsMVT` triggers "tolerance condition error (-20)" when vertex density is too high, returning HTTP 500; (2) MapLibre GL JS has a 65535 vertex limit per tile bucket, silently dropping features at low zoom. Fix: pre-simplify geometries before loading into PostGIS: `gdf.geometry.simplify(0.01, preserve_topology=True)`.

## Validation checks

### Raster (GeoTIFF / NetCDF)

| Check | Pass condition |
|---|---|
| COG structure | `rio-cogeo` validate returns valid |
| CRS | EPSG:4326 defined |
| Bounds match | COG bounds contain source cell centers |
| Dimensions | Pixel width/height match source grid |
| Band count | Matches source (GeoTIFF) or exactly 1 (NetCDF) |
| Pixel fidelity | Random samples, max diff < 1e-4 (geographic) or < 0.5 (reprojected) |
| NoData | nodata value is set and preserved |
| Overviews | >= 3 internal overview levels |
| Rendering metadata | Advisory: reports rescale range for tile server colormap rendering |
| WGS84 compatibility | Advisory: warns if projected CRS needs downstream bound reprojection |
| Mercator bounds | Advisory: warns if bounds exceed +/-85 degrees (Web Mercator limit) |

### Vector (GeoJSON / Shapefile)

| Check | Pass condition |
|---|---|
| Row count | Same number of features |
| CRS preserved | pyproj equality check |
| Columns preserved | All columns present (case-insensitive) |
| Geometry type | Same geometry types |
| Geometry validity | No new invalid geometries introduced |
| Geometry fidelity | Sampled WKT comparison |
| Attribute fidelity | Sampled value comparison |
| Bounds preserved | Total bounds within tolerance |
| GeoParquet metadata | Valid `geo` key in parquet metadata |
| Column names lowercase | All column names are lowercase |
