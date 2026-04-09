---
name: netcdf-to-cog
description: Convert NetCDF files to Cloud-Optimized GeoTIFFs (COG) with support for geostationary satellites, CF conventions, and automatic CRS reprojection. Use when preparing climate/weather/satellite data for web visualization.
---

# NetCDF to Cloud-Optimized GeoTIFF

Converts a NetCDF variable and timestep to a Cloud-Optimized GeoTIFF (COG) for efficient cloud-based access, tiling, and visualization. Handles geographic, geostationary, and projected CRS inputs.

## Prerequisites

- Python 3.10+
- `pip install -r requirements.txt`

## Scripts

| File | Purpose |
|------|---------|
| `scripts/convert.py` | Convert a NetCDF variable to COG with configurable compression |
| `scripts/validate.py` | Validate that a COG preserves all data from the source NetCDF |
| `scripts/reproject.py` | Shared module: reproject to EPSG:4326 via gdalwarp or rasterio |

## Quickstart

```bash
pip install xarray netcdf4 rasterio rio-cogeo numpy pyproj
python scripts/convert.py --input data.nc --output data_cog.tif --variable temperature
python scripts/validate.py --input data.nc --output data_cog.tif --variable temperature
```

## CLI flags

### convert.py

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--input` | Yes | -- | Path to input .nc file |
| `--output` | Yes | -- | Path for output COG |
| `--variable` | No | first data var | NetCDF variable name to extract |
| `--time-index` | No | `0` | Timestep index for temporal variables |
| `--compression` | No | `DEFLATE` | Compression method: DEFLATE, ZSTD, or LZW |
| `--overwrite` | No | False | Overwrite output if it exists |
| `--verbose` | No | False | Print detailed progress |

### validate.py

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--input` | No | -- | Path to original NetCDF (omit for self-test) |
| `--output` | No | -- | Path to converted COG (omit for self-test) |
| `--variable` | No | first data var | NetCDF variable to validate against |
| `--time-index` | No | `0` | Timestep index to validate against |

When both `--input` and `--output` are omitted, runs a self-test with four synthetic datasets: geographic, geostationary, projected (Albers), and 0-360 longitude.

## Known complexity

- **Multi-variable NetCDFs:** Only one variable is extracted per conversion. If no `--variable` is specified, the first data variable is used.
- **Temporal dimensions:** Only one timestep is extracted per conversion. Use `--time-index` to select.
- **Geostationary projection:** Satellite files (GOES-R, Himawari, Meteosat) store x/y as scanning angles in radians. The converter automatically multiplies by `perspective_point_height` and reprojects. The `sweep_angle_axis` attribute is critical: GOES uses `x`, Meteosat uses `y`.
- **CF conventions:** Any projected CRS expressible in CF conventions is supported via `pyproj.CRS.from_cf()`.
- **Dimension naming:** Recognizes `lat`/`latitude`/`y` and `lon`/`longitude`/`x`. Non-standard names produce a clear error.
- **0-360 longitudes:** Automatically rewrapped to -180 to 180.
- **CRS reprojection:** Non-EPSG:4326 inputs are automatically reprojected. The `reproject.py` module uses `gdalwarp` when available and falls back to `rasterio.warp` otherwise.

## Known failure modes

- **NetCDF4 files report as HDF5 MIME type**: NetCDF4 is built on HDF5. `libmagic` reports their MIME type as `application/x-hdf5`, not `application/x-netcdf`. Any MIME-based format detection must whitelist both types.
- **Geostationary x/y not scaled to meters**: If scanning-angle coordinates are not multiplied by `perspective_point_height` before building the affine transform, the data appears as a tiny dot near (0,0). The converter handles this automatically.
- **Single-band float COGs need `rescale` for colormap rendering**: NetCDF-to-COG always produces single-band float32 output. Applying `colormap_name` without `rescale` causes titiler to return 500 ("arrays used as indices must be of integer type"). Fix: pass `rescale=min,max` alongside `colormap_name`. Use p2/p98 percentiles for a good visual range. The validate script reports recommended rescale values.

## Validation checks (8 core + 1 advisory)

| Check | Pass condition |
|---|---|
| COG structure | `rio-cogeo` validate returns valid |
| CRS present | EPSG:4326 defined |
| Bounds match | COG bounds contain NetCDF cell centers |
| Dimensions | Pixel width/height match NetCDF grid |
| Band count | Exactly 1 band |
| Pixel fidelity | 1000 random samples, max diff < 1e-4 (geographic) or < 0.5 (reprojected) |
| NoData defined | nodata value is set |
| Overviews | >= 3 internal overview levels |
| Rendering metadata | Advisory: reports recommended rescale range for tile server colormap rendering |
