---
name: devseed-poster
description: Create a Development Seed conference poster as a self-contained HTML file. Use this skill when the user asks to make a poster, conference poster, scientific poster, or presentation board — especially for EGU, AGU, or similar geoscience/tech conferences. Also trigger when the user mentions "poster session", "A0 poster", "print-ready poster", or wants to present work at a conference.
---

# Development Seed Poster Skill

Creates a single self-contained HTML file that renders at exact physical poster dimensions and scales to fit any browser window. Print from browser or export via Chromium headless PDF.

## Workflow

1. **Gather content** — ask for: title, authors, affiliations, session tag, abstract/DOI, sections and their text, any images or screenshots, logos
2. **Plan the grid** — decide column distribution for 3 rows of cards (see Layout section)
3. **Generate the HTML** — use the boilerplate in `references/boilerplate.md` as the starting point
4. **Iterate with screenshots** — take a headless Chromium screenshot after each batch of changes, show to user
5. **Inline assets** — convert images and logos to base64 before final export
6. **Export PDF** — use the Chromium headless command at the bottom

---

## Canvas & Scale

```
Poster: 1978 × 1183 px  (= 1978 × 1183 mm at 1 px/mm for EGU landscape board)
Background: grey #888 page, warm off-white #f7f4ef poster canvas
```

The `.scale-wrap` div is 1978×1183px and uses `transform: scale()` via JS to fit the viewport — never touch the canvas dimensions.

---

## Design System

### Fonts (Google Fonts)
```
DM Serif Display  — h1, h2, large numbers, italic emphasis
DM Sans           — body text, descriptions
DM Mono           — labels, captions, links, tags, code
```

### Colour palette
```css
--accent: #E84B23   /* DevSeed orange — primary accent, borders, highlights */
--gnw:    #2a5c45   /* Forest green — Global Nature Watch / nature topics */
--dede:   #1d4e8f   /* Deep blue — climate / ECMWF / data topics */
--ink:    #1a1614   /* Near-black body text */
--mid:    #4a4440   /* Secondary text, lesson numbers, links, footer */
--muted:  #9a9490   /* Captions only — avoid for anything that must print */
--rule:   #dedad4   /* Dividers, card borders */
--bg:     #f7f4ef   /* Warm off-white canvas background */
```

**Print rule**: use `--mid` (#4a4440) for anything that must be readable on paper. `--muted` (#9a9490) is too light — reserve it for truly decorative/secondary text only.

---

## Layout

### Poster outer grid
```css
grid-template-columns: 36px repeat(12, 1fr) 36px;  /* 36px gutters */
grid-template-rows: auto 1fr 84px;                  /* header / body / footer */
gap: 0 20px;
```

### Body inner grid (3 rows × 12 cols)
```css
grid-template-columns: repeat(12, 1fr);
grid-template-rows: auto auto 1fr;   /* rows 1+2 shrink to content; row 3 fills rest */
gap: 12px 16px;
padding-top: 12px;
```

**Critical**: use `auto auto 1fr` NOT `1fr 1fr 1fr`. Equal fractions leave dead whitespace below auto-height content. Only the bottom row gets `1fr` to fill remaining space.

### Typical column distributions (all rows must sum to 12)

| Style | Left | Middle | Right |
|---|---|---|---|
| Equal thirds | 4 | 4 | 4 |
| Narrow left | 3 | 5 | 4 |
| Wide middle | 3 | 6 | 3 |

Cards use explicit `grid-column` and `grid-row` placement — each card can span differently across rows.

### Card anatomy
```css
.card { display: flex; flex-direction: column; gap: 6px; }
/* NO overflow:hidden on cards — put overflow:hidden only on .poster */
```

```html
<div class="card">
  <div class="card-label">Section Label</div>   <!-- mono 10px all-caps + rule line -->
  <h2>Card Title</h2>                           <!-- DM Serif 17px -->
  <p>Body text...</p>                           <!-- DM Sans 12.5px / 1.57 lh -->
</div>
```

---

## Component Patterns

### Two-column system/demo card (text + screenshot side by side)
Use this for any "system showcase" card — keeps screenshots fully visible without taking all vertical space.
```html
<div class="card">
  <div class="card-label">System 1</div>
  <div class="sys-body">
    <div class="sys-text">
      <h2>System Name</h2>
      <p>Description...</p>
      <div class="card-link">example.org</div>
    </div>
    <img class="sys-img" src="screenshot.png" alt="...">
  </div>
</div>
```
```css
.sys-body { display: flex; gap: 14px; align-items: flex-start; }
.sys-text { flex: 1; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.sys-img  { flex: none; max-width: 55%; height: auto;
            border-radius: 5px; border: 1px solid var(--rule); }
```

### Numbered lessons / principles
```html
<div class="lesson-list">
  <div class="lesson">
    <div class="lesson-num">1</div>
    <div class="lesson-body">
      <div class="lesson-title">Principle title</div>
      <div class="lesson-desc">Explanation text.</div>
    </div>
  </div>
</div>
```
```css
.lesson-num { font-family: 'DM Serif Display'; font-size: 26px;
              color: var(--mid); /* NOT --rule — too faint for print */ }
```

### Stat callout boxes
```html
<div class="stat-row">
  <div class="stat">
    <div class="stat-value">~$15</div>
    <div class="stat-label">Short label</div>
  </div>
</div>
```
```css
.stat       { flex: 1; padding: 7px 9px; background: white;
              border-radius: 4px; border-top: 3px solid var(--accent); }
.stat-value { font-family: 'DM Serif Display'; font-size: 24px; color: var(--accent); }
.stat-label { font-size: 10.5px; color: var(--mid); }
```

### Callout quote / example
```html
<div class="callout" style="border-color:var(--accent);
     background:color-mix(in srgb,var(--accent) 5%,white)">
  Quote or example text.
</div>
```
```css
.callout { border-left: 3px solid; padding: 7px 10px;
           border-radius: 0 4px 4px 0; font-size: 12px;
           font-style: italic; color: var(--mid); line-height: 1.5; }
```

### Light gray card link (URL / status line)
```html
<div class="card-link">github.com/org/repo</div>
```
```css
.card-link { font-family: 'DM Mono'; font-size: 10px;
             color: var(--mid); margin-top: 4px; }
```

### Pipeline / flow strip
```html
<div class="pipeline">
  <div class="pipe-step"><strong>Step</strong>Description</div>
  <div class="pipe-arrow">›</div>
  ...
</div>
```
```css
.pipeline   { display: flex; align-items: stretch; height: 68px; flex: none; }
.pipe-step  { flex: 1; padding: 7px 8px; font-size: 11px; background: white;
              border-left: 3px solid var(--rule); }
.pipe-arrow { width: 13px; display: flex; align-items: center;
              justify-content: center; color: var(--muted); background: white; }
```

---

## Images & Screenshots

**Screenshots (browser/app captures):**
- Prefer two-column layout (`.sys-body`) so images don't consume vertical card space
- Use `max-width: 55%; height: auto` — never constrain height, let aspect ratio govern
- Never use `object-fit: cover` if full visibility is required
- `border-radius: 5px; border: 1px solid var(--rule)` on all screenshots

**Diagrams / workflow PNGs with transparent backgrounds:**
```html
<img src="diagram.png"
     style="width:100%; height:165px; flex:none;
            object-fit:contain; object-position:center">
```
Remove `background:white; padding` — let the transparent PNG sit on `--bg`.

**Logos (SVG):**
- Use `height: 60-66px; width: auto` — never fixed width, let the SVG scale
- Vertically heavier logos (portrait mark) need a taller `height` than wide horizontal logos at the same visual weight

**Inlining for self-contained export:**
```bash
python3 -c "
import base64, sys
with open(sys.argv[1],'rb') as f:
    print('data:image/png;base64,' + base64.b64encode(f.read()).decode())
" path/to/image.png
```

---

## QR Codes

Generate and inline with Python:
```bash
uv run python3 -c "
import qrcode, base64, io
urls = {
    'Label': 'https://...',
}
for label, url in urls.items():
    qr = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    print(label, base64.b64encode(buf.getvalue()).decode())
"
```

Apply dark-gray CSS filter to match the poster's restrained palette — dark gray still scans reliably on any phone camera:
```css
.qr-block img { filter: invert(1) brightness(0.667) invert(1); }
/* Result: black modules → #555, white stays white. 3:1 contrast — scannable. */
```

QR block HTML:
```html
<div class="qr-block">
  <img src="data:image/png;base64,..." style="width:44px;height:44px;display:block">
  <div class="qr-label">Short name</div>
</div>
```

---

## Common Pitfalls

| Problem | Cause | Fix |
|---|---|---|
| Dead whitespace below row 1 content | `1fr 1fr 1fr` body rows | Use `auto auto 1fr` |
| Content silently clipped | `overflow:hidden` on `.card` | Move to `.poster` only |
| Image grows to fill card height | `flex:1` on `<img>` | Use `flex:none` |
| Screenshot takes all vertical space | `width:100%; height:auto` | Two-column layout + `max-width:55%` |
| Transparent PNG shows white box | `background:white` on image | Remove it; inherit `--bg` |
| Footer overflows | Fixed footer row too short | Use `84px` min for QR + label |
| Text invisible in print | `color: var(--muted)` | Use `--mid` for anything that must print |
| Logo looks small vs neighbour | Same `height` on differently proportioned SVGs | Give portrait logos taller height than landscape logos |
| No tag pills | — | Don't use tag pills; they clutter at poster scale. Use `.card-link` for URLs instead |

---

## Screenshot for Iteration

```bash
/snap/bin/chromium --headless=new --screenshot --window-size=1978,1183 \
  --no-sandbox "file:///path/to/poster.html" 2>/dev/null
# Output: screenshot.png in current directory
```

---

## PDF Export (print-ready)

```bash
/snap/bin/chromium --headless=new --no-sandbox \
  --print-to-pdf=poster.pdf \
  --print-to-pdf-no-header \
  --no-pdf-header-footer \
  --paper-width=77.87 \
  --paper-height=46.57 \
  "file:///absolute/path/to/poster.html"
```

Dimensions: 1978 mm ÷ 25.4 = 77.87 in · 1183 mm ÷ 25.4 = 46.57 in.
Verify in PDF viewer that page size is 1978 × 1183 mm before sending to print.

---

## Full Boilerplate

Read `references/boilerplate.md` for the complete starter HTML — copy, fill in content, iterate.
