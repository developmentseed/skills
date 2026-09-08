# Cloud-native geospatial formats

What problem each format solves, when to reach for it, and the gotchas that actually bite. "Cloud-native" here means: data sits in object storage (S3/GCS/Azure) and clients fetch only the bytes they need via HTTP range requests — no need to download a whole file or run a bespoke server just to read a small piece of it.

## COG — Cloud-Optimized GeoTIFF

**Problem it solves:** efficient partial reads of a single raster (one scene, one DEM, one band-stack) straight from object storage — internal tiling + overviews mean a client can fetch just the pixels/zoom level it needs.

**Reach for it when:** you have one raster (not a time series) that needs to be tiled, previewed, or analyzed without downloading the whole file.

**Gotchas:**
- Don't write COGs with plain `rasterio.open()` — tiled GeoTIFFs with overviews written that way get invalid IFD ordering. Use `gdal_translate -of COG` or `rio-cogeo`'s `cog_translate`.
- COGs in a projected CRS have bounds in meters, not degrees. STAC requires WGS84 bounding boxes — reproject bounds with `rasterio.warp.transform_bounds(src.crs, "EPSG:4326", *src.bounds)` before writing STAC metadata, or tile servers will silently return empty (204) tiles because the item bbox never intersects a web-mercator tile.
- Polar CRS (e.g. EPSG:3413) can produce `south=-90`/`north=90` after that reprojection — Web Mercator is undefined at the poles, and feeding those bounds into `WebMercatorViewport.fitBounds` (deck.gl) produces NaN and a silently blank map. Clamp to ±85.051129° first.
- Colormaps only apply to single-band data — applying one to a multi-band COG returns HTTP 500 from titiler. Single-band non-byte (float32/int16) rasters also need an explicit `rescale=min,max` alongside the colormap, or indexing into the colormap fails.

## STAC — SpatioTemporal Asset Catalog

**Problem it solves:** a common JSON metadata schema (+ API) for *discovering* geospatial assets — what exists, where, when, with what properties — independent of how the underlying data is stored.

**Reach for it when:** you have more than a handful of assets and need search/filter/discovery (by bbox, date range, collection, custom properties) rather than a fixed list of file paths.

**Two deployment shapes:**
- **Dynamic STAC API** — a real API (search, paging, CQL2 filters) backed by a database. DevSeed's stack: **pgstac** (Postgres schema + functions) behind **stac-fastapi-pgstac**, usually bundled via **eoAPI**. Scales to huge, frequently-updated catalogs (eoAPI deployments manage 1B+ items).
- **Static STAC + STAC-GeoParquet** — no API server; the catalog is just files (or one GeoParquet file) in object storage, queried with DuckDB or read directly. Cheaper to run, great for read-heavy or smaller/less-frequently-updated catalogs; **stac-fastapi-geoparquet** gives you an API-shaped interface over the same data without a database. For catalogs under ~100k items, geoparquet-backed search is often faster than a database round-trip for broad/paginated queries; a live database still wins for single-item lookups and high write-concurrency.

**Gotcha:** don't assume "STAC API" means Postgres — check which of the two shapes a given catalog actually is before writing query code against it.

## GeoParquet / STAC-GeoParquet

**Problem it solves:** columnar, cloud-native storage for *vector* data (points/lines/polygons + attributes), built on Apache Parquet — so it plugs straight into the Arrow/DuckDB/pandas analytics ecosystem instead of needing a database or a slow row-oriented format like GeoJSON/Shapefile.

**Reach for it when:** you have a large table of vector features you want to query, filter, or join at scale, not just render.

**STAC-GeoParquet** is the same idea applied to STAC metadata itself — a STAC collection's items encoded as GeoParquet rows instead of individual JSON files, so bulk catalog access becomes a columnar query instead of thousands of small HTTP requests.

**Gotcha:** GeoParquet is mid-transition as of 2026 — a 2.0 release candidate moves geometry storage from WKB-in-a-plain-`BYTE_ARRAY`-column (1.x) to Parquet's new native `Geometry`/`Geography` logical types, and is still pending OGC approval. Always check which version a file declares (its `geo` metadata key, or whether geometry columns use the new logical types) before assuming 1.x-style column encoding — reader code written against 1.x won't automatically understand 2.0 files.

## Zarr

**Problem it solves:** chunked, compressed, N-dimensional array storage — the right shape for datacubes (time × band × y × x), not single 2D rasters. Native to the Python scientific stack (`zarr-python`, `xarray`).

**Reach for it when:** the data has more than 2 spatial dimensions worth treating as one unit — a time series, an ensemble, a multi-band stack you want to slice arbitrarily.

**Gotcha:** plain Zarr has no built-in geospatial awareness (no CRS, no "this dimension is longitude") and no transactional guarantees for concurrent writers — see GeoZarr and Icechunk below, which each solve one half of that gap.

## Icechunk

**Problem it solves:** a transactional storage engine *on top of* Zarr — adds serializable-isolation transactions and git-like versioning, so Zarr data in object storage is safe to read and write from multiple uncoordinated processes. Built by Earthmover.

**Reach for it when:** more than one process/pipeline writes to the same Zarr store over time, or you want versioned/rollback-able datacube updates.

## GeoZarr

**Problem it solves:** the "what CRS, what spatial transform, what multiscale pyramid" gap in plain Zarr — modular conventions (each addresses one concern: CRS, transform, or multiscale pyramids) so georeferenced data in Zarr is interoperable across tools, the way COG's spec makes a GeoTIFF unambiguous. Developed by the OGC GeoZarr Standards Working Group; not yet a ratified OGC standard (targeting Architecture Board review in 2026), so check `../SKILL.md`'s verify-before-coding table for the current spec state before depending on exact key names.

**Reach for it when:** producing or consuming Zarr data that needs to be rendered on a map (as opposed to pure array analytics), e.g. as input to deck.gl-raster's `ZarrLayer`.

## VirtualiZarr / Kerchunk

**Problem it solves:** letting existing archival files (NetCDF, HDF5, GRIB) be read *as if* they were a Zarr store — by indexing byte ranges inside the original files instead of copying/rewriting the data — so huge legacy archives get Zarr/xarray-style chunked, cloud-native access without a costly rewrite.

**Reach for it when:** you have a large existing archive in NetCDF/HDF5/GRIB you want datacube-style access to, and rewriting it all as native Zarr isn't practical (cost, time, or you don't own the archive).

**Relationship:** VirtualiZarr grew out of Kerchunk, using an array-level "chunk manifest" representation instead of Kerchunk's JSON reference format; virtual references can be committed to Icechunk (`.to_icechunk()`) instead of/alongside the older Kerchunk reference spec.

## PMTiles

**Problem it solves:** a whole tile pyramid (vector or raster tiles) packed into a *single* file that's HTTP-range-readable — no tile server process needed at all, since the client fetches just the tiles it needs directly from the file in object storage or a CDN.

**Reach for it when:** you want production map tile serving (e.g. a basemap layer) without running or scaling a tile server. Pairs with MapLibre GL JS via the `pmtiles` protocol plugin.

**Compare to FlatGeobuf:** PMTiles serves pre-rendered tiles the client draws immediately; FlatGeobuf serves raw features the client still has to style/render itself. Pick PMTiles for "just show this on a map fast"; pick FlatGeobuf for "I need the actual geometries client-side to do something with them."

## FlatGeobuf

**Problem it solves:** a streamable binary vector format with a spatial index, readable incrementally over HTTP range requests — a cloud-native replacement for shipping a big GeoJSON or Shapefile.

**Reach for it when:** a client needs the actual feature geometries/attributes (not pre-rendered tiles) from a large vector dataset, streamed rather than downloaded whole.

## COPC — Cloud-Optimized Point Cloud

**Problem it solves:** COG's idea applied to point clouds — a single (compressed LAZ) file reorganized into a clustered octree instead of a flat point list, so clients can fetch just the points in their area/level of detail via range requests.

**Reach for it when:** working with LiDAR or photogrammetry point clouds that need partial/progressive access rather than a full download.

## MosaicJSON

**Problem it solves:** a DevSeed-authored spec describing which COG(s) cover which tile at which zoom level, so a tile server can serve a seamless mosaic assembled from many COGs (e.g. a global basemap from thousands of scenes) without pre-rendering one giant raster.

**Reach for it when:** you need to serve tiles from *many* COGs as one logical layer. Built and read with **cogeo-mosaic**; served with **titiler**'s mosaic package.
