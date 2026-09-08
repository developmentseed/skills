---
name: cloud-native-geo
description: Helps choose and use cloud-native geospatial formats and tools — COG, STAC, Zarr/Icechunk/GeoZarr, GeoParquet, PMTiles, FlatGeobuf — plus the Python/JS stack for reading, writing, serving, and visualizing them (titiler, rio-tiler, obstore, pgstac, eoAPI, deck.gl-raster, lonboard). Use when a user wants to store, publish, tile-serve, query, or visualize satellite imagery, raster/vector geospatial data, or build a geospatial app, and when picking a format or library for that job. This is a fast-moving niche space — the skill points to live docs instead of memorized API details for the newest tools.
---

# Cloud-native geospatial

Helps pick the right cloud-native format and tool for a geospatial data job, and use it with today's APIs rather than stale, memorized ones. Covers both **producing** data (converting/writing into a cloud-native format) and **consuming** it (reading, serving, querying, visualizing).

This space moves fast — several of the libraries recommended here are under two years old and change their APIs between releases. Two rules make this skill reliable instead of guessy:

1. **Ask before recommending, if the request is vague.** "Help me store some satellite data" or "how do I visualize this raster" doesn't have one right answer.
2. **Verify before writing code, for fast-moving libraries.** Don't generate code for obstore, titiler/rio-tiler, deck.gl-raster, icechunk, virtualizarr, or rustac from memory — fetch the current docs first (table below).

## Ask before recommending

Before picking a format or library, get enough to place the request on these four axes. Two or three quick questions beat a wrong-but-confident answer:

- **Data shape** — one raster/scene? A time series or multi-band datacube? Millions of small vector features (points/lines/polygons)? A point cloud?
- **Access pattern** — written once and served read-only to many clients? Or updated/appended by multiple concurrent writers over time?
- **Where it runs** — does this need a backend tile/API service, or should it work fully client-side (browser/Jupyter) with no server?
- **Existing infrastructure** — is there already a STAC catalog, a Postgres database, an object-storage bucket (S3/GCS/Azure) this should plug into?

Example: a user says "I need to visualize this raster on a map." Don't default to spinning up a tile server — ask whether the raster is already a COG, whether they want this to run without a backend (→ deck.gl-raster can render a COG straight from a bucket URL, no server), and roughly how big it is. The answer changes the recommendation from `references/visualization.md` vs. `references/python-stack.md`.

Skip the questions when the request is already specific enough to place on all four axes (e.g. "convert this Sentinel-2 GeoTIFF to a COG and serve it with titiler-pgstac from our existing pgSTAC database").

## Decision guide

| Need | Reach for |
|---|---|
| Serve a single raster (scene, DEM, orthomosaic) efficiently | **COG** — via titiler/rio-tiler (server) or deck.gl-raster (client-side, no server) |
| Time series / multi-band datacube (climate, model output, stacked imagery) | **Zarr**, +**Icechunk** for transactional/versioned writes, +**GeoZarr** conventions so it's georeferenced, +**VirtualiZarr/Kerchunk** to wrap existing NetCDF/HDF5/GRIB archives without rewriting them |
| Millions of points/lines/polygons for analytics | **GeoParquet** + DuckDB (spatial extension) or geopandas |
| Serve pre-rendered tiles (vector or raster) globally with no tile server | **PMTiles** |
| Stream or client-side-render one big vector dataset | **FlatGeobuf** |
| Catalog and discover assets across a collection | **STAC** — dynamic API backed by pgstac/eoAPI for large, frequently-updated catalogs; static STAC + STAC-GeoParquet for smaller or serverless ones |
| Mosaic many COGs across zoom levels (e.g. a basemap from thousands of scenes) | **MosaicJSON** + cogeo-mosaic + titiler |
| Point cloud (LiDAR, photogrammetry) | **COPC** |
| Visualize in-browser or in Jupyter with no backend | **deck.gl-raster** (raster/Zarr/GeoZarr) or **lonboard** (vector, GeoParquet-native, Jupyter) or MapLibre GL JS + the PMTiles plugin (tiles) |

Full primers, gotchas, and "why this instead of that" reasoning per format: [references/formats.md](references/formats.md).

## Reading, writing, serving, and querying: the tool stack

Development Seed builds or maintains most of the reference implementations in this space, so it's the default stack here (alternatives are noted where they matter):

- **Server/data-side Python** (object storage access, raster tiling, STAC backends, STAC data tooling): [references/python-stack.md](references/python-stack.md)
- **Client-side / notebook visualization** (GPU-rendered raster/Zarr in the browser, GeoParquet-native map viz, STAC browsing): [references/visualization.md](references/visualization.md)

If the task is a narrow **format conversion** (e.g. GeoTIFF → COG, NetCDF → COG, GeoJSON/Shapefile → GeoParquet) rather than choosing/using a format, check for a dedicated conversion skill in this repo first — those carry GDAL-flag-level detail and validation scripts this skill doesn't duplicate.

## Verify before writing code

These libraries are young or restructure often enough that memorized snippets are a real risk. Before generating code against one of them, `WebFetch` its docs (or the relevant page) to confirm current function names, package layout, and required arguments:

| Library | Why it's risky to guess | Docs |
|---|---|---|
| **titiler** / **rio-tiler** | titiler split into namespace packages (`titiler.core`, `titiler.mosaic`, `titiler.xarray`, ...); rio-tiler is on a 9.x major line with breaking changes between majors | https://developmentseed.org/titiler/ |
| **obstore** | New (2025), Rust-backed, API still settling | https://developmentseed.org/obstore/latest/ |
| **deck.gl-raster** | New (2026), `ZarrLayer`/GeoZarr support actively expanding | https://developmentseed.org/deck.gl-raster/ |
| **icechunk** | New (2024), transactional API for Zarr still evolving | https://icechunk.io/en/latest/ |
| **virtualizarr** | Kerchunk-derived, API and `.to_icechunk()` semantics still moving | https://virtualizarr.readthedocs.io/ |
| **rustac** | Rust STAC library w/ Python bindings, young and fast-releasing | https://stac-utils.github.io/rustac-py/ |
| **GeoZarr spec** | Not yet a finalized OGC standard (targeting Architecture Board review 2026) — conventions can still shift | https://geozarr.org/ |

For everything else tracked by this skill (with the exact package name and registry used to check for updates), see [references/tracked-sources.yaml](references/tracked-sources.yaml) — a scheduled job in this repo checks that list weekly and flags anything that's shipped a new release since it was last reviewed.

## Requirements

No setup needed to use this skill's guidance. Following its code recommendations requires whatever the chosen library needs (e.g. `pip install`/`uv add` the relevant Python package, or GDAL for some conversions) — call that out per-task rather than assuming a fixed environment.
