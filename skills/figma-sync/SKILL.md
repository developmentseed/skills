---
name: devseed-figma-sync-codebase
description: 
---

# figma-sync-codebase

Analyze a codebase path (file or directory) and produce a Figma file that mirrors it at three levels: (1) library component instances placed exactly as they are used in code, (2) project-specific styles captured as local Figma variables and styles, and (3) local Figma components for every composite component in the codebase. The result is a 1:1 mapping between codebase, UI library components, and Figma — no divergence in naming, structure, or styling.

## Input
`$ARGUMENTS` is a file path or directory. If empty, default to `src/` in the current working directory.

---

## Core principles (enforce throughout all phases)

**1:1 mapping is non-negotiable.** Every component in the codebase has an exact counterpart in Figma — same name, same structure, same styling, same layout. There is no creative interpretation.

**Names come from the codebase, not from Figma conventions.** If the code imports `<Button>`, the Figma layer is named `Button`. If the code defines a `<SidePanel>` composite, the local Figma component is named `SidePanel`. Never rename.

**Always use auto layout.** Every frame, group, and component in Figma must use auto layout. No manual positioning.

**Use framework-native naming for layout primitives.** Before placing any layout wrapper, inspect the actual UI framework's component API to use the correct name (e.g. Chakra UI uses `Box`, `Flex`, `Stack`, `Container`, `Grid`; ShadCN/ui uses `div` wrappers — check actual imports). Read the framework source or docs if needed.

**Base library components first, then composites.** Never combine library components into a local component until the base usage is correctly established. Work bottom-up.

---

## Tool reference

| Job | Primary tool | Fallback |
|---|---|---|
| Get authenticated user + plan key | `whoami` (official) | — |
| Create a new Figma file | `create_new_file` (official) | — |
| Discover available libraries | `get_libraries` (official) | — |
| Search components + variables + styles | `search_design_system` (official, with `includeLibraryKeys`) | `figma_search_components` (console, with `libraryFileKey`) |
| Browse library by fileKey | `figma_get_library_components` (console) | — |
| Extract full design system tokens | `figma_get_design_system_kit` (console) | `get_variable_defs` (official, per-node) |
| Read existing Figma designs | `get_design_context` (official) | — |
| Build / write to Figma | `use_figma` (official — load figma-use skill first) | `figma_execute` (console — complex JS only) |
| Place library component instances | `figma_instantiate_component` (console) | — |
| Create local variables | `figma_create_variable`, `figma_batch_create_variables` (console) | — |
| Create variable collections | `figma_create_variable_collection` (console) | — |
| Screenshot during build (iterative) | `figma_take_screenshot` (console) | — |
| Screenshot for final output | `get_screenshot` (official) | — |

> **Two key formats — not interchangeable:**
> - `libraryKey` (`lk-...`) — official Figma MCP (`get_libraries`, `search_design_system`)
> - `fileKey` (short alphanumeric) — figma-console-mcp tools

> **Org vs community scope:** `source: "organization"` keys are scoped to the user's Figma org. `source: "community"` keys are globally accessible.

---

## Phase 1 — Foundation

### Step 1 — Project context and Figma file setup

Read `CLAUDE.md`. Extract:
- Figma file key
- UI component library name (Radix, ShadCN, Chakra, etc.) and saved library key
- Design token configuration (color palette, typography, spacing)

If CLAUDE.md is missing or incomplete, read `package.json` to detect the UI library.

**If no Figma file key exists:**
1. Call `whoami` to get the authenticated user's plan key (use the `key` field from the plan). If the user has multiple plans, ask which team or org to use.
2. Derive the file name from the project name (from `package.json` `name` field or the directory name), formatted as Title Case (e.g. "AKD Flow", "Source Coop").
3. Call `create_new_file` with `editorType: "design"`, the derived file name, and the plan key. If the user wants the file in a specific Figma project folder, ask for the project URL and extract the `projectId`.
4. Save the returned file key to CLAUDE.md before continuing.

**File structure setup (new file or existing file without structure):**

Before building anything, establish the page structure. Use `use_figma` (load figma-use skill first) to create the following pages in this order — do not create pages that already exist:

| Page name | Purpose |
|---|---|
| `Cover` | Project name, repo link, last updated date, brief description |
| `🎨 Tokens & Styles` | Local variables, color styles, text styles — populated in Phase 1 |
| `🧩 Components` | Local composite components — populated in Phase 2 |
| One page per route | Named by the label used in the navigation, not the route path |

**Page naming rule:** Read the navigation component(s) in the codebase to find the human-readable label for each route. Use that label as the Figma page name, in Title Case. Only fall back to the route path if no label exists. Example: if `/model` is labelled "Explorer" in the nav, the Figma page is named `Explorer`, not `Model`.

**Within each route page, pre-create the following sections** (even if empty — they will be filled during Phase 2):
- `Desktop` — contains 1440px-wide frames
- `Mobile` — contains 375px-wide frames (skip if the codebase has no responsive/mobile layout)
- `States` — loading, error, and empty state variants

Section spacing: 160px vertical gap between sections. Frame spacing within a section: 80px horizontal gap between frames. Leave 120px padding around all content inside a section.

Save the file key and page structure to CLAUDE.md before proceeding.

### Step 2 — Codebase scan

Recursively scan `$ARGUMENTS`. For each `.tsx` / `.jsx` / `.ts` / `.js` file:

**Identify two levels of component usage:**

**Level 1 — Base library imports:** Which UI library components are imported and how are they used? Capture:
- Exact import names (e.g. `import { Button, Input } from '@chakra-ui/react'`)
- All props passed (variant, size, colorScheme, etc.)
- All className or style overrides applied on top of the base component
- Layout primitives used (Box, Flex, Stack, Container — inspect the framework)

**Level 2 — Composite components:** Which project-defined components combine or wrap base library components? Capture:
- Component name (exactly as defined in the file)
- Which base components it contains and how they are composed
- Props passed down, layout structure, styling

Build two inventories:
- **Base inventory:** `import name → props + styling overrides`
- **Composite inventory:** `component name → composition tree + styling`

**Test data scan:** Search the codebase for test fixtures, mocks, and sample data to use as realistic content in Figma. Check in this order:
- Jest test files (`*.test.ts`, `*.spec.ts`, `__mocks__/`, `__fixtures__/`)
- Cypress fixtures (`cypress/fixtures/`)
- Storybook stories (`*.stories.tsx`)
- Any `mock*.ts`, `seed*.ts`, `fixture*.ts`, or `fakeData*.ts` files

Extract realistic values for: user names, place names, numbers, labels, descriptions, dates, status values — anything that will appear as text or data in the UI. Use these values throughout all Figma builds instead of lorem ipsum or placeholder text. If no test data exists, infer realistic values from the component's prop types and context.

### Step 3 — Figma library resolution

**Key distinction — two different identifiers, both required:**

| Key | Format | Source | Used by |
|---|---|---|---|
| `libraryKey` | `lk-a08e7c72...` (long hex) | `get_libraries` response | `search_design_system` scoping |
| `fileKey` | `Y9q43mbwqwK4FqVf3e17fs` (short alphanumeric) | Library file URL | `figma_get_library_components`, `importComponentByKeyAsync`, REST API |

These are **not interchangeable**. `figma_get_library_components` will 404 if given an `lk-` key. CLAUDE.md must store both. If only the `libraryKey` is saved, the fileKey is still missing.

**3a — Discover available libraries and capture both keys**

Call `get_libraries` with the project's Figma file key. Paginate until the full list is retrieved. Search for the detected UI library by name.

Save the `libraryKey` (`lk-...`) to CLAUDE.md. Then immediately obtain the `fileKey`:
1. Instruct the user: in the Figma project file → Assets panel → drag any component from the library onto the canvas → right-click it → **"Go to main component"** → copy the URL that opens. The `fileKey` is the short alphanumeric segment after `/design/` (e.g. `IEAX7LBhU1FTzzbJXYycCw`).
2. Save the `fileKey` and full library URL to CLAUDE.md alongside the `libraryKey` before continuing. Do not proceed without the `fileKey`.

**3a-ii — Enumerate all component variants and text styles**

Once the `fileKey` is known, make these two calls in parallel:

1. `figma_get_library_components` with `fileKey`, `includeVariants: true`, no query (get everything). This returns all component sets with their `variants` arrays — each variant has its own importable `key` and property string (e.g. `size=lg, variant=solid, state=default, colorPalette=orange`). The result may be large; parse it with `jq` or Python if needed.

2. `figma_get_design_system_kit` with `fileKey`, `format: "compact"`, `include: ["styles"]`. This returns all published text styles and effect styles with their `key` values. Text styles are importable via `figma.importStyleByKeyAsync(key)` in `use_figma`.

Save the following to CLAUDE.md for reuse across all subsequent build steps:
- Component variant keys for every component_set used in the codebase (especially high-frequency ones: Button, Input, Select, Badge, etc.) — keyed as `ComponentName size/variant/state/colorPalette: key`
- Text style keys for the sizes used in the codebase — keyed as `styleName: key`

**This enumeration must complete before Step 4. It is never optional — it is how library components and styles are actually used.**

**3b — Library not found**

If no match is found in `get_libraries`, work through the following steps in order:

1. **Check the package name directly.** Use the detected package name to identify the canonical community library. Common mappings:
   - `@radix-ui/themes` → search "Radix Themes" on Figma Community
   - `shadcn/ui` or `@shadcn/ui` → search "shadcn/ui components" on Figma Community
   - `@chakra-ui/react` → search "Chakra UI Figma Kit" on Figma Community
   - `@mui/material` → search "Material 3 Design Kit" on Figma Community
   - `@mantine/core` → search "Mantine UI" on Figma Community
   - `antd` → search "Ant Design" on Figma Community

2. **Give the user exact steps to connect it:**
   > "I couldn't find a [library name] library in your Figma org or community libraries. To connect it:
   > 1. Go to figma.com/community and search **"[canonical search term]"**
   > 2. Open the official or most widely used result
   > 3. Click **Open in Figma** — this duplicates it to your drafts
   > 4. In that file: Main menu → Libraries → **Publish styles and components**
   > 5. Back in your project file: Assets panel → book icon → find **[library name]** → **Enable**
   > 6. Share the URL of the community file so I can save the file key"

3. Save the confirmed file key to CLAUDE.md before continuing.

4. If the user cannot or does not want to set up the library, fall back to building all components as custom frames using extracted tokens only — do not block progress. Note this clearly in the final report.

**3c — What each tool can and cannot do**

| Tool | Key format needed | What it returns | Limitation |
|---|---|---|---|
| `search_design_system` | `libraryKey` (`lk-...`) | Components, variables, styles — searchable by name | Returns component_set keys only, NOT individual variant keys |
| `figma_get_library_components` | `fileKey` (short alphanumeric) | All components with full `variants` arrays including individual variant keys | Requires the actual file URL/key, not the lk- key |
| `figma_get_design_system_kit` | `fileKey` | All styles (text, effect) and tokens with importable keys | Requires fileKey |
| `importComponentByKeyAsync` | Individual `component` key | Imports a single component instance | FAILS on component_set keys — always use a variant key |
| `importStyleByKeyAsync` | Style key | Imports a text or effect style for local use | Requires the style key from `figma_get_design_system_kit` |
| `importVariableByKeyAsync` | Variable key | Imports a library variable for binding | Requires the variable key |

**Rule:** `search_design_system` is useful for discovery and variable lookup. For actually importing components to place in designs, always use `figma_get_library_components` to get variant keys first.

**3d — Ensure the library is subscribed**

Check `libraries_added_to_file`. If the library is not subscribed:
1. Inform the user and instruct: Assets panel → book icon (Libraries) → find library → Enable.
2. If it hasn't been published (private team file): open that file → Main menu → Libraries → "Publish styles and components" (manual Figma UI action — MCP cannot do this).
3. Wait for confirmation before continuing.

### Step 4 — Component mapping

For each item in the base inventory:
1. Call `search_design_system` with `includeLibraryKeys` to find the matching Figma library component. Note the `componentKey`, `assetType`, and available variant properties.
2. Map code props (e.g. `variant="outline"`, `size="sm"`) to Figma component property values returned by the search.
3. Build a **mapping table**: `import name → componentKey + assetType + property mappings`

**Handling `component_set` vs `component`:**
- `search_design_system` returns `assetType: "component"` for standalone components and `assetType: "component_set"` for components with variants (e.g. Button with solid/outline/ghost variants).
- `importComponentByKeyAsync` only works with individual `component` keys — it WILL FAIL on a `component_set` key.
- **Never use the component_set key for import.** Always resolve individual variant keys first.

**Getting variant keys (required before any component_set is placed):**
1. Call `figma_get_library_components` with the library `fileKey` and `includeVariants: true`.
2. In the results, find the component_set by name. Its `variants` array contains individual variant objects with their own `key` and property values (e.g. `variant=solid, size=lg`).
3. Match the code props (e.g. `variant="solid" size="lg"`) to the correct variant entry. Use that variant's `key` with `importComponentByKeyAsync`.
4. This must be done for EVERY component_set used in the codebase — especially high-frequency ones like Button, Input, Badge, Select.

If `figma_get_library_components` is not yet available (fileKey not yet obtained), block progress until the fileKey is resolved — do not fall back to custom frames for component_sets that have a known library match.

**After placing any component instance — set properties to match code:**

After `const instance = comp.createInstance()`, immediately call `setProperties` to match all code props:

```js
instance.setProperties({
  'label#nodeId':      'Learn More',           // TEXT property
  'variant':           'outline',               // VARIANT property
  'size':              'lg',                    // VARIANT property
  '.iconEnd?#nodeId':  false,                  // BOOLEAN — hide if not in code
  '.iconStart?#nodeId': true,                  // BOOLEAN — show if code has icon
});
```

Inspect `instance.componentProperties` first to find all available property names and their `#nodeId` suffixes before calling `setProperties`.

**INSTANCE_SWAP for icons — correct approach:**

To swap an icon or nested component instance (e.g. `iconStart` on a Button):

```js
// 1. Import the target icon component by its key
const iconComp = await figma.importComponentByKeyAsync('iconComponentKey');

// 2. Pass the imported component's NODE ID (not its key) to setProperties
instance.setProperties({ 'iconStart#nodeId': iconComp.id });
```

**Critical:** `setProperties` for INSTANCE_SWAP requires the **node ID** of the imported component (`.id`), NOT its component key (`.key`). Passing the key string will throw "Property value is incompatible with component property type".

**Icon sourcing strategy:**
1. First, check the UI library's own icon set using `figma_get_library_components` with a query for the icon name (e.g. "info", "map", "chevron").
2. If an exact match exists in the library, import it and swap it in.
3. If no exact match: use the closest available icon from the library, flag it with `⚠ icon: should be [LuX] — add lucide/correct icon library to Figma and re-swap`.
4. Notify the user: "The [icon library] icon set is not available in this Figma file. Closest available icon from [UI library] was used. To use exact icons, add the [lucide/heroicons/etc] icon library to Figma and re-swap `iconStart` on affected components."

**Text color — always use library variables:**

Never set text fills with hardcoded hex values. Always:
```js
const variable = await figma.variables.importVariableByKeyAsync('variableKey');
const boundPaint = figma.variables.setBoundVariableForPaint(
  { type: 'SOLID', color: { r: 0, g: 0, b: 0 } }, 'color', variable
);
node.fills = [boundPaint];
```

Use the Chakra semantic color variable keys saved in CLAUDE.md (e.g. `text/fg` for primary text, `text/fg_muted` for secondary/muted text, `orange/600` for brand fills). Only use hardcoded hex as a last resort when no matching library variable exists, and flag it.

### Step 5 — Token extraction and local variable creation

**This step runs before any building.** Variables and text styles must exist before components are placed, so they can be bound immediately.

**5a — Read the theme file**

Find the project's theme configuration file (e.g. `theme.ts`, `theme.tsx`, `chakra.ts`, `tokens.ts`, or the equivalent). Extract:
- **Colors:** every named color token and its value (including semantic aliases like `navBg`, `panelBorder`, and full palette ramps like `orange.50–950`)
- **Typography:** font family names (e.g. `DM Sans`, `DM Mono`), size scale, weight scale, line-height scale, letter-spacing values
- **Custom text styles:** any `defineTextStyles` or equivalent definitions (e.g. `subTitle`, `allCapLabel`, `sliderLabel`) — capture name, font, size, weight, color, letter-spacing, transform
- **Spacing, radius, shadow:** any custom scale values

**5b — Create local Figma variables** (on the `🎨 Tokens & Styles` page)

Create variable collections that mirror the theme structure exactly. Do this before building any pages.

- One collection per semantic group: `Colors`, `Typography`, `Spacing` (add others as needed)
- For colors: create one variable per token. Use the exact token name from the theme (e.g. `orange/600`, `navBg`, `panelBorder`). Set scopes appropriately (`FRAME_FILL`, `TEXT_FILL`, etc.).
- For light/dark themes: create two modes (`Light`, `Dark`) in the Colors collection and set values per mode.
- For font families: create string variables for each font (e.g. `font/body`, `font/mono`) — these will bind to text nodes.
- Save all variable IDs for use in Steps 6–8.

**5c — Import library text styles, then create local overrides**

The UI library's text styles were already enumerated in Step 3a-ii. Use those keys now:

1. For each text style key saved to CLAUDE.md, import it in `use_figma` with `await figma.importStyleByKeyAsync(key)`. This makes it available as a local style reference within the project file.
2. Build a **text style map**: `styleName → imported style ID`. Cache this map for use in all subsequent build steps.
3. Apply imported styles to text nodes via `textNode.textStyleId = importedStyle.id`.

**Note on library text style naming:** Different libraries use different naming conventions:
- Chakra UI v3: `sm/font-normal`, `lg/font-bold`, `4xl/font-semibold`, etc. (size/weight format)
- Radix: may vary
- ShadCN: may vary
Always check the actual style names from `figma_get_design_system_kit` rather than guessing.

**Only create local text styles for values the library does not publish** — typically project-specific custom styles from the theme file (e.g. Chakra's `defineTextStyles`: `subTitle`, `allCapLabel`, `sliderLabel`). Local styles must:
- Be named to match the theme definition exactly
- Use the same font family, size, weight, line-height, letter-spacing, and text-transform
- Be placed on the `🎨 Tokens & Styles` page

**Every text node must have a `textStyleId` — either from an imported library style or a local style. Never set raw `fontSize` or `fontName` directly on a text node.**

**5d — Reconcile with library**

Call `figma_get_design_system_kit` with the library's fileKey to see what variables and styles the library already defines. Map project tokens → library variables where a match exists. Only create local variables for values the library does not cover.

---

## Phase 2 — Build with library components

> **Prerequisite:** Load the `figma-use` skill before any `use_figma` call. Use `figma_execute` only for operations `use_figma` cannot express.

### Step 6 — Build shared components first

**Before building any page, build all shared layout components as local Figma components on the `🧩 Components` page.** These are used on every page and must exist as reusable instances, not duplicated frames.

Identify shared components from the composite inventory — anything that appears in the root layout, is imported by multiple pages, or represents persistent UI (header, footer, navigation, sidebar, logo). Common examples: `Header`, `Footer`, `Sidebar`, `Nav`, `Logo`, `AppShell`.

For each shared component:
1. Create a local Figma component (not a frame) on the `🧩 Components` page, inside a Section named `Shared`.
2. Follow the same rules as Step 8: 1:1 structure, auto layout, library instances inside, variables bound, text styles applied.
3. Use test data from Step 2 to populate navigation labels, logo text, user info, etc.
4. After creating each shared component, take a screenshot to validate.

**Do not proceed to page building until all shared components exist as local Figma components.**

When building pages, always place shared components as instances of the local Figma component — never redraw them inline.

### Step 7 — Place base library components on pages

For each page or component file in `$ARGUMENTS`, work section by section, top to bottom:

**Before starting each page:** Call `get_design_context` to check what already exists on that page's Figma canvas. Do not overwrite existing work without confirming with the user.

**Container setup:** Navigate to the correct route page (created in Step 1). Place all content inside the pre-created `Desktop` section as 1440px-wide frames. Use auto layout on everything — no exceptions. Follow the spacing established in Step 1: 160px between sections, 80px between frames, 120px padding inside sections.

**Shared components:** Place the shared layout components (Header, Footer, etc.) created in Step 6 as instances at the top/bottom of each page frame. Never redraw them — always use instances.

**For each base library component in the file:**
1. Import the component using its `componentKey` from the mapping table via `importComponentByKeyAsync`.
2. If `assetType` is `"component_set"` and only the set key is available: import the default variant, name the layer correctly, and add an annotation (`⚠ needs variant: [prop=value]`) so the gap is visible and trackable.
3. Set variant properties to match the code props exactly where the variant is correctly resolved.
4. Apply any className or style overrides as local overrides on the instance (not on the library component itself), bound to local variables from Step 5.
5. Name the layer exactly as the component is named in the import.
6. **Never substitute a library component with a custom-drawn frame.** If a component cannot be imported, place the default import and flag it. A file full of library instances with flags is better than a file full of custom frames.

**For all text nodes:**
- Apply a text style from Step 5c to every text node — never set raw `fontSize`, `fontName`, or `fontWeight` directly.
- Use test data from Step 2 for all content. No lorem ipsum, no "placeholder text".

**For layout primitives** (Box, Flex, Stack, Container, Grid, etc.):
- Inspect the actual UI framework to confirm correct naming and behavior before placing.
- Recreate the layout intent using auto layout frames named to match the framework primitive (e.g. a `Stack` becomes an auto layout frame named "Stack" with vertical direction and appropriate gap).

**Iterative validation:** After each major section, call `figma_take_screenshot`. Verify layout matches the code structure. Fix before moving on. Max 3 iterations per section.

**Multi-page handling:** Complete one page fully before moving to the next. Confirm with user between pages.

---

## Phase 3 — Style system and local composite components

### Step 8 — Capture project styles as local Figma variables and styles

Once base library components are placed, document every styling override from the codebase as a local Figma design system layer. These sit on top of the library's own variables and styles.

**What to create as variables** (primitive, reusable values):
- Color overrides: brand colors, semantic colors, background/surface overrides
- Spacing overrides: custom gap, padding, margin values not in the library scale
- Border radius overrides
- Organize into a variable collection named after the project (e.g. "Source Coop Tokens")
- Create modes for light/dark if the codebase supports theming

**What to create as styles** (composite visual treatments):
- Typography: font family + size + weight + line-height combinations used across the project → create as text styles
- Shadow / elevation overrides → create as effect styles

**How to capture:**
1. For each styling override found in Step 2, check whether a matching Figma variable or style already exists in the connected library using `search_design_system`.
2. If it exists, bind the override to that existing variable.
3. If it does not exist, create a new local variable or style using `figma_create_variable` / `figma_batch_create_variables` / `figma_create_variable_collection`.
4. Go back to the instances placed in Phase 2 and bind overrides to the new variables rather than leaving them as hardcoded values.

### Step 9 — Create local composite components

For each composite component in the composite inventory from Step 2:

**Rule:** A local Figma component is created for every project-defined component that combines, wraps, or styles base library components. The Figma component must match the codebase component exactly in name, structure, layout, and styling.

1. **Name:** Use the exact component name from the codebase. No renaming.

2. **Structure:** Reproduce the JSX tree as a Figma component hierarchy:
   - Each child element in JSX → a layer in Figma, named identically
   - Nesting and grouping must match the component's DOM structure
   - All frames use auto layout

3. **Styling:** Apply project variables and styles from Step 7. Do not hardcode values that exist as variables.

4. **Composition:** Use `figma_instantiate_component` for any base library components nested inside the composite. The composite Figma component contains library instances, not raw frames, wherever the code uses library components.

5. **Variants:** If the codebase component accepts props that change its visual appearance, create Figma component variants to match. Variant names must match the prop names and values from the code.

6. **Organization:** Place all local composite components in a dedicated Section named "Components — [Project Name]", separate from the page layouts.

7. **Validation:** After creating each local component, call `figma_take_screenshot`. Verify it visually matches the rendered codebase component. Fix before moving on.

---

## Phase 4 — Final validation and report

### Step 10 — Validate and report

1. Call `get_screenshot` on each completed page frame and each local component for final output.
2. Verify: all layers use auto layout, all instances use library components where applicable, all color/spacing overrides are bound to variables, all local components match their codebase counterparts.
3. Report:
   - Pages built and library components used
   - Local variables and styles created (names and values)
   - Local composite components created (names and structure)
   - Gaps: components without a library match, tokens that could not be resolved to variables

---

## Rules summary
- 1:1 mapping between codebase, library components, and Figma — always
- Layer names = codebase import or component names — never rename
- Always use auto layout — no manual positioning
- Inspect the UI framework for layout primitive names before placing any wrapper
- **Variables and text styles must be created (Step 5) before any building begins**
- **Shared components (Header, Nav, Logo, Footer) must be built as local Figma components (Step 6) before any page is built**
- **Page names come from navigation labels, not route paths**
- Base library components must be placed as library instances — never reproduced as custom frames
- When a component_set key is all that's available: import the default variant, flag it, never substitute a custom frame
- All text nodes must have a text style applied — never raw fontSize/fontName
- All text content must use real data from tests/mocks — never lorem ipsum or placeholder text
- All color/spacing overrides must be bound to local variables — never hardcoded
- Local composite components are created for every project-defined component that combines base components
- Load `figma-use` skill before any `use_figma` call
- Use `figma_execute` only when `use_figma` cannot accomplish the operation
- Process one page at a time, confirm with user before continuing to the next
- Save `libraryKey` and `fileKey` values back to CLAUDE.md after resolving them
