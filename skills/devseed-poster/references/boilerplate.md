# Poster Boilerplate

Full starter HTML for a Development Seed conference poster. Replace all `FILL:` placeholders.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>FILL: Poster title — Author et al. YEAR</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap');

  :root {
    --accent: #E84B23;
    --ink:    #1a1614;
    --mid:    #4a4440;
    --muted:  #9a9490;
    --rule:   #dedad4;
    --bg:     #f7f4ef;
    /* project-specific accent colours — add as needed */
    /* --gnw:  #2a5c45; */
    /* --dede: #1d4e8f; */
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  html, body {
    width: 100%; height: 100%;
    background: #888;
    display: flex; align-items: center; justify-content: center;
  }

  .scale-wrap {
    width: 1978px; height: 1183px;
    transform-origin: top center;
    background: var(--bg);
    font-family: 'DM Sans', sans-serif;
    font-size: 14px; color: var(--ink);
    flex-shrink: 0;
  }

  /* ── POSTER GRID ── */
  .poster {
    display: grid;
    width: 1978px; height: 1183px;
    overflow: hidden;
    grid-template-columns: 36px repeat(12, 1fr) 36px;
    grid-template-rows: auto 1fr 84px;
    gap: 0 20px;
  }

  /* ── HEADER ── */
  .header {
    grid-column: 2 / 14; grid-row: 1;
    display: grid; grid-template-columns: 1fr auto;
    align-items: end;
    padding-top: 18px; padding-bottom: 14px;
    border-bottom: 3px solid var(--ink);
  }
  .session-tag {
    font-family: 'DM Mono', monospace; font-size: 11px;
    letter-spacing: .12em; text-transform: uppercase;
    color: var(--accent); margin-bottom: 8px;
  }
  h1 {
    font-family: 'DM Serif Display', serif;
    font-size: 34px; line-height: 1.08; max-width: 920px;
  }
  h1 em { font-style: italic; color: var(--accent); }
  .authors { font-size: 11.5px; color: var(--mid); margin-top: 9px; line-height: 1.5; }
  .authors strong { color: var(--ink); }
  .header-right {
    display: flex; flex-direction: column; align-items: flex-end;
    gap: 10px; padding-bottom: 2px;
  }
  .logo-row { display: flex; gap: 16px; align-items: center; }

  /* ── BODY ── */
  .body {
    grid-column: 2 / 14; grid-row: 2;
    display: grid;
    grid-template-columns: repeat(12, 1fr);
    grid-template-rows: auto auto 1fr;   /* IMPORTANT: not 1fr 1fr 1fr */
    gap: 12px 16px; padding-top: 12px;
  }

  /* ── CARDS ── */
  .card { display: flex; flex-direction: column; gap: 6px; }
  .card-label {
    font-family: 'DM Mono', monospace; font-size: 10px;
    letter-spacing: .14em; text-transform: uppercase; color: var(--muted);
    display: flex; align-items: center; gap: 8px; flex-shrink: 0;
  }
  .card-label::after { content: ''; flex: 1; height: 1px; background: var(--rule); }
  .card h2 {
    font-family: 'DM Serif Display', serif; font-size: 17px;
    line-height: 1.18; flex-shrink: 0;
  }
  .card p { font-size: 12.5px; line-height: 1.57; color: var(--mid); }
  .card p strong { color: var(--ink); font-weight: 600; }
  .card-link {
    font-family: 'DM Mono', monospace; font-size: 10px;
    color: var(--mid); margin-top: 4px;
  }
  .accent-dot {
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    margin-right: 5px; vertical-align: middle; position: relative; top: -2px;
  }

  /* ── TWO-COLUMN SYSTEM CARD ── */
  .sys-body { display: flex; gap: 14px; align-items: flex-start; }
  .sys-text { flex: 1; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .sys-img  { flex: none; max-width: 55%; height: auto;
              border-radius: 5px; border: 1px solid var(--rule); }

  /* ── LESSONS / PRINCIPLES ── */
  .lesson-list { display: flex; flex-direction: column; gap: 11px; margin-top: 2px; }
  .lesson { display: flex; gap: 9px; align-items: flex-start; }
  .lesson-num {
    font-family: 'DM Serif Display', serif; font-size: 26px; line-height: 1;
    color: var(--mid); flex-shrink: 0; width: 24px; text-align: right;
  }
  .lesson-title { font-size: 12px; font-weight: 600; color: var(--ink); line-height: 1.2; margin-bottom: 1px; }
  .lesson-desc  { font-size: 11.5px; color: var(--mid); line-height: 1.47; }

  /* ── PIPELINE / FLOW ── */
  .pipeline  { display: flex; align-items: stretch; height: 68px; flex: none; margin-top: 4px; }
  .pipe-step {
    flex: 1; padding: 7px 8px; font-size: 11px; line-height: 1.36;
    background: white; border-left: 3px solid var(--rule); color: var(--mid);
  }
  .pipe-step:first-child { border-radius: 4px 0 0 4px; border-left-color: var(--accent); }
  .pipe-step strong { display: block; font-size: 11.5px; color: var(--ink); margin-bottom: 2px; }
  .pipe-arrow {
    width: 13px; display: flex; align-items: center; justify-content: center;
    color: var(--muted); background: white;
  }

  /* ── CALLOUT ── */
  .callout {
    border-left: 3px solid var(--accent); padding: 7px 10px;
    background: color-mix(in srgb, var(--accent) 5%, white);
    border-radius: 0 4px 4px 0; font-size: 12px; font-style: italic;
    color: var(--mid); line-height: 1.5; flex-shrink: 0;
  }

  /* ── STAT BOXES ── */
  .stat-row { display: flex; gap: 10px; margin-top: 3px; flex-shrink: 0; }
  .stat {
    flex: 1; padding: 7px 9px; background: white;
    border-radius: 4px; border-top: 3px solid var(--accent);
  }
  .stat-value { font-family: 'DM Serif Display', serif; font-size: 24px; color: var(--accent); }
  .stat-label { font-size: 10.5px; color: var(--mid); line-height: 1.3; margin-top: 2px; }

  /* ── FOOTER ── */
  .footer-strip {
    grid-column: 2 / 14; grid-row: 3;
    display: flex; align-items: flex-start; justify-content: space-between;
    border-top: 1.5px solid var(--rule); padding-top: 8px;
  }
  .footer-meta { font-family: 'DM Mono', monospace; font-size: 10px; color: var(--mid); line-height: 1.65; }
  .footer-qr-zone { display: flex; gap: 18px; align-items: flex-start; }
  .qr-block { display: flex; flex-direction: column; align-items: center; gap: 2px; }
  .qr-block img { filter: invert(1) brightness(0.667) invert(1); }
  .qr-label { font-family: 'DM Mono', monospace; font-size: 9px; color: var(--ink); font-weight: 500; }
  .photo-allowed {
    display: flex; align-items: center; gap: 6px;
    font-size: 10px; font-family: 'DM Mono', monospace; color: var(--mid);
  }
  .photo-icon {
    width: 30px; height: 30px; border: 1.5px solid var(--accent); border-radius: 4px;
    display: flex; align-items: center; justify-content: center; font-size: 15px;
  }

  /* ── GRID PLACEMENT — adjust spans to your content ── */
  /* Example: 3-col left / 5-col middle / 4-col right across all rows */
  .c-intro    { grid-column: 1 / 4;  grid-row: 1; }
  .c-sys1     { grid-column: 4 / 9;  grid-row: 1; }
  .c-sys2     { grid-column: 9 / 13; grid-row: 1; }
  .c-lessons  { grid-column: 1 / 4;  grid-row: 2; }
  .c-arch     { grid-column: 4 / 9;  grid-row: 2; }
  .c-related  { grid-column: 9 / 13; grid-row: 2; }
  .c-eval     { grid-column: 1 / 4;  grid-row: 3; }
  .c-method   { grid-column: 4 / 9;  grid-row: 3; }
  .c-takeaway { grid-column: 9 / 13; grid-row: 3; }
</style>
</head>
<body>
<div class="scale-wrap">
<div class="poster">

  <header class="header">
    <div class="header-left">
      <div class="session-tag">FILL: Session · Conference · Date · Room</div>
      <h1>FILL: Main Title with <em>Italic Accent</em></h1>
      <div class="authors">
        <strong>FILL: Presenting Author</strong>, Co-Author One, Co-Author Two<br>
        <span style="color:var(--mid)">¹ Organisation, City · ² Organisation, City</span>
      </div>
    </div>
    <div class="header-right">
      <div class="logo-row">
        <!-- Replace with actual logo imgs: <img src="logo.svg" style="height:66px;width:auto"> -->
      </div>
    </div>
  </header>

  <div class="body">

    <!-- ROW 1 ─────────────────────────────────────────── -->

    <div class="card c-intro">
      <div class="card-label">Motivation</div>
      <h2>FILL: Problem statement</h2>
      <p>FILL: Why this matters. What was missing or broken.</p>
      <div class="callout">FILL: Key quote or framing statement.</div>
    </div>

    <!-- Two-column system card -->
    <div class="card c-sys1">
      <div class="card-label">System 1</div>
      <div class="sys-body">
        <div class="sys-text">
          <h2><span class="accent-dot" style="background:var(--accent)"></span>FILL: System Name</h2>
          <p>FILL: What it does, who uses it, key partners.</p>
          <div class="card-link">FILL: example.org</div>
        </div>
        <img class="sys-img" src="FILL: screenshot.png" alt="FILL: description">
      </div>
    </div>

    <div class="card c-sys2">
      <div class="card-label">System 2</div>
      <div class="sys-body">
        <div class="sys-text">
          <h2><span class="accent-dot" style="background:var(--accent)"></span>FILL: System Name</h2>
          <p>FILL: What it does, who uses it, key partners.</p>
          <div class="card-link">FILL: status or URL</div>
        </div>
        <img class="sys-img" src="FILL: screenshot.png" alt="FILL: description">
      </div>
    </div>

    <!-- ROW 2 ─────────────────────────────────────────── -->

    <div class="card c-lessons">
      <div class="card-label">Lessons Learned</div>
      <h2>FILL: N principles for X</h2>
      <div class="lesson-list">
        <div class="lesson">
          <div class="lesson-num">1</div>
          <div class="lesson-body">
            <div class="lesson-title">FILL: Principle</div>
            <div class="lesson-desc">FILL: Explanation.</div>
          </div>
        </div>
        <!-- repeat for each principle -->
      </div>
    </div>

    <div class="card c-arch">
      <div class="card-label">Architecture</div>
      <h2>FILL: Architecture pattern name</h2>
      <p>FILL: How the system is structured and why.</p>
      <div class="pipeline">
        <div class="pipe-step"><strong>Input</strong>Description</div>
        <div class="pipe-arrow">›</div>
        <div class="pipe-step"><strong>Step</strong>Description</div>
        <div class="pipe-arrow">›</div>
        <div class="pipe-step"><strong>Output</strong>Description</div>
      </div>
      <!-- Optional: transparent diagram PNG -->
      <!-- <img src="diagram.png" style="width:100%;height:160px;flex:none;object-fit:contain"> -->
    </div>

    <div class="card c-related">
      <div class="card-label">Related Work</div>
      <h2>FILL: Related project name</h2>
      <p>FILL: Context and motivation for this work.</p>
      <div class="stat-row">
        <div class="stat">
          <div class="stat-value">FILL</div>
          <div class="stat-label">FILL: what this number means</div>
        </div>
        <div class="stat">
          <div class="stat-value">FILL</div>
          <div class="stat-label">FILL: what this number means</div>
        </div>
      </div>
      <p style="margin-top:5px">FILL: More detail.</p>
      <div class="card-link">FILL: github.com/org/repo</div>
    </div>

    <!-- ROW 3 ─────────────────────────────────────────── -->

    <div class="card c-eval">
      <div class="card-label">Evaluation</div>
      <h2>FILL: How you tested it</h2>
      <div class="lesson-list">
        <div class="lesson">
          <div class="lesson-num" style="color:var(--accent);font-size:20px">①</div>
          <div class="lesson-body">
            <div class="lesson-title">FILL</div>
            <div class="lesson-desc">FILL</div>
          </div>
        </div>
      </div>
    </div>

    <div class="card c-method">
      <div class="card-label">Key Technique</div>
      <h2>FILL: Technical contribution</h2>
      <p>FILL: What you built, why it matters.</p>
      <div class="callout" style="border-color:var(--accent);background:color-mix(in srgb,var(--accent) 6%,white)">
        <strong style="font-style:normal">Example —</strong> FILL: concrete example.
      </div>
      <p style="margin-top:6px">FILL: Conclusion or implication.</p>
    </div>

    <div class="card c-takeaway">
      <div class="card-label">Takeaway</div>
      <h2>FILL: One-sentence thesis</h2>
      <p>FILL: Why this matters beyond this project.</p>
      <div class="lesson-list" style="margin-top:5px">
        <div class="lesson">
          <div class="lesson-num" style="color:var(--accent)">→</div>
          <div class="lesson-body">
            <div class="lesson-desc"><strong>FILL:</strong> Point one.</div>
          </div>
        </div>
        <div class="lesson">
          <div class="lesson-num" style="color:var(--accent)">→</div>
          <div class="lesson-body">
            <div class="lesson-desc"><strong>FILL:</strong> Point two.</div>
          </div>
        </div>
      </div>
    </div>

  </div><!-- /body -->

  <footer class="footer-strip">
    <div class="footer-meta">
      FILL: Author et al. · Organisation · Conference-ID<br>
      FILL: email@org.com · https://doi.org/FILL
    </div>
    <div class="footer-qr-zone">
      <!-- Replace base64 src with generated QR data -->
      <div class="qr-block">
        <img src="data:image/png;base64,FILL" style="width:44px;height:44px;display:block" alt="Abstract QR">
        <div class="qr-label">Abstract</div>
      </div>
      <div class="qr-block">
        <img src="data:image/png;base64,FILL" style="width:44px;height:44px;display:block" alt="Demo QR">
        <div class="qr-label">FILL: Demo / Repo</div>
      </div>
      <div class="photo-allowed">
        <div class="photo-icon">📷</div>
        <span>Photography<br>encouraged</span>
      </div>
    </div>
  </footer>

</div><!-- /poster -->
</div><!-- /scale-wrap -->

<script>
  function scaleToFit() {
    const wrap = document.querySelector('.scale-wrap');
    const sx = window.innerWidth  / 1978;
    const sy = window.innerHeight / 1183;
    const s  = Math.min(sx, sy);
    wrap.style.transform = `scale(${s})`;
    document.body.style.alignItems = (1183 * s < window.innerHeight) ? 'center' : 'flex-start';
  }
  scaleToFit();
  window.addEventListener('resize', scaleToFit);
</script>
</body>
</html>
```
