# Visualization: client-side and notebook tools

The newest part of this stack: rendering cloud-native rasters and vectors directly in the browser or a notebook, streaming chunks from object storage on demand — often with **no tile server or backend at all**. Prefer these when "where it runs" (see SKILL.md's ask-before-recommending questions) points to client-side/serverless.

## deck.gl-raster (Development Seed)

**What it does:** client-side, GPU-driven (WebGL2, via deck.gl + luma.gl) rendering of COGs and Zarr/GeoZarr datasets. It figures out which chunks intersect the current map viewport, fetches and decodes only those, and composites/reprojects them on the GPU — all in the browser, streaming straight from object storage.

**Reach for it when:** you want interactive raster or datacube visualization on a map without standing up titiler or any tile-serving backend — the client talks directly to the bucket.

**Zarr specifics:** its `ZarrLayer` requires an explicit selection (a Zarrita-style index/slice) for every non-spatial dimension — Zarr arrays can have arbitrary extra dimensions (time, band, ensemble member, ...) and the layer needs to be told which slice of those to render, it won't guess.

**Verify before coding:** new (2026) and actively adding GeoZarr support — check https://developmentseed.org/deck.gl-raster/ for current API before writing `ZarrLayer` code.

## lonboard (Development Seed)

**What it does:** fast, WebGL-based *vector* visualization in Jupyter notebooks — GeoParquet-native, handles millions of features at interactive framerates by avoiding GeoJSON's per-feature Python object overhead.

**Reach for it when:** exploring/visualizing a large vector dataset (points/lines/polygons) from a notebook, especially one already in or convertible to GeoParquet.

## stac-map (Development Seed)

**What it does:** a map-first STAC search and visualization tool with stac-geoparquet support — browse/query a STAC catalog and see results on a map rather than working through raw JSON responses.

**Reach for it when:** exploring what's in a STAC catalog, or building a lightweight STAC browsing UI.

## MapLibre GL JS + PMTiles

**What it does:** the standard open-source (non-DevSeed) vector/raster tile renderer for the web. Combined with the `pmtiles` protocol plugin, it reads PMTiles files directly (from object storage or a CDN) with no tile server in between.

**Reach for it when:** the data is already tiled (PMTiles, or a conventional XYZ/vector tile endpoint) rather than raw COG/Zarr that needs on-the-fly rendering — that's deck.gl-raster's job instead.

## Where cloud-native data actually lives

**Source Cooperative** (built and governed by Radiant Earth) — an S3-compatible open data publishing platform hosting a large and growing amount of cloud-native geospatial data (COG, GeoParquet, PMTiles, etc.) at the petabyte scale. Useful both as a place to publish output and as a source of real example datasets/URLs when testing these tools.

**Cloud-Native Geospatial Forum's Cloud-Optimized Geospatial Formats Guide** (guide.cloudnativegeo.org, co-led by NASA IMPACT and Development Seed) — the living, community-maintained reference for these formats, with runnable notebook examples. Treat it as the canonical source to check when this skill's format primers need a deeper worked example than [formats.md](formats.md) provides.
