---
name: cng-geotiff-to-cog
description: Convert GeoTIFF files to Cloud-Optimized GeoTIFFs (COG) with automatic CRS reprojection and validation. Use when preparing rasters for titiler, STAC catalogs, or cloud storage.
---

# GeoTIFF to Cloud-Optimized GeoTIFF

Converts a GeoTIFF to a Cloud-Optimized GeoTIFF (COG) for efficient cloud-based access, tiling, and visualization. Automatically reprojects non-EPSG:4326 inputs.

## Prerequisites

- Python 3.10+
- `pip install rasterio rio-cogeo numpy pyproj`

## Scripts

| File | Purpose |
|------|---------|
| `scripts/convert.py` | Convert a GeoTIFF to COG with configurable compression |
| `scripts/validate.py` | Validate that a COG preserves all data from the source GeoTIFF |
| `scripts/reproject.py` | Shared module: reproject to EPSG:4326 via gdalwarp or rasterio |

## Quickstart

```bash
pip install rasterio rio-cogeo numpy pyproj
python scripts/convert.py --input data.tif --output data_cog.tif
python scripts/validate.py --input data.tif --output data_cog.tif
```

## CLI flags

### convert.py

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--input` | Yes | -- | Path to input GeoTIFF |
| `--output` | Yes | -- | Path for output COG |
| `--compression` | No | `DEFLATE` | Compression method: DEFLATE, ZSTD, or LZW |
| `--overwrite` | No | False | Overwrite output if it exists |
| `--verbose` | No | False | Print detailed progress |

### validate.py

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--input` | No | -- | Path to original GeoTIFF (omit for self-test) |
| `--output` | No | -- | Path to converted COG (omit for self-test) |

When both `--input` and `--output` are omitted, runs a self-test that generates synthetic data, converts it, and validates the result.

## Known complexity

- **CRS reprojection:** If the input is not EPSG:4326, it is automatically reprojected. The `reproject.py` module uses `gdalwarp` when available (handles large files with disk-based chunking) and falls back to `rasterio.warp` otherwise. Output is always EPSG:4326.

## Known failure modes

- **Do not write COGs directly with `rasterio.open()`**: Writing tiled GeoTIFFs with overviews directly produces invalid IFD ordering. Must use `rio-cogeo`'s `cog_translate` function.
- **Projected CRS bounds not compatible with STAC**: COGs with projected CRS have bounds in meters, not degrees. STAC requires WGS84 bounding boxes. Downstream ingest must reproject bounds via `rasterio.warp.transform_bounds(src.crs, "EPSG:4326", *src.bounds)`. Without this, tile servers like titiler-pgstac return empty tiles (204) because the STAC item bbox doesn't intersect any web mercator tiles.
- **Polar CRS datasets produce out-of-range WGS84 bounds**: Polar projections (e.g. EPSG:3412, EPSG:3413) produce bounds where `south=-90` or `north=90` after `transform_bounds`. Web Mercator is undefined at the poles. Passing these bounds to `WebMercatorViewport.fitBounds` (deck.gl) produces NaN viewport values, causing the map layer to fail silently. Fix: clamp bounds to +/-85.051129 degrees before fitting the viewport. The validate script flags this.
- **Colormap on multi-band COGs causes tile server 500**: Applying `colormap_name` (e.g. `viridis`) to an RGB/multi-band COG causes titiler to return HTTP 500. Colormaps only work on single-band data. Check band count before adding colormap parameters.
- **Single-band non-byte COGs need `rescale` for colormap rendering**: Applying `colormap_name` without `rescale` to float32/int16 COGs causes titiler to return 500 ("arrays used as indices must be of integer type"). Raw values can't index into a 256-entry colormap. Fix: pass `rescale=min,max` alongside `colormap_name`. Use p2/p98 percentiles for a good visual range. The validate script reports recommended rescale values.

## Validation checks

| Check | Pass condition |
|---|---|
| COG structure | `rio-cogeo` validate returns valid |
| CRS EPSG:4326 | EPSG:4326 defined |
| Bounds preserved | Bounding box matches source (EPSG:4326 inputs) |
| Dimensions | Pixel width/height match source (EPSG:4326 inputs) |
| Band count | Matches source |
| Pixel fidelity | 1000 random samples, max diff < 1e-4 |
| NoData preserved | nodata value matches source |
| Overviews | >= 3 internal overview levels |
| Rendering metadata | Advisory: reports rescale range for tile server colormap rendering |
| WGS84 compatibility | Advisory: warns if projected CRS needs downstream bound reprojection |
| Mercator bounds | Advisory: warns if bounds exceed +/-85 degrees (Web Mercator limit) |
