# Available Datasets

Use `datasetId` and `layerId` values exactly as listed below in `<Chapter>` and `<Map>` components.

**IMPORTANT:** Only use datasets that have configuration files in `app/content/datasets/` AND exist in OpenVEDA's STAC catalog. Datasets marked "NOT YET CONFIGURED" will cause CORS errors.

---

## NOT YET CONFIGURED: Black Marble Daily Nighttime Lights (VNP46A2)

- **datasetId**: `black-marble-vnp46a2`
- **Layers**:
  - `VNP46A2` — Daily gap-filled BRDF-corrected nightlights
- **Date range**: January 2012 - present, daily
- **Coverage**: Global, 500m resolution
- **What it shows**: Nighttime artificial light emissions for power outage and disaster recovery tracking
- **Status**: Collection does not exist in OpenVEDA STAC catalog. Requires NASA LAADS DAAC backend integration.
- **Workaround**: Use `nightlights-hd-monthly` (existing dataset, but monthly composites only)

## NOT YET CONFIGURED: Harmonized Landsat Sentinel-2 (HLS)

- **datasetId**: `hls`
- **Layers**:
  - `hls-l30-002-ej-reprocessed` — Landsat 30m surface reflectance
  - `hls-s30-002-ej-reprocessed` — Sentinel-2 30m surface reflectance
- **Date range**: 2013 - present (Landsat), 2015 - present (Sentinel-2), daily
- **Coverage**: Global, 30m resolution
- **What it shows**: True-color and false-color optical imagery showing land surface. Excellent for before/after disaster comparisons, landslide detection, urban damage assessment, vegetation change.
- **STAC Source**: `https://cmr.earthdata.nasa.gov/stac/LPCLOUD` (collections: HLSL30_2.0, HLSS30_2.0)
- **Best for earthquakes**: Before/after imagery showing collapsed buildings, landslides, road damage
- **Recommended zoom**: 10-14 for urban areas, 8-10 for regional views
- **Example bands**: Red, Green, Blue (true color), NIR (vegetation health), SWIR (moisture)

## NOT YET CONFIGURED: Black Marble Daily Nighttime Lights (VNP46A2)

- **datasetId**: `black-marble-vnp46a2`
- **Layers**:
  - `VNP46A2` — Daily gap-filled BRDF-corrected nightlights
- **Date range**: January 2012 - present, daily
- **Coverage**: Global, 500m resolution
- **What it shows**: Nighttime artificial light emissions. Dimming = power outages, infrastructure damage. Brightening = recovery, reconstruction.
- **Cover image**: `/images/dataset/nighttime-lights--dataset-cover.jpg`
- **STAC Source**: NASA LAADS DAAC
- **Best for earthquakes**: Detecting and tracking power outages, monitoring recovery over days/weeks
- **Recommended zoom**: 6-8 for city-scale, 4-5 for regional
- **Note**: Daily data allows tracking of power restoration timeline. Use compareDateTime for before/after views.

## NOT YET CONFIGURED: OPERA Dynamic Surface Water Extent (DSWx-HLS)

- **datasetId**: `opera-dswx`
- **Layers**:
  - `OPERA_L3_DSWX-HLS_V1` — Surface water extent from HLS
- **Date range**: 2022 - present
- **Coverage**: Global, 30m resolution
- **What it shows**: Water extent changes. Useful for tsunami inundation, dam/reservoir damage, flooding from infrastructure failure.
- **STAC Source**: `https://cmr.earthdata.nasa.gov/stac/POCLOUD`
- **Best for earthquakes**: Tsunami inundation mapping, landslide-dammed lakes

---

## Nitrogen Dioxide (NO2)

- **datasetId**: `no2`
- **Layers**:
  - `no2-monthly` — Global monthly NO2 concentrations (primary layer)
  - `no2-monthly-2` — Same data, bounded to US only
  - `no2-monthly-diff` — Month-over-month difference
- **Date range**: January 2000 - December 2021, monthly
- **Coverage**: Global, 1 km resolution
- **What it shows**: Air pollution from fossil fuel burning. Darker colors = higher NO2. Useful for COVID lockdown impact, industrial activity, transportation patterns.
- **Cover image**: `/images/dataset/no2--dataset-cover.jpg`
- **Legend colors**: light blue (#99c5e0) to dark purple (#050308)

## Sulfur Dioxide (SO2)

- **datasetId**: `so2`
- **Layers**:
  - `OMSO2PCA-COG` — Total column SO2
- **Date range**: 2005 - 2021, annual
- **Coverage**: Global, 30 km resolution
- **What it shows**: Industrial emissions, volcanic activity. Yellow = high SO2, purple = low.
- **Cover image**: `/images/dataset/so2--dataset-cover.jpg`
- **Example center/zoom**: India `[77.63, 24.27]` zoom 4, China `[117.22, 35.66]` zoom 4

## GPM IMERG Daily Precipitation

- **datasetId**: `GPM-3IMERGDF`
- **Layers**:
  - `GPM_3IMERGDF.v07` — Daily accumulated precipitation (CMR type)
- **Date range**: 2000 - 2024, daily
- **Coverage**: Global, 0.1 degree resolution (~11km at equator)
- **What it shows**: Rainfall and precipitation. Blue/green gradient, darker = more rain. Good for storms, hurricanes, drought, flooding.
- **Cover image**: `/images/dataset/gpmimergdaily.png`
- **Important**: This is a CMR-backed dataset. It works in the app but won't appear in STAC API searches. Use known event dates confidently.
- **Recommended zoom**: 3-4 for watersheds/regions, 5 for large countries. DO NOT use zoom 6+ (will look pixelated).
- **Example center/zoom**: Victoria Falls watershed `[25.86, -17.92]` zoom 4, Houston Harvey `[-95.37, 29.76]` zoom 5

## Facebook Population Density

- **datasetId**: `facebook-population`
- **Layers**:
  - `facebook_population_density` — High-resolution population density
- **Date range**: 2015 (single year)
- **Coverage**: Global, 30m resolution
- **What it shows**: Where people live. Red = high density. Great for urban/rural analysis, wildland-urban interface, socioeconomic stories.
- **Cover image**: `/images/dataset/facebook-population--dataset-cover.png`
- **Example center/zoom**: New York `[-74.006, 40.7128]` zoom 10

## Nighttime Lights

- **datasetId**: `nighttime-lights`
- **Layers**:
  - `nightlights-hd-monthly` — Black Marble HD nightlights
- **Date range**: Varies by location
- **Coverage**: Select metro areas only (NOT continuous global coverage)
- **What it shows**: Light emissions at night. Bright = more human activity/energy use. Good for disaster impact (blackouts), urbanization, energy access.
- **Cover image**: `/images/dataset/nighttime-lights--dataset-cover.jpg`
- **Warning**: HD nightlights only covers specific metros. Zooming out to regional views may show empty tiles. Verify coverage before using.

## National Land Cover Database (NLCD)

- **datasetId**: `nlcd-annual-conus`
- **Layers**:
  - `nlcd-annual-conus` — Land use/land cover classifications
  - `nlcd-new-urbanization` — New urbanization layer
- **Date range**: 2001 - 2021, annual
- **Coverage**: CONUS (Continental US) only, 30m resolution
- **What it shows**: Land cover types (forest, urban, water, agriculture, etc.). Color-coded by category. Great for deforestation, urbanization, wildfire recovery, before/after comparisons.
- **Cover image**: `/images/dataset/nlcd--dataset-cover.jpg`
- **Important**: US-only. Do not use for non-US locations.

## MTBS Burn Severity

- **datasetId**: `mtbs-burn-severity`
- **Layers**:
  - `mtbs-burn-severity` — Burn severity classifications
- **Date range**: 2016 - 2021
- **Coverage**: CONUS (Continental US), categorical data
- **What it shows**: Wildfire burn scars. Categories from unburned to high severity (dark red = total destruction). Essential for wildfire stories.
- **Cover image**: `/images/dataset/mtbs_burn_severity.thumbnail.jpg`
- **Important**: US-only. Categorical data (not continuous gradient).

## GEOGLAM Crop Conditions

- **datasetId**: `geoglam`
- **Layers**:
  - `geoglam` — Crop condition monitoring
- **Date range**: Monthly (ongoing)
- **Coverage**: Global agricultural regions
- **What it shows**: Crop health and conditions worldwide. Used for food security monitoring, agricultural stories.
- **Cover image**: `/images/dataset/geoglam--dataset-cover.jpg`

## OCI/PACE Chlorophyll-a

- **datasetId**: `OCI-PACE-Chlorophyll-a`
- **Layers**:
  - `OCI_PACE_Chlorophyll_a` — Ocean chlorophyll concentration (WMTS type)
- **Date range**: Recent observations
- **Coverage**: Global oceans
- **What it shows**: Ocean biological productivity. Higher chlorophyll = more phytoplankton activity. Good for ocean health, marine biology, algal blooms.
- **Note**: Uses WMTS tile service from dev.openveda.cloud, not standard STAC.

## GEDI Aboveground Biomass

- **datasetId**: `gedi-agb-grid-v2.1`
- **Layers**:
  - `GEDI_ISS_L4B_Aboveground_Biomass_Density_Mean_201904-202303` — Biomass density (WMTS type)
- **Date range**: April 2019 - March 2023
- **Coverage**: Global (between 51.6N and 51.6S latitude)
- **What it shows**: Forest biomass density from space-based lidar. Good for carbon storage, deforestation, forest health stories.

## Landsat MSS

- **datasetId**: `landsat-mss`
- **Layers**:
  - `landsat-mss-l1` — Multispectral Scanner imagery
- **Date range**: 1972 - 2013 (historical)
- **Coverage**: Global
- **What it shows**: Historical satellite imagery from the earliest Landsat missions. Good for long-term change detection stories.
- **Note**: Older data may be in cold storage. Verify specific dates are accessible.
- **Initial datetime**: 1980-05-18

---

## Dataset Selection Guide for Disasters

| Disaster Type | Primary Dataset | Secondary Dataset | What to Show |
|---------------|-----------------|-------------------|--------------||
| **Earthquake** | HLS (before/after) | Black Marble Daily | Structural damage, landslides, power outages |
| **Tsunami** | DSWx-HLS | HLS | Inundation extent, coastal damage |
| **Hurricane** | GPM IMERG | HLS, Black Marble | Rainfall, flooding, wind damage, power outages |
| **Wildfire** | MTBS Burn Severity | HLS, NLCD | Burn area, vegetation loss |
| **Flood** | GPM IMERG | DSWx-HLS | Precipitation, water extent |
| **Volcanic** | SO2 | HLS | Emissions plume, lava flows |

---

## STAC API Endpoints

For programmatic access to these datasets:

- **OpenVEDA STAC**: `https://openveda.cloud/api/stac/`
- **NASA CMR-STAC (HLS)**: `https://cmr.earthdata.nasa.gov/stac/LPCLOUD`
- **NASA CMR-STAC (OPERA)**: `https://cmr.earthdata.nasa.gov/stac/POCLOUD`
- **NASA CMR-STAC (GPM)**: `https://cmr.earthdata.nasa.gov/stac/GES_DISC`

---

## Available Cover Images

When creating a story, `media.src` must point to an existing image. These are available:

**Dataset images** (`/images/dataset/`):
- `no2--dataset-cover.jpg` — Power plant with emissions
- `so2--dataset-cover.jpg` — SO2 map visualization
- `gpmimergdaily.png` — Precipitation map
- `facebook-population--dataset-cover.png` — Population density
- `nighttime-lights--dataset-cover.jpg` — Earth at night
- `nlcd--dataset-cover.jpg` — Land cover classification
- `mtbs_burn_severity.thumbnail.jpg` — Burn severity map
- `geoglam--dataset-cover.jpg` — Crop conditions
- `fire--dataset-cover.jpg` — Wildfire imagery

**Story images** (`/images/story/`):
- `air-quality-and-covid-19--discovery-cover.jpg`
- `no2-so2-cover.jpg`
- `sat-data-agriculture--discovery-cover.jpg`
- `tallest_waves_cover.png`
- `lahaina-fire-background.jpg`

## Available Chart Data

Only one CSV exists in `public/charts/story/`:
- `no2-and-so2-charts.csv` — NO2 and SO2 changes from 2005 baseline for US, China, India (2005-2021)
  - Columns: `Year`, `Data Type`, `United States Change from 2005`, `China Change from 2005`, `India Change from 2005`
  - Data Types: `Nitrogen Dioxide`, `Sulfur Dioxide`
