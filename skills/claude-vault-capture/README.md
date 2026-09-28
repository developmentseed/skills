# claude-vault-capture

Automatically turn your [Claude Code](https://claude.com/claude-code) sessions into notes in your [Obsidian](https://obsidian.md) vault. When a session ends, a background job summarizes it and drops a markdown file into your vault's `Inbox/auto/` — so the decisions, runbooks, and gotchas you worked through don't evaporate when you close the terminal.

Nothing runs synchronously on session close (the hook returns in well under 200 ms); all model work is backgrounded.

**Before you install, two things to know.** This plugin makes a **paid model call at the end of every qualifying session** — on real usage the median is about **$0.11 per captured session** (Sonnet 5.5 at $2/$10 per MTok; sessions that don't qualify cost nothing, and you can bill to a Pro/Max plan instead — see [Subscription mode](#subscription-mode)). And it **sends your session transcript to the Anthropic API** — your prompts, Claude's replies, and a summary of tool activity including commands run and error output. A regex scrubber redacts common credential shapes first (API keys, tokens, JWTs, `KEY=` assignments, basic-auth URLs), but it is pattern-matching over known formats, **not a guarantee** — it cannot recognise a secret it has no pattern for. If you work with material that must not reach a model API, don't install this.

> **Provenance.** This plugin is adapted from [**developmentseed/claude-vault-capture**](https://github.com/developmentseed/claude-vault-capture) by **Loïc Houpert**, MIT-licensed (see [`LICENSE`](LICENSE)). It has been repackaged here as a Claude Code marketplace plugin: the standalone `install.sh` is replaced by the plugin's hook registration + `userConfig`, and the worker now runs via `uv run` (PEP 723 inline deps) so no separate `uv sync` step is needed. Original authorship is preserved in this repository's commit history.

## What you get

- **Automatic capture** — a `SessionEnd` hook curates one durable artifact per qualifying session (a decision, runbook, gotcha, or spec — or nothing, if the session was low-signal) into `<vault>/Inbox/auto/`, using Sonnet. The curator sees the tool activity too — commands run, files touched, and error output — not just the conversation, so notes capture what actually happened rather than only what was said about it.
- **`/vault-save` skill** — on-demand export of a Claude-generated document (spec, plan, ADR, runbook, note) to `<vault>/claude-docs/` with structured frontmatter, mid-session. Auto-triggers on phrases like "save this to my vault".

## Prerequisites

- Claude Code CLI, installed and in use
- [`uv`](https://docs.astral.sh/uv/) on your `PATH` — the hook launches the Python worker with `uv run`, which builds and caches its environment on first capture (no manual dependency install)
- `python3` on your `PATH` — used to parse the hook payload (present by default on macOS and most Linux distributions)
- An Obsidian vault (any location — you point the plugin at it during install)
- An `ANTHROPIC_API_KEY`, **or** a Claude Pro/Max subscription (see [Subscription mode](#subscription-mode))

## Install

```
/plugin marketplace add developmentseed/skills
/plugin install claude-vault-capture@skills
```

When the plugin is enabled, Claude Code prompts for its configuration. **Two fields are required in practice** — the rest can stay blank:

- **Obsidian vault path** (`vault_dir`) — where notes are written.
- **Credentials** — *either* paste an **Anthropic API key** (`anthropic_api_key`), *or* set **`use_subscription`** to `1` **and** paste an OAuth token (see [Subscription mode](#subscription-mode)).

With no credential the plugin looks installed and its hook fires, but every capture aborts before the model call — **no note, and no entry in the log**. The only trace is a single line in `~/.claude/hooks.log`. This is the most common reason a fresh install appears to do nothing, and it catches Pro/Max users in particular, since they often have no `ANTHROPIC_API_KEY` anywhere.

The `SessionEnd` hook is registered automatically and the `/vault-save` skill becomes available. Sensitive values (API key, OAuth token) are stored in your OS keychain (macOS Keychain; the platform-appropriate secret store elsewhere).

Runtime state (a dedup index and a per-session log) is kept in the plugin's persistent data directory (`${CLAUDE_PLUGIN_DATA}`), which survives plugin updates.

## Verify it's working

The hook fires at session *end*, so this is about your **next** session, not the one you installed in. Make it a substantial one — short sessions are skipped by design.

The log is the only check that distinguishes "working, nothing worth capturing" from "broken". Resolve the state directory first (`${CLAUDE_PLUGIN_DATA}` is set for the hook, not for your shell):

```bash
STATE=~/.claude/plugins/data/claude-vault-capture-skills/state
tail -1 "$STATE/log.md" | python3 -m json.tool
```

`"skip_reason_a": null` means a note was written, and `path_a` names it. Any other value is a skip, and the value tells you which.

> Don't rely on `grep SESSION_END_RECEIVED ~/.claude/hooks.log` alone — that marker is written *before* the worker starts, so it appears even when capture is completely broken. An empty `Inbox/auto/` is equally ambiguous: it's the correct result for a low-signal session.

### Nothing was captured

Check the `skip_reason_a` from the log above:

| `skip_reason_a` | Meaning |
|---|---|
| `threshold` | a very short session: fewer than 3 user-side messages (tool results count) or under 1500 chars of user-side text (your prompts plus injected skill text) — working as intended |
| `model_returned_null` | the model judged the session had no durable artifact — the single most common reason, and normal |
| `duplicate` | that session already reached the model (captured, null, malformed, refused or truncated). Timeouts and errors aren't recorded, so a resumed session retries |
| `excluded_command` | a slash command in `excluded_commands` was used |
| `token_limit` | transcript above `max_est_tokens` |
| `timeout` | the model call exceeded `timeout_seconds` — raise it |
| `malformed_json` | the model didn't return a usable artifact; transient unless it's every session |
| `refusal` / `truncated` | the model declined, or hit its output cap mid-artifact; not retried |
| `transcript_missing` | the transcript file couldn't be read |
| `error:<Type>` | anything else, including a failed note write (e.g. vault unmounted); the message is in `hooks.log` |

**If `log.md` doesn't exist or has no row for the session at all**, the worker never got that far. `grep -E 'CAPTURE_|skipping capture' ~/.claude/hooks.log | tail` names the cause:

| Marker in `hooks.log` | Fix |
|---|---|
| `skipping capture` (no key / no token) | set `anthropic_api_key`, or `use_subscription=1` + `oauth_token` |
| `CAPTURE_TOKEN_FILE_PERMS` | `chmod 600` the credential file it names |
| `CAPTURE_NOT_CONFIGURED` | set `vault_dir` |
| `CAPTURE_VAULT_NOT_ABSOLUTE` | make `vault_dir` an absolute path (`~/…` is expanded) |
| `CAPTURE_BAD_SETTING` | a numeric setting isn't a positive whole number; the default is used |
| `CAPTURE_NO_INTERPRETER` / `CAPTURE_NO_PYTHON3` | install `uv` / `python3` (see Prerequisites) |
| `CAPTURE_HOOK_JSON_UNPARSED` | report it — the hook payload didn't parse |

## Configuration

Set via the plugin config prompt (`/plugin` → configure), or override with environment variables:

| Setting / Env var | Default | Effect |
|---|---|---|
| `vault_dir` / `CAPTURE_VAULT_DIR` | — | **Required.** Absolute path to your Obsidian vault (`~/…` is expanded). |
| `anthropic_api_key` / `ANTHROPIC_API_KEY` | — | API key for metered (default) mode; falls back to `~/.claude_vault_token`. |
| `use_subscription` / `CAPTURE_USE_SUBSCRIPTION` | — | `1` routes model calls through your Claude Pro/Max subscription. |
| `oauth_token` / `CLAUDE_CODE_OAUTH_TOKEN` | — | Subscription auth; falls back to `~/.claude_vault_oauth_token`. |
| `max_est_tokens` / `CAPTURE_MAX_EST_TOKENS` | `50000` | Token ceiling before skipping (~200 KB transcript). |
| `excluded_commands` / `CAPTURE_EXCLUDED_COMMANDS` | — | Comma-separated slash commands whose sessions are not captured. |
| `timeout_seconds` / `CAPTURE_TIMEOUT_SECONDS` | `30` | Hard wall on a single model call (in API mode, per attempt; overloads and 5xx errors are retried twice). Raise it for large sessions or slow links (subscription mode especially) — all model work is backgrounded, so a higher value never delays session close. |
| `CAPTURE_STATE_DIR` | `${CLAUDE_PLUGIN_DATA}/state` | Where the dedup index and per-session log live. Set automatically for plugin installs. |
| `CAPTURE_TOOL_CHARS_BUDGET` | `30000` | Character budget for the tool activity (commands, files touched) summarized alongside the conversation. |
| `CAPTURE_SUCCESS_HEAD_CHARS` | `200` | How much of each successful tool result is kept when rendering that activity. |

### Subscription mode

By default the model call hits the metered Messages API (`ANTHROPIC_API_KEY`). Set `use_subscription` to `1` to route it through the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview) and bill it to your Pro/Max plan instead. The hook pulls `claude-agent-sdk` on the fly via `uv run --with`, so no extra install step is needed — but the `claude` CLI must be installed.

Generate a long-lived token in a normal terminal (it opens a browser):

```bash
claude setup-token        # prints a token starting with sk-ant-oat01-…
```

Paste it into the plugin's `oauth_token` config field (stored in your OS keychain), or write it to `~/.claude_vault_oauth_token`. Token files must be owner-only — the hook refuses group/other-readable credential files:

```bash
(umask 077 && printf '%s\n' "sk-ant-oat01-…" > ~/.claude_vault_oauth_token)
# or, for an existing file: chmod 600 ~/.claude_vault_oauth_token
```

The same applies to the API-key fallback file `~/.claude_vault_token`.

**Trade-offs:** background captures draw from the *same* rolling rate limit as your interactive Claude Code usage, and `cost_usd` in the log becomes an *estimated* API-equivalent rather than a billed amount.

## Consuming captures: the Inbox contract

This is a capture *engine*. Triaging captured artifacts into structured vault folders (promoting, backlinking, rollups) is intentionally out of scope. An extension consumes:

- **`Inbox/auto/`** — curated artifacts. Filenames: `YYYY-MM-DD-<slug>-<sid8>.md`. Frontmatter includes `session_id`, `created`, `source`, `type`, and `tags`.
- **`${CLAUDE_PLUGIN_DATA}/state/`** — read-only runtime state: `session-index.tsv` (dedup) and `log.md` (per-session JSON-lines: skip reasons, costs, token counts).

To stop the pipeline from archiving an extension's own workflow sessions, set `CAPTURE_EXCLUDED_COMMANDS`.

Notes contain model-written text. If you use Templater's "trigger on new file creation", exclude `Inbox/auto/` there, or any `<% %>` in a note runs as a template.

## Turning it off

To pause, disable the plugin in `/plugin`: the `SessionEnd` hook stops and your settings and state are kept.

Uninstalling leaves your notes in `<vault>/Inbox/auto/` and `<vault>/claude-docs/` alone. But by default, uninstalling from the last place the plugin is installed **deletes `${CLAUDE_PLUGIN_DATA}`**: the dedup index and the log. A later reinstall would then re-curate (and re-bill) resumed sessions. Pass `--keep-data` to `claude plugin uninstall` to keep them.

## Tests

The Python pipeline ships with its test suite (no network, no API key needed).
Run it from a **clone of this repo**, from the plugin's own directory (it has its own `pyproject.toml`; `uv sync` from the repo root will not find it):

```bash
cd skills/claude-vault-capture
uv sync          # dev/test deps
uv run pytest
```

An opt-in live test makes real model calls and is skipped unless `CAPTURE_LIVE_TESTS=1`.

## License

[MIT](LICENSE) © Loïc Houpert. Repackaged as a Claude Code plugin for the Development Seed skills marketplace.
