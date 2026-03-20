# Lessons Learned: VEDA Story Creation

Critical lessons distilled from real story development. Read these before creating stories to avoid common pitfalls.

## Dataset Availability

### The "Documented ≠ Available" Trap
**Issue**: A dataset may be documented but not actually configured in the VEDA system.

**Symptom**: `Layer [X] not found in dataset [Y]` error even though documentation mentions it.

**Solution**:
- Always check datasets.md and/or existing configuration files
- Datasets marked "NOT YET CONFIGURED" in datasets.md will cause errors

### External STAC Integration Limitations
**Issue**: Creating a dataset MDX file doesn't automatically make external STAC data available.

**Example**: Black Marble Daily (VNP46A2) causes CORS error because the collection doesn't exist in OpenVEDA's STAC catalog.

**Solution**:
- Verify collection exists: `curl "https://openveda.cloud/api/stac/collections?limit=250" | jq -r '.collections[].id' | grep {name}`
- Only use collections that exist in OpenVEDA's catalog (247 currently available)
- External sources require platform-level backend integration

## Frontmatter Schema

### Strict Schema Enforcement
**Issue**: Using wrong frontmatter field names causes 404 errors or server crashes.

**Common mistake**: Using `title`/`summary` instead of required `id`/`name`/`description`.

**Solution**:
- Always use: `id`, `name`, `description` (not `title`, `summary`)
- `description` must be a quoted string
- Copy from a working story to start

## Dataset-Specific Quirks

### The "Global" Dataset Fallacy
**Issue**: Some datasets labeled "Global" are actually sparse mosaics.

**Example**: `nightlights-hd-monthly` only covers specific metro areas, not continuous global coverage.

**Solution**:
- Check coverage notes in datasets.md
- US-only datasets: `nlcd-annual-conus`, `mtbs-burn-severity`
- Metro-only: `nightlights-hd-monthly` (HD version)

### CMR vs STAC Search
**Issue**: CMR-backed datasets (like GPM) don't show up in STAC API searches.

**Example**: `GPM-3IMERGDF` returns 0 hits in STAC search but works perfectly in the app.

**Solution**:
- Check dataset type in MDX file
- If `type: cmr`, trust the documented date range
- Use known event dates confidently

### Zoom Levels & Resolution
**Issue**: Data looks pixelated or blocky at wrong zoom levels.

**Rule of thumb**:
- **GPM precipitation (0.1° res)**: zoom 3-4 for regions, max 5
- **NO2/SO2 (1-30km res)**: zoom 4-6 for regions, 7-8 for cities
- **Population/NLCD (30m res)**: zoom 8-12 for cities/neighborhoods

**Solution**: If data looks pixelated, zoom OUT by 2 levels.

## Visual Storytelling Patterns

### The "Filmstrip" Pattern
**Issue**: When showing temporal change, users need to see the data changing, not the map view changing.

**Solution**:
- Lock `center` and `zoom` to **identical** values across chapters
- Only change `datetime` parameter
- Excellent for tracking storms, recovery, seasonal changes

**Example**:
```jsx
// All chapters show Port Vila at same location/zoom, only time changes
<Chapter center={[168.32, -17.73]} zoom={7} datetime='2024-12-10'>
<Chapter center={[168.32, -17.73]} zoom={7} datetime='2024-12-17'>
<Chapter center={[168.32, -17.73]} zoom={7} datetime='2024-12-28'>
```

### Data Interpretation
**Issue**: Users don't know what colors mean.

**Solution**: In the first chapter, explicitly state: "Dark red indicates high NO2 concentration" or "Bright yellow = more nighttime lights."

### Context vs Resolution
**Issue**: Large-scale phenomena look pixelated at high zoom.

**Solution**: Zoom OUT to show the full system. A low-res hurricane spiral at zoom 3 tells a better story than pixelated blocks at zoom 8.

## Asset Management

### Image Paths Must Exist
**Issue**: `media.src` pointing to non-existent image causes broken UI.

**Solution**:
- Run `ls public/images/dataset/` and `ls public/images/story/`
- Use existing images from datasets.md "Available Cover Images" section
- Never guess image paths

### Chart Data Availability
**Issue**: Chart component requires CSV files that may not exist.

**Solution**:
- Run `ls public/charts/story/` to verify CSV exists
- Currently only one CSV available: `no2-and-so2-charts.csv`
- Don't create Chart components without verified data

## ScrollytellingBlock Chapter Formatting

### CRITICAL: Only ONE ScrollytellingBlock Per Story
**This is the #1 cause of `Cannot read properties of undefined (reading 'center')` errors.**

Multiple `<ScrollytellingBlock>` components on the same page cause scrollama index collisions. The scrollama library tracks DOM elements by index, and when multiple blocks exist, the indexes don't match the internal chapter data arrays.

**Symptom**: Map works initially, then crashes when scrolling to the second or third block with `TypeError: Cannot read properties of undefined (reading 'center')`.

**Bad MDX** (will crash):
```jsx
<ScrollytellingBlock>
  <Chapter ...>US chapters</Chapter>
</ScrollytellingBlock>
<Block>...prose...</Block>
<ScrollytellingBlock>   ← CRASH
  <Chapter ...>China chapters</Chapter>
</ScrollytellingBlock>
```

**Good MDX** (correct):
```jsx
<ScrollytellingBlock>
  <Chapter ...>US chapters</Chapter>
  <Chapter ...>China chapters</Chapter>  ← All in ONE block
  <Chapter ...>India chapters</Chapter>
</ScrollytellingBlock>
<Block>...prose after all scrollytelling...</Block>
```

**Solution**: Consolidate ALL chapters into a single `<ScrollytellingBlock>`. Place static content before or after, not interleaved.

### No Blank Lines Between Chapters
**Issue**: Blank lines between `</Chapter>` and `<Chapter>` tags can also cause issues.

**Solution**: Ensure `</Chapter>` and the next `<Chapter>` are on adjacent lines with no blank lines between them.

---

## Technical Gotchas

### Chart "Crashes" & Warnings
**Issue**: `<Chart>` component logs `Icon with img role is missing an accessible label`.

**Reality**: This is often a **non-fatal warning**. If the app crashes, it is likely due to **malformed MDX structure** (unclosed tags, bad nesting) around the Chart, rather than this specific accessibility check.

**Solution**:
- **Verify MDX Structure**: Ensure strictly valid JSX.
- **Ignore the Warning**: If the chart renders, this console error can be ignored.

### No Tailwind CSS
**Issue**: Utility classes like `text-red-500` have no effect.

**Reason**: Project uses `styled-components`, not Tailwind.

**Solution**: Don't attempt to style with utility classes.

### Server Components Context
**Issue**: Some components fail with "createContext only works in Client Components."

**Solution**: Components using styled-components need `'use client';` directive (but most MDX components are already configured correctly).

## Rapid Prototyping Strategy

1. **Start Simple**: Begin with a known-good dataset (GPM, NLCD, population)
2. **Verify Data**: Check `app/content/datasets/` before referencing any dataset
3. **Copy Working Examples**: Duplicate an existing story as a template
4. **Test Early**: View story in browser after writing frontmatter and first chapter
5. **Iterate**: Add chapters one at a time, testing after each

## Red Flags to Watch For

🚩 **Dataset doesn't have MDX file** → Will cause crash, check first
🚩 **Zoom exceeds dataset's zoomExtent** → 400 errors in console, check dataset MDX for limits
🚩 **Using title/summary in frontmatter** → Will cause 404, use id/name/description
🚩 **Different zoom/center across temporal chapters** → Will be disorienting, use filmstrip pattern
🚩 **No data interpretation text** → Users won't understand colors, add legend explanation
🚩 **Image path not verified** → Broken image, check public/images/ first
🚩 **Multiple ScrollytellingBlocks** → Will crash scrollama, use ONE block for all chapters

## Dataset Zoom Limits

Each dataset has a `zoomExtent` property in its MDX file. Exceeding the max zoom causes WMTS 400 errors.

**Common limits:**
- GEDI biomass: [0, 5]
- GPM/IMERG: [0, 6]
- Nighttime Lights: [0, 8]
- Landsat/Sentinel: [0, 12]+

**Always check:** `app/content/datasets/{dataset-id}.mdx` before setting Chapter zoom levels.

---

For complete technical details, see the main project's `docs/LESSONS_LEARNED.md`.
