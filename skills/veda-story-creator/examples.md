# Annotated Story Example

This is a complete, working story with annotations explaining each pattern.

## The Great Quiet (annotated)

```mdx
---
id: the-great-quiet                          # Must match filename slug
name: The Great Quiet                         # Human-readable title
description: "How the COVID-19 lockdowns became a global atmospheric experiment."  # Quoted string
media:
  src: /images/dataset/no2--dataset-cover.jpg # Must exist in public/images/
  alt: Air quality imagery                    # Accessibility text
  author:
    name: Mick Truyts                         # Image credit
    url: https://unsplash.com/photos/x6WQeNYJC1w
pubDate: 2026-01-30                           # YYYY-MM-DD format
taxonomy:
  - name: Topics                              # Always use "Topics" as the name
    values:
      - Air Quality                           # 1-3 topic tags
      - Human Impact
---

<!-- PATTERN: Intro Block with StatCard -->
<!-- Start with context and a compelling number -->
<Block>
  <Prose>
    ## The World Paused

    In early 2020, as the COVID-19 pandemic spread across the globe, nations
    implemented unprecedented lockdowns.

    <StatCard
      value="-30%"
      label="Average NO2 Drop"
      trend="Global Decrease in April 2020"
      trendColor="green"
    />
  </Prose>
</Block>

<!-- PATTERN: Scrollytelling with filmstrip technique -->
<!-- center/zoom stay the same for chapters showing the same area over time -->
<!-- center/zoom change when moving to a different geographic subject -->
<ScrollytellingBlock>
  <Chapter
    center={[114.30, 30.59]}
    zoom={6}
    datasetId='no2'
    layerId='no2-monthly'
    datetime='2020-01-01'
  >
    ### 1. The Outbreak: Wuhan (Jan 2020)

    <!-- DATA INTERPRETATION: Tell the reader what colors mean -->
    **Nitrogen Dioxide (NO2)** is a pollutant from burning fossil fuels.
    Dark red/purple indicates high concentration. In January, levels were
    still high as the lockdown was just beginning.
  </Chapter>

  <Chapter
    center={[114.30, 30.59]}
    zoom={6}
    datasetId='no2'
    layerId='no2-monthly'
    datetime='2020-02-01'
  >
    ### 2. The Drop (Feb 2020)

    <!-- FILMSTRIP: Same center/zoom, only datetime changes -->
    By February, the effect was unmistakable. NO2 levels plummeted as the
    lockdown took full effect. The dark pollution clouds vanish from the map.
  </Chapter>

  <Chapter
    center={[9.19, 45.46]}
    zoom={6}
    datasetId='no2'
    layerId='no2-monthly'
    datetime='2020-03-01'
  >
    ### 3. The Spread: Italy (Mar 2020)

    <!-- NEW LOCATION: center changes because we're showing a different place -->
    Northern Italy went into lockdown in March. The Po Valley, usually a
    pollution hotspot trapped by the Alps, saw historic clear skies.
  </Chapter>
</ScrollytellingBlock>

<!-- PATTERN: Analysis Block with Figure -->
<Block>
  <Prose>
    ## Visualizing the Impact

    The change was visible not just in data, but in the air itself.
  </Prose>

  <Figure>
    <img
      src='/images/dataset/east_coast_mar_avg.jpg'
      alt='Average NO2 levels (2015-2019)'
      style={{width: '100%', borderRadius: '8px'}}
    />
    <Caption
      attrAuthor='NASA Scientific Visualization Studio'
      attrUrl='https://svs.gsfc.nasa.gov/'
    >
      Average pollution over the I-95 corridor.
    </Caption>
  </Figure>
</Block>

<!-- PATTERN: Data Block with Quote and SimpleTable -->
<Block>
  <Prose>
    ## The Data Signal

    We can quantify this drop across multiple regions.

    <Quote author="NASA Earth Observatory" role="Scientific Report">
      The drop in nitrogen dioxide over China was initially
      containment-related... but the reduction later spread globally.
    </Quote>

    <SimpleTable
      data={{
        headers: ["Region", "NO2 Drop (Mar '20)", "Primary Source"],
        rows: [
          ["Wuhan, China", "-50%", "Transportation"],
          ["Milan, Italy", "-45%", "Industry & Auto"],
          ["New York, USA", "-30%", "Transportation"]
        ]
      }}
    />
  </Prose>

  <!-- PATTERN: Chart with existing CSV data -->
  <Figure>
    <Chart
      dataPath="/charts/story/no2-and-so2-charts.csv"
      dateFormat="%Y"
      idKey='Data Type'
      xKey='Year'
      yKey='China Change from 2005'
    />
    <Caption>
      Change in NO2 levels in China relative to 2005. Note the dip in 2020.
    </Caption>
  </Figure>
</Block>

<!-- PATTERN: Conclusion Block -->
<Block>
  <Prose>
    ## Conclusion

    The "Great Quiet" didn't last. As lockdowns eased, emission levels
    rebounded. However, this period provided scientists with a valuable
    baseline — proof that policy decisions can have immediate, measurable
    effects on planetary health.
  </Prose>
</Block>
```

## Map with Compare Slider (from template-story.mdx)

Use `compareDateTime` on `<Map>` to create a before/after slider:

```mdx
<Block>
  <Prose>
    ## Before and After
    Description of what the comparison shows.
  </Prose>

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
      SO2 comparison: 2006 vs 2021
    </Caption>
  </Figure>
</Block>
```

## Common Patterns Summary

| Pattern | When to Use | Key Rule |
|---------|-------------|----------|
| Filmstrip | Same area, different times | Keep center/zoom identical |
| Location shift | Different geographic subject | Change center/zoom |
| Data guide | First chapter of a sequence | Explain what colors mean |
| StatCard in intro | Hook the reader | Lead with a compelling number |
| Quote + Table | Analysis section | Pair expert voice with data |
| Compare Map | Before/after | Use `compareDateTime` prop |
| Zoom out | Continental phenomena | Use zoom 3-5, not 8+ |
