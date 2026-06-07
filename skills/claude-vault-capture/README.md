# claude-vault-capture

Automatically turn your [Claude Code](https://claude.com/claude-code) sessions into notes in your [Obsidian](https://obsidian.md) vault. When a session ends, a background job summarizes it and drops a markdown file into your vault's `Inbox/auto/` — so the decisions, runbooks, and gotchas you worked through don't evaporate when you close the terminal.

Nothing runs synchronously on session close (the hook returns in well under 200 ms); all model work is backgrounded. Secrets are scrubbed before anything is sent to a model and again before anything is written to disk.

> **Provenance.** This plugin is adapted from [**lhoupert/claude-vault-capture**](https://github.com/lhoupert/claude-vault-capture) by **Loïc Houpert**, MIT-licensed (see [`LICENSE`](LICENSE)). It has been repackaged here as a Claude Code marketplace plugin: the standalone `install.sh` is replaced by the plugin's hook registration + `userConfig`, and the worker now runs via `uv run` (PEP 723 inline deps) so no separate `uv sync` step is needed. Original authorship is preserved in this repository's commit history.

## What you get

- **Automatic capture** — a `SessionEnd` hook curates one durable artifact per qualifying session (a decision, runbook, gotcha, or spec — or nothing, if the session was low-signal) into `<vault>/Inbox/auto/`, using Sonnet.
- **`/vault-save` skill** — on-demand export of a Claude-generated document (spec, plan, ADR, runbook, note) to `<vault>/claude-docs/` with structured frontmatter, mid-session. Auto-triggers on phrases like "save this to my vault".

## Prerequisites

- Claude Code CLI, installed and in use
- [`uv`](https://docs.astral.sh/uv/) on your `PATH` — the hook launches the Python worker with `uv run`, which builds and caches its environment on first capture (no manual dependency install)
- An Obsidian vault (any location — you point the plugin at it during install)
- An `ANTHROPIC_API_KEY`, **or** a Claude Pro/Max subscription (see [Subscription mode](#subscription-mode))

## Install

```
/plugin marketplace add developmentseed/skills
/plugin install claude-vault-capture@skills
```

When the plugin is enabled, Claude Code prompts for your **Obsidian vault path** (and, optionally, an API key). That's it — the `SessionEnd` hook is registered automatically and the `/vault-save` skill becomes available. Sensitive values (API key, OAuth token) are stored in your OS keychain.

Runtime state (a dedup index and a per-session log) is kept in the plugin's persistent data directory (`${CLAUDE_PLUGIN_DATA}`), which survives plugin updates.

## Verify it's working

After your next Claude Code session ends:

```bash
# Hook fired?
grep SESSION_END_RECEIVED ~/.claude/hooks.log | tail -5

# Files written?
ls "<your-vault>"/Inbox/auto/
```

Sessions are silently skipped when: fewer than 3 user turns, under 1500 chars of user content, a command listed in `CAPTURE_EXCLUDED_COMMANDS` was used (empty by default), or the session is already indexed.

## Configuration

Set via the plugin config prompt (`/plugin` → configure), or override with environment variables:

| Setting / Env var | Default | Effect |
|---|---|---|
| `vault_dir` / `CAPTURE_VAULT_DIR` | — | **Required.** Your Obsidian vault path. |
| `anthropic_api_key` / `ANTHROPIC_API_KEY` | — | API key for metered (default) mode; falls back to `~/.claude_vault_token`. |
| `use_subscription` / `CAPTURE_USE_SUBSCRIPTION` | — | `1` routes model calls through your Claude Pro/Max subscription. |
| `oauth_token` / `CLAUDE_CODE_OAUTH_TOKEN` | — | Subscription auth; falls back to `~/.claude_vault_oauth_token`. |
| `CAPTURE_MAX_EST_TOKENS` | `50000` | Token ceiling before skipping (~200 KB transcript). |
| `CAPTURE_EXCLUDED_COMMANDS` | — | Comma-separated slash commands whose sessions are not captured. |

### Subscription mode

By default the model call hits the metered Messages API (`ANTHROPIC_API_KEY`). Set `use_subscription` to `1` to route it through the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview) and bill it to your Pro/Max plan instead. The hook pulls `claude-agent-sdk` on the fly via `uv run --with`, so no extra install step is needed — but the `claude` CLI must be installed.

Generate a long-lived token in a normal terminal (it opens a browser):

```bash
claude setup-token        # prints a token starting with sk-ant-oat01-…
```

Paste it into the plugin's `oauth_token` config field (stored in your OS keychain), or write it to `~/.claude_vault_oauth_token`.

**Trade-offs:** background captures draw from the *same* rolling rate limit as your interactive Claude Code usage, and `cost_usd` in the log becomes an *estimated* API-equivalent rather than a billed amount.

## Consuming captures: the Inbox contract

This is a capture *engine*. Triaging captured artifacts into structured vault folders (promoting, backlinking, rollups) is intentionally out of scope. An extension consumes:

- **`Inbox/auto/`** — curated artifacts. Filenames: `YYYY-MM-DD-<slug>-<sid8>.md`. Frontmatter includes `session_id`, `created`, `source`, `type`, and `tags`.
- **`${CLAUDE_PLUGIN_DATA}/state/`** — read-only runtime state: `session-index.tsv` (dedup) and `log.md` (per-session JSON-lines: skip reasons, costs, token counts).

To stop the pipeline from archiving an extension's own workflow sessions, set `CAPTURE_EXCLUDED_COMMANDS`.

## Tests

The Python pipeline ships with its test suite (no network, no API key needed):

```bash
uv sync          # dev/test deps
uv run pytest
```

An opt-in live test makes real model calls and is skipped unless `CAPTURE_LIVE_TESTS=1`.

## License

[MIT](LICENSE) © Loïc Houpert. Repackaged as a Claude Code plugin for the Development Seed skills marketplace.
