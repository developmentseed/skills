---
name: space-monkey
description: Sets up developmentseed/space-monkey, an LLM-driven exploratory ("monkey") testing GitHub Action that clicks through a deployed web app adversarially and reports issues. Use when asked to add monkey testing, exploratory testing, or adversarial UI testing to a repo, or to write/improve its context.md.
---

# space-monkey

Wires up [developmentseed/space-monkey](https://github.com/developmentseed/space-monkey) — a reusable GitHub Actions workflow where an LLM agent (OpenCode + Playwright MCP) opens a deployed app in a real browser and tests it adversarially: clicking through pages, submitting invalid forms, probing forbidden routes, watching the console. It writes a report to the job summary and, optionally, a sticky PR comment. It's non-deterministic by design — it explores differently each run — and is a supplement to deterministic tests, not a replacement.

## When to use this

The user wants to add automated exploratory/adversarial testing of a deployed app (staging, preview, or prod) to a repo's CI, without writing scripted browser tests.

## Prerequisites

- The app must already be deployed somewhere reachable by URL (staging, preview deploy, whatever). This is not for testing localhost.
- `developmentseed/space-monkey` is currently a **private** repo, org-wide accessible only within `developmentseed`. For client-org repos it must be made public first (check with the repo owner before assuming this works outside `developmentseed`).
- An [OpenRouter](https://openrouter.ai) API key, stored as the `OPENROUTER_API_KEY` secret in the consuming repo. Recommend the user set a spend limit on the key.

## How to set it up

1. **Check the latest release tag** — pin to an exact semver tag, never a moving major-version ref:
   ```bash
   gh release list --repo developmentseed/space-monkey --limit 1
   ```

2. **Add a workflow file** at `.github/workflows/monkey-test.yml` in the consuming repo, adapted from [examples/consumer-workflow.yml](https://github.com/developmentseed/space-monkey/blob/main/examples/consumer-workflow.yml):

   ```yaml
   name: Monkey Test

   on:
     workflow_dispatch: # always keep this so it can be run manually
     pull_request:
       branches: [staging] # adjust: main, a release branch, or drop for cron only

   permissions:
     contents: read
     pull-requests: write # only needed when pr_comment: true

   jobs:
     monkey-test:
       uses: developmentseed/space-monkey/.github/workflows/monkey-test.yml@v0.1.0
       with:
         base_url: ${{ vars.TEST_TARGET_URL }}
         context: tests/monkey/context.md
         pr_comment: true
       secrets:
         OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
         TEST_CREDENTIALS: ${{ secrets.TEST_CREDENTIALS }}
   ```

   The `on:` trigger belongs to the caller, not space-monkey — ask the user when they want it to run (PRs into a staging branch, a release branch, a cron schedule) rather than guessing.

   **Never use `pull_request_target`** — it exposes secrets to fork PRs. Only `pull_request` or `workflow_dispatch` are safe here.

3. **Set `base_url`** — either a repo/environment variable (`vars.TEST_TARGET_URL`) or a literal URL. No staging/prod distinction is assumed by the action; it just needs something reachable.

4. **Add secrets** in the repo settings (or ask the user to):
   - `OPENROUTER_API_KEY` (required)
   - `TEST_CREDENTIALS` (optional) — free-form text, one test account per line, e.g. `reviewer: alice@example.com / hunter2 (can approve submissions)`. If provided, the agent signs in as each account and probes role boundaries; if omitted, it tests as an anonymous visitor. Warn the user: this can end up visible in the job summary or logs, so use throwaway accounts against non-production deployments only.

5. **Write `context.md`** (path referenced by the `context` input — inline text also works but a file is easier to maintain). This is the highest-leverage part: the base prompt is deliberately generic, and test quality depends on this file. Include:
   - What the app is for, in a sentence, so the agent tests realistic journeys.
   - UI quirks: modals that appear on load, how to sign out, non-obvious flows.
   - Role expectations: what each test account should and should *not* be able to do (the credentials themselves go in `TEST_CREDENTIALS`, not here).
   - Known issues to ignore or deprioritize, so the report isn't noisy with things already tracked.

   Do not invent app-specific quirks — ask the user or read the app's code/docs for real ones instead of guessing plausible-sounding ones.

## Optional: gating merges

By default the job never fails based on findings (non-deterministic tests shouldn't block merges). If the user explicitly wants to gate merges on it, use the `issue_count` output:

```yaml
jobs:
  monkey-test:
    uses: developmentseed/space-monkey/.github/workflows/monkey-test.yml@v0.1.0
    with: { base_url: ${{ vars.TEST_TARGET_URL }} }
    secrets: { OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }} }
  gate:
    needs: monkey-test
    runs-on: ubuntu-latest
    if: needs.monkey-test.outputs.issue_count > 0
    steps:
      - run: exit 1
```

## Reference: inputs, secrets, outputs

| Input | Type | Default | Notes |
|---|---|---|---|
| `base_url` | string | required | URL of the deployed app to test |
| `model` | string | `openrouter/auto` | OpenRouter model ID; default uses auto-routing, so key-level restrictions govern what actually runs |
| `context` | string | `''` | Inline text or a path to a file in the repo |
| `pr_comment` | boolean | `false` | Requires `pull-requests: write` |
| `timeout_minutes` | number | `45` | Job timeout |

| Secret | Required | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | yes | |
| `TEST_CREDENTIALS` | no | See step 4 above |

Output: `issue_count` — number of issues found in the report.

## Where results show up

- Job summary — always, on the run's Actions tab page.
- Sticky PR comment — when `pr_comment: true` and the run has PR context; one comment per PR, updated in place.

## Common mistakes

- Pinning `@main` or a moving tag instead of an exact `@vX.Y.Z` release — there is no moving major-version tag to track.
- Using `pull_request_target` — leaks secrets to fork PRs.
- Skipping `context.md` — the default prompt is generic; without app-specific context the agent wastes time on trivial or irrelevant paths.
- Putting test account credentials directly in `context.md` instead of `TEST_CREDENTIALS`.
- Pointing `base_url` at production with real user data — the agent is adversarial and will act on whatever the account can do.
