---
name: geotiff-to-cog
description: Convert GeoTIFF files to Cloud-Optimized GeoTIFFs (COG) with validation. Use when preparing rasters for titiler, STAC catalogs, or cloud storage.
---

# GeoTIFF to Cloud-Optimized GeoTIFF

Converts a GeoTIFF to a Cloud-Optimized GeoTIFF (COG) for efficient cloud-based access, tiling, and visualization. Includes a validation script that checks data integrity and downstream compatibility.

## Prerequisites

- GDAL CLI tools (`gdal_translate`, `gdalwarp`)
- For validation: Python 3.10+ with `pip install -r requirements.txt`

## Conversion

Use GDAL's built-in COG driver. No custom script needed.

```bash
# Input already in EPSG:4326:
gdal_translate -of COG -co COMPRESS=DEFLATE input.tif output_cog.tif

# Input in a different CRS (reproject to EPSG:4326):
gdalwarp -t_srs EPSG:4326 -of COG -co COMPRESS=DEFLATE input.tif output_cog.tif
```

Common options:
- `-co COMPRESS=DEFLATE|ZSTD|LZW` — compression method
- `-co BLOCKSIZE=512` — tile size (default 512)
- `-co NUM_THREADS=ALL_CPUS` — parallelize compression
- `-co OVERVIEW_RESAMPLING=NEAREST|BILINEAR|CUBIC` — overview resampling

## Validation

The validation script checks that the COG preserves all data from the source and flags downstream compatibility issues.

```bash
python scripts/validate.py --input original.tif --output converted_cog.tif
```

Omit both flags to run a self-test with synthetic data:

```bash
python scripts/validate.py
```

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

## Known failure modes

- **Do not write COGs directly with `rasterio.open()`**: Writing tiled GeoTIFFs with overviews via rasterio produces invalid IFD ordering. Use `gdal_translate -of COG` or `rio-cogeo`'s `cog_translate` function instead.
- **Projected CRS bounds not compatible with STAC**: COGs with projected CRS have bounds in meters, not degrees. STAC requires WGS84 bounding boxes. Downstream ingest must reproject bounds via `rasterio.warp.transform_bounds(src.crs, "EPSG:4326", *src.bounds)`. Without this, tile servers like titiler-pgstac return empty tiles (204) because the STAC item bbox doesn't intersect any web mercator tiles.
- **Polar CRS datasets produce out-of-range WGS84 bounds**: Polar projections (e.g. EPSG:3412, EPSG:3413) produce bounds where `south=-90` or `north=90` after `transform_bounds`. Web Mercator is undefined at the poles. Passing these bounds to `WebMercatorViewport.fitBounds` (deck.gl) produces NaN viewport values, causing the map layer to fail silently. Fix: clamp bounds to +/-85.051129 degrees before fitting the viewport. The validate script flags this.
- **Colormap on multi-band COGs causes tile server 500**: Applying `colormap_name` (e.g. `viridis`) to an RGB/multi-band COG causes titiler to return HTTP 500. Colormaps only work on single-band data. Check band count before adding colormap parameters.
- **Single-band non-byte COGs need `rescale` for colormap rendering**: Applying `colormap_name` without `rescale` to float32/int16 COGs causes titiler to return 500 ("arrays used as indices must be of integer type"). Raw values can't index into a 256-entry colormap. Fix: pass `rescale=min,max` alongside `colormap_name`. Use p2/p98 percentiles for a good visual range. The validate script reports recommended rescale values.
