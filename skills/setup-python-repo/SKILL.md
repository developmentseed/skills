---
name: setup-python-repo
description: Scaffold CI/CD, linting, and dependency automation for a Python project using GitHub Actions. Sets up uv-based CI with pre-commit, ruff, pytest, dependabot, docs builds, security checks, release-please, and optional PyPI publishing. Use when the user says anything like "set up CI for my Python repo", "add GitHub Actions", "scaffold Python project automation", or "create workflows for lint/test/deploy".
metadata:
  author: hrodmn
  version: "1.0.1"
---

# Setup Python Repository

Scaffold GitHub Actions workflows, pre-commit hooks, and Dependabot configuration for a uv-based Python project.

## Workflow

### 1. Assess Project State

Run these diagnostics to understand what already exists:

```bash
# Check project structure
ls -la .github/workflows 2>/dev/null || echo "No .github/workflows yet"
ls -la .github/dependabot.yml 2>/dev/null || echo "No dependabot.yml yet"
ls -la .pre-commit-config.yaml 2>/dev/null || echo "No pre-commit config yet"
cat pyproject.toml 2>/dev/null | head -50 || echo "No pyproject.toml"
git remote get-url origin 2>/dev/null || echo "No git remote"
```

If `pyproject.toml` exists, read it fully to understand dependencies, build system, and existing tool configuration.

### 2. Confirm What to Scaffold

All features are included by default **except PyPI publishing**, which is opt-in. Present the user with a checklist:

- **Core CI** (always included): lint, docs build check, pre-commit, pytest matrix
- **Docs deployment** (default: yes): auto-deploy docs to GitHub Pages on push to main
- **Security checks** (default: yes): run zizmor to audit workflow security
- **Conventional commits** (default: yes): validate PR titles follow conventional commit format
- **Release automation** (default: yes): release-please for automated changelog and versioning
- **Dependabot** (default: yes): monthly grouped dependency updates for uv and GitHub Actions
- **PyPI publishing** (default: no): build and publish to PyPI on release — ask explicitly before enabling

If the user says "just the defaults" or equivalent, enable everything except PyPI publishing without further prompts.

Also collect:
- Python version matrix (default: `["3.12", "3.13", "3.14"]`)
- Docs tool (default: mkdocs — assumes `uv run --group docs mkdocs build`)
- PyPI package URL (only if PyPI publishing is enabled, e.g. `https://pypi.org/p/<package-name>`)

### 3. Create the GitHub Actions Workflows

Always create `.github/workflows/ci.yml`. Create the other workflows by default except `publish-pypi.yml`, which is only created if the user explicitly opted in.

#### `ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions: {}

jobs:
  lint-python:
    name: Lint
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          persist-credentials: false

      - name: Install a specific version of uv
        uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
        with:
          version: "0.11.*"
          enable-cache: false

      - name: Check docs
        run: uv run --group docs mkdocs build --strict

      - uses: astral-sh/ruff-action@0ce1b0bf8b818ef400413f810f8a11cdbda0034b # v4.0.0

  test:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    strategy:
      matrix:
        python-version: {{PYTHON_VERSIONS}}
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          persist-credentials: false

      - name: Install uv
        uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
        with:
          version: "0.11.*"
          enable-cache: false

      - name: Set up Python
        run: uv python install ${{ matrix.python-version }}

      - name: Run pre-commit
        if: matrix.python-version == '{{HIGHEST_PYTHON_VERSION}}'
        run: uv run pre-commit run --all-files

      - name: Run tests
        run: uv run pytest
```

Replace `{{PYTHON_VERSIONS}}` with the matrix list (e.g. `["3.12", "3.13", "3.14"]`).
Replace `{{HIGHEST_PYTHON_VERSION}}` with the highest version from that list (e.g. `3.14`).

If the user does not use mkdocs for docs, adjust or remove the docs build step in the lint job. Ask the user what docs tool they use if it is not mkdocs.

#### `docs.yml` (optional — docs deployment)

```yaml
name: Deploy Docs

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions: {}

jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          fetch-depth: 0
          persist-credentials: false

      - name: Install uv
        uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
        with:
          version: "0.11.*"
          enable-cache: false

      - name: Set up Python
        run: uv python install {{HIGHEST_PYTHON_VERSION}}

      - name: Install docs dependencies
        run: uv sync --group docs

      - name: Deploy docs
        env:
          REF_NAME: ${{ github.ref_name }}
        run: |
          uv run mkdocs gh-deploy --force
```

Replace `{{HIGHEST_PYTHON_VERSION}}` accordingly. Adjust the deploy command if using a different docs tool (e.g. Sphinx).

#### `security.yml` (optional — security checks)

```yaml
name: GitHub Actions Security Analysis with zizmor

on:
  push:
    branches: ['main']
  pull_request:
    branches: ['**']

permissions: {}

jobs:
  zizmor:
    runs-on: ubuntu-latest
    permissions:
      security-events: write
    steps:
      - name: Checkout repository
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          persist-credentials: false

      - name: Run zizmor
        uses: zizmorcore/zizmor-action@5f14fd08f7cf1cb1609c1e344975f152c7ee938d # v0.5.6
```

#### `conventional-commits-prs.yml` (optional)

```yaml
name: PR Conventional Commit Validation

# NOTE: pull_request_target runs in the base repo context with access to secrets.
# Do NOT checkout untrusted code in this workflow.
on:
  # zizmor: ignore[dangerous-triggers]
  # Safe: this workflow does not check out any code; it only validates
  # the PR title via the GitHub API.
  pull_request_target:
    types: [opened, synchronize, reopened, edited]

permissions: {}

jobs:
  validate-pr-title:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - name: PR Conventional Commit Validation
        uses: ytanikin/pr-conventional-commits@639145d78959c53c43112365837e3abd21ed67c1 # 1.5.2
        with:
          task_types: '["feat","fix","docs","test","ci","refactor","perf","chore","revert"]'
```

#### `release-please.yml` (optional)

```yaml
on:
  push:
    branches:
      - main

permissions: {}

name: release-please

jobs:
  release-please:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    outputs:
      release_created: ${{ steps.release.outputs.release_created }}
    steps:
      - uses: actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1 # v3.2.0
        id: app-token
        with:
          app-id: ${{ secrets.DS_RELEASE_BOT_ID }}
          private-key: ${{ secrets.DS_RELEASE_BOT_PRIVATE_KEY }}
          permission-contents: write
          permission-pull-requests: write
      - uses: googleapis/release-please-action@45996ed1f6d02564a971a2fa1b5860e934307cf7 # v5.0.0
        id: release
        with:
          token: ${{ steps.app-token.outputs.token }}
```

**Note:** Some organizations use a GitHub app token for release-please. For a new project, `secrets.GITHUB_TOKEN` is the safe default. If the user has a release bot app, ask whether to configure it instead. When minting an app token with `actions/create-github-app-token`, explicitly set the `permission-*` inputs to the minimum permissions release-please needs instead of inheriting the app installation's full permission set.

- Configure a release-please manifest if release-please was enabled (`release-please-config.json` and `.release-please-manifest.json`). Use git to identify the latest version tag and set the current version in the manifest file so release-please knows where to start when incrementing the version for the next release.

- `release-please-config.json` will look something like this:

```json
{
  "packages": {
    ".": {
      "release-type": "python",
      "changelog-path": "CHANGELOG.md"
    }
  }
}
```

#### `publish-pypi.yml` (opt-in — only create if explicitly requested)

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]
  workflow_dispatch:

permissions: {}

jobs:
  publish-to-pypi:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    environment:
      name: pypi-release
      url: {{PYPI_URL}}
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          persist-credentials: false
      - uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
      - name: Set version from release tag
        if: github.event_name == 'release'
        env:
          VERSION: ${{ github.event.release.tag_name }}
        run: |
          VERSION="${VERSION#v}"
          VERSION="$(echo "$VERSION" | sed 's/-\(a\|alpha\|b\|beta\|rc\)/\1/')"
          sed -i "s/^version = .*/version = \"$VERSION\"/" pyproject.toml
      - run: uv build
      - run: uv publish
```

Replace `{{PYPI_URL}}` with the actual PyPI package URL.

### 4. Create Dependabot Configuration

Create `.github/dependabot.yml` by default:

```yaml
version: 2
updates:
  - package-ecosystem: uv
    cooldown:
      default-days: 7
    directory: "/"
    schedule:
      interval: monthly
    groups:
      all:
        patterns:
          - "*"
    commit-message:
      prefix: "chore(deps):"

  - package-ecosystem: "github-actions"
    directory: "/"
    cooldown:
      default-days: 7
    schedule:
      interval: monthly
    groups:
      all:
        patterns:
          - "*"
    commit-message:
      prefix: "ci(deps):"
```

### 5. Create Pre-commit Configuration

Create or update `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.4
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/tsvikas/sync-with-uv
    rev: v0.5.0
    hooks:
      - id: sync-with-uv
```

If a pre-commit config already exists, merge rather than overwrite. Keep any existing hooks the user has and add ruff if missing.

### 6. Ensure pyproject.toml Has Required Tool Configuration

Read `pyproject.toml`. Ensure these sections exist. Add or merge them without destroying existing configuration.

**Dependency groups:**

```toml
[dependency-groups]
dev = [
    "pytest>=9.0.3",
    "pre-commit>=4.6.0",
    "ruff>=0.15.12",
]
docs = [
    "mkdocs-material>=9.7.6",
    "mkdocstrings[python]>=1.0.3",
]
```

If the project already has a `dev` or `docs` group, append missing entries rather than replacing. If the project does not use mkdocs, ask before adding `docs` dependencies.

**pytest configuration:**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-vv"
```

**ruff lint configuration (minimal sensible defaults):**

```toml
[tool.ruff.lint]
select = ["ALL"]
ignore = [
    "D203",   # incompatible with D211
    "D213",   # incompatible with D212
    "EM101",  # raw string in exception
    "EM102",  # f-string in exception
    "FIX002", # todo statements
    "PYI051", # literal strings redundant with str in type union
    "TD002",  # todo without author name
    "TRY003", # define exceptions in the exception class
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = [
    "ANN001",  # annotation in function argument
    "ANN201",  # return type annotation
    "PLR2004", # Magic value used in comparison
    "S101",    # assert
    "SLF001",  # private member access
    "D",       # docstring
]

```

If the user already has ruff configuration, do not overwrite it. Only add these sections if they are missing.

### 7. Validate the Setup

After writing all files, run:

```bash
# Verify pre-commit works
uv run pre-commit run --all-files

# Verify tests pass
uv run pytest
```

If either fails, report the errors and fix them before declaring success.

Also ask the user to:
- Enable GitHub Pages in repository settings if docs deployment was configured
- Setup trusted publishing if PyPI publishing is enabled


## Rules

- Always read existing files before writing — never blindly overwrite.
- Use `uv` consistently. Do not mix pip, poetry, or other tools unless the project already uses them.
- Pin ALL action references to specific commit hashes with a trailing version comment (e.g. `actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2`). Do not use floating `@vN` tags.
- After creating or editing workflows, run `zizmor .github/workflows/` locally. Fix or suppress all findings before committing. Use `# zizmor: ignore[rule-name]` inline comments (placed on the line *after* a step's `uses:` or `on:` block) with explanatory comments when suppression is appropriate.
- Keep the Python version matrix configurable but default to `["3.12", "3.13", "3.14"]`.
- If the project does not have a `tests/` directory, note this rather than failing — the CI will fail until tests are added.
- Never include a benchmark workflow.
