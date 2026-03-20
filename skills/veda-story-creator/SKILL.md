---
name: veda-story-creator
description: Generates VEDA scrollytelling story MDX files with satellite data visualizations. Use when the user wants to create a new data story, write a story about an earth science topic, or generate an MDX file for the stories directory.
---

# VEDA Story Generator

Create a single `.mdx` file and place it in `app/content/stories/<slug>.mdx`. The slug is the filename without extension and must match the `id` field in the frontmatter.

## Frontmatter Schema

Every story MUST use this exact format. Using `title` or `summary` instead of `name`/`description` will cause a 404.

```yaml
---
id: my-story-slug
name: Human Readable Story Title
description: "A one-sentence summary of the story. Must be quoted."
media:
  src: /images/dataset/no2--dataset-cover.jpg
  alt: Description of the cover image
  author:
    name: Source Name
    url: https://source-url.com
pubDate: 2026-01-28
taxonomy:
  - name: Topics
    values:
      - Topic One
      - Topic Two
---
```

**Critical rules:**
- `id` must match the filename slug exactly
- `description` must be a quoted string
- `media.src` must reference an existing image. Use one from `public/images/dataset/` or `public/images/story/`. Run `ls public/images/dataset/` to see available images.
- `pubDate` uses `YYYY-MM-DD` format

## Disaster Response Datasets (Future)

**IMPORTANT:** Specialized disaster-response datasets are documented but **require backend integration** before they can be used:

- **Black Marble Daily (VNP46A2)**: 500m daily nighttime lights - requires NASA LAADS DAAC integration
- **HLS (Harmonized Landsat Sentinel-2)**: 30m optical imagery - requires NASA CMR-STAC integration
- **OPERA DSWx-HLS**: 30m water extent - requires NASA CMR-STAC integration

These datasets don't exist in OpenVEDA's STAC catalog yet. Adding them requires platform-level backend configuration, CORS policies, and tile service setup.

**Workaround for disaster stories**: Use existing datasets:
- **nightlights-hd-monthly** for power outage tracking (monthly composites, not daily)
- **GPM-3IMERGDF** for precipitation and flooding
- **facebook-population** for impact assessment

To verify if a dataset is available: `curl -s "https://openveda.cloud/api/stac/collections?limit=250" | jq -r '.collections[].id' | grep {dataset-name}`

## Available Components

### Layout
- `<Block>` — Full-width content container. Wraps `<Prose>` and/or `<Figure>`.
- `<Prose>` — Text content wrapper. All markdown text must be inside `<Prose>`.

### Scrollytelling
```jsx
<ScrollytellingBlock>
  <Chapter
    center={[longitude, latitude]}
    zoom={6}
    datasetId='no2'
    layerId='no2-monthly'
    datetime='2020-03-01'
  >
    ## Chapter Title
    Narrative text for this map view.
  </Chapter>
</ScrollytellingBlock>
```

**Chapter props:**
- `center`: `[longitude, latitude]` array (note: longitude first)
- `zoom`: integer 1-18 — **CRITICAL: Match zoom to data resolution**
  - **GPM precipitation (0.1° res)**: zoom 3-4 for watersheds/regions, 5 for large countries
  - **NO2/SO2 (1-30km res)**: zoom 4-6 for regions, 7-8 for cities
  - **Population/NLCD (30m res)**: zoom 8-10 for cities, 11-12 for neighborhoods
  - **Rule**: If data looks pixelated, zoom OUT 2 levels
- `datasetId`: must match a dataset `id` from the datasets catalog
- `layerId`: must match a layer `id` from that dataset
- `datetime`: `'YYYY-MM-DD'` string within the dataset's date range

### Maps (standalone, outside scrollytelling)
```jsx
<Figure>
  <Map
    datasetId='so2'
    layerId='OMSO2PCA-COG'
    dateTime='2006-01-01'
    zoom={4}
    center={[117.22, 35.66]}
    compareDateTime='2021-01-01'
  />
  <Caption attrAuthor='NASA' attrUrl='https://nasa.gov/'>
    Description of what the map shows.
  </Caption>
</Figure>
```

Use `compareDateTime` to create a before/after slider comparison.

### Charts
```jsx
<Figure>
  <Chart
    dataPath="/charts/story/no2-and-so2-charts.csv"
    dateFormat="%Y"
    idKey='Data Type'
    xKey='Year'
    yKey='China Change from 2005'
  />
  <Caption>Chart description.</Caption>
</Figure>
```

Only use Chart if CSV data already exists in `public/charts/`. Check with `ls public/charts/story/`.

### Innovation Components

**StatCard** — Highlight a key statistic:
```jsx
<StatCard
  value="-30%"
  label="Average NO2 Drop"
  trend="Global Decrease in April 2020"
  trendColor="green"
/>
```
Props: `value` (string), `label` (string), `trend` (optional string), `trendColor` (optional: "green" or omit)

**Quote** — Block quote with attribution:
```jsx
<Quote author="Dr. Jane Smith" role="NASA Scientist">
  Quoted text goes here without extra quotes.
</Quote>
```

**SimpleTable** — Data table:
```jsx
<SimpleTable
  data={{
    headers: ["Region", "Change", "Source"],
    rows: [
      ["City A", "-50%", "Transportation"],
      ["City B", "-30%", "Industry"]
    ]
  }}
/>
```

## Recommended Story Structure

```
1. Intro Block (Block > Prose)
   - Set the scene, provide context
   - Optionally include a StatCard for a key number

2. ScrollytellingBlock (3-6 Chapters)
   - Each chapter reveals a new aspect of the data
   - Lock zoom/center when comparing the same area across time
   - Change location only when shifting to a new geographic subject

3. Analysis Block(s) (Block > Prose + Figure)
   - Deeper analysis with maps, charts, or tables
   - Use Map with compareDateTime for before/after comparisons
   - Use Quote for expert perspectives
   - Use SimpleTable for structured data

4. Conclusion Block (Block > Prose)
   - Summarize findings
   - Connect data to real-world implications
```

## Critical Rules

1. **Filmstrip pattern**: When showing temporal change in the same area, keep `center` and `zoom` identical across chapters. Only the `datetime` should change.

2. **Zoom for scale**: Match zoom level to data resolution. Coarse-resolution data (GPM 0.1°, NO2/SO2 1-30km) needs low zoom (3-5). High-resolution data (population, NLCD 30m) can use high zoom (8-12). **If data looks pixelated or blocky, zoom OUT by 2 levels.**

3. **Data interpretation**: In the first chapter of a scrollytelling sequence, explicitly state what the colors/values mean: "Dark red indicates high NO2 concentration."

4. **Date ranges matter**: Each dataset has specific temporal coverage. Check [datasets.md](datasets.md) before using a datetime. Using a date outside the range will show a blank map.

5. **Coverage gaps**: Some datasets only cover specific regions. `nlcd-annual-conus` is US-only. `nightlights-hd-monthly` only covers select metro areas at HD resolution.

6. **No Tailwind CSS**: This project uses `styled-components`. Utility classes like `text-red-500` will have no effect.

7. **CMR datasets**: `GPM-3IMERGDF` uses NASA's CMR backend, not standard STAC. It works in the app but won't appear in STAC API searches.

8. **Dataset availability**: Just because a dataset is documented doesn't mean it's configured. Run `ls app/content/datasets/` to verify a dataset MDX file exists before using it in a story. If the file doesn't exist, the app will crash with `Layer [X] not found in dataset [Y]`.

## Reference Files

- **[datasets.md](datasets.md)**: Complete catalog of all available datasets, layer IDs, date ranges, and coverage notes
- **[examples.md](examples.md)**: Annotated working story showing all components in use
- **[lessons.md](lessons.md)**: Critical lessons learned from real story development - read this first to avoid common pitfalls

## Packaging for Claude

To zip this skill for upload, run this from the root of the repository:

```bash
zip -r veda-story-creator.zip veda-story-creator/ -x "*/.venv/*" "*/output/*" "*/input/*" "*/.env" "*/__pycache__/*" "*/.DS_Store"
```
