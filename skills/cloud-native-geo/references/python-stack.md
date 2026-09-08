# The Python stack: storage, tiling, and STAC backends

Development Seed builds or maintains most of these — they're the default choice here, grouped by what problem they solve. Package names and APIs move fast; check the SKILL.md verify-before-coding table before writing code against the ones flagged there.

## Object storage access

**obstore** — a fast, Rust-backed Python client for S3, GCS, and Azure Blob Storage. The default choice for reading/writing cloud object storage from Python now; meaningfully faster than fsspec/boto3-based access for many concurrent small reads (the common pattern when range-reading COGs/Zarr/GeoParquet chunks). Exposes an fsspec-compatible surface so it drops into tools expecting fsspec (e.g. PyArrow). `rustac` (below) can use any `obstore.store.ObjectStore`, or its own zero-dependency store implementation.

**When to reach for something else:** if a tool you're integrating with only accepts `fsspec`/`s3fs`/`gcsfs` and can't take an obstore-backed filesystem, fall back to those — but prefer obstore when you control the read path.

## Raster tiling

**rio-tiler** — the core raster-reading library: given a COG (or, via its `XarrayReader`, anything xarray can open — Zarr, NetCDF, HDF5) it produces tiles, statistics, and previews. Most raster tooling in this stack (titiler included) is built on it.

**titiler** — a FastAPI-based framework for building dynamic tile servers. Not one package: it's a set of namespace packages —
- `titiler.core` — base tile/statistics/info endpoints for COGs
- `titiler.mosaic` — MosaicJSON-based mosaic tiling (pairs with cogeo-mosaic)
- `titiler.extensions` — optional add-ons (e.g. STAC render extensions)
- `titiler.xarray` — Zarr/NetCDF/multi-dimensional tiling via rio-tiler's `XarrayReader`
- `titiler-pgstac` — connects to a **pgstac** database to do large-scale dynamic mosaic tiling directly over a STAC collection (query STAC, tile the matching items, no separate mosaic-build step)
- `titiler-multidim` is a reference *application* built from `titiler.xarray`, not a package to import

Pick namespace packages individually rather than assuming a single `titiler` install gives you everything — this split happened relatively recently and older guidance (including older training data) may still describe a monolithic package.

**cogeo-mosaic** — creates and reads MosaicJSON files describing which COGs cover which tiles at which zoom levels; the data-prep counterpart to `titiler.mosaic`.

**morecantile** — construct and use OGC TileMatrixSets (tiling grids) beyond plain Web Mercator, for when a project needs a different projection's tile grid.

## STAC backends (dynamic APIs)

**pgstac** — a Postgres schema + functions purpose-built for STAC search at scale (this is *not* just "STAC items in a generic Postgres table" — it has custom indexes and query functions for STAC's search semantics).

**stac-fastapi** / **stac-fastapi-pgstac** — the STAC API (FastAPI) implementation that sits in front of pgstac and speaks the STAC API spec (search, collections, items, CQL2 filtering).

**stac-fastapi-geoparquet** — an alternative backend implementing the same STAC API surface but reading from GeoParquet + DuckDB instead of Postgres — no database to run, good fit for smaller or read-heavy catalogs (see the STAC section of [formats.md](formats.md) for the tradeoff).

**tipg** — a simple, fast OGC API - Features and Tiles server directly over PostGIS, for when the need is a generic OGC Features/Tiles API rather than STAC search specifically.

**eoAPI** — the bundle: brings pgstac + stac-fastapi-pgstac + titiler-pgstac + tipg together into one deployable Earth-observation API stack (metadata search, dynamic raster tiling, and vector OGC API in one deployment). The pragmatic starting point when the requirement is "give me a production STAC + tiling backend," rather than assembling the pieces individually.

## STAC data tooling (not APIs — reading/writing/generating STAC data itself)

**rustac** — a fast Rust STAC library with Python bindings; reads/writes STAC items/catalogs, integrates with DuckDB for STAC-GeoParquet queries, and can use obstore (or its own built-in store) for object-storage access. Young and fast-releasing — verify current API before generating code.

**stactools** — a CLI/library framework for building STAC-metadata generators for specific dataset types (each supported dataset gets a `stactools-packages` plugin that knows how to turn that data into correct STAC items).

**stac-geoparquet** — converts between STAC items (JSON) and STAC-GeoParquet; the library counterpart to the STAC-GeoParquet spec described in [formats.md](formats.md).

## Typed models

**geojson-pydantic** — Pydantic models for the GeoJSON spec; use for validating/typing GeoJSON payloads in Python code (e.g. FastAPI request/response models) rather than hand-rolling dict validation.

## Querying GeoParquet / STAC-GeoParquet

**DuckDB** (with its `spatial` extension loaded) is the standard engine for querying GeoParquet and STAC-GeoParquet files directly — spatial predicates (`ST_Intersects`, etc.), column pruning, and predicate pushdown against files in object storage, no server or database to run. `rustac` also wraps DuckDB specifically for STAC-GeoParquet queries. For row-by-row Python-native work instead of SQL, geopandas reads GeoParquet natively too.
