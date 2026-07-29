#!/usr/bin/env bash
# SessionEnd hook entry point — returns in <200ms; all model work is backgrounded.
#
# Runs in two modes from the same file:
#   • Marketplace plugin — config arrives as CLAUDE_PLUGIN_OPTION_* env vars,
#     runtime state lives under ${CLAUDE_PLUGIN_DATA}, and the worker is launched
#     with `uv run` (PEP 723 deps in curate.py; no `uv sync` step required).
#   • Standalone/dev checkout — config from a sourced capture.env and a `.venv`
#     built by `uv sync`. Preferred automatically when that .venv exists.
set -euo pipefail

HOOKS_LOG="$HOME/.claude/hooks.log"

# Print a credential file's contents only if it is owner-only (mode *00); a
# hand-made `echo $TOKEN > file` is 644, i.e. readable by every local user, and
# must not be treated as a usable credential. stat -f is macOS/BSD, -c is GNU.
_read_secret_file() {
    local f="$1" perms
    # -L follows symlinks: a token symlinked to a 600 file would otherwise be
    # stat'd as the link itself (777 on macOS) and refused, with a chmod hint
    # that cannot fix it. GNU -c is probed FIRST because BSD stat rejects it
    # cleanly (rc=1, empty), whereas GNU stat treats -f as "filesystem" and
    # prints a multi-line blob that would land in hooks.log as the mode.
    perms="$(stat -L -c '%a' "$f" 2>/dev/null || stat -L -f '%Lp' "$f" 2>/dev/null)" || return 1
    if [[ "$perms" != *00 ]]; then
        printf 'CAPTURE_TOKEN_FILE_PERMS\t%s\t%s is mode %s (group/other-readable) — refusing to use it; run: chmod 600 %s\n' \
            "${NOW:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}" "$f" "$perms" "$f" >> "$HOOKS_LOG"
        return 1
    fi
    cat "$f"
}

# Resolve the repo from this script's own location so the checkout can live anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
CURATE="$REPO/hooks/curate.py"
VENV_PYTHON="$REPO/.venv/bin/python3"

# Every branch below may log; guarantee the destination and one coherent
# timestamp up front (each $(date) is a fork — this is the <200ms close path).
mkdir -p "$(dirname "$HOOKS_LOG")"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Legacy/standalone config file (pre-plugin installs). Plugin installs instead
# pass config through CLAUDE_PLUGIN_OPTION_* env vars (handled just below).
if [[ -f "$REPO/capture.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO/capture.env"
    set +a
fi

# Plugin user-config → the env vars curate.py already understands. `:=` only fills
# a value that isn't already set (so capture.env / a real env var still win).
: "${CAPTURE_VAULT_DIR:=${CLAUDE_PLUGIN_OPTION_VAULT_DIR:-}}"
: "${CAPTURE_USE_SUBSCRIPTION:=${CLAUDE_PLUGIN_OPTION_USE_SUBSCRIPTION:-}}"
export CAPTURE_VAULT_DIR CAPTURE_USE_SUBSCRIPTION

# Timeout is exported only when set to a plain integer. curate.py reads it with
# a *string* default — os.environ.get("CAPTURE_TIMEOUT_SECONDS", "30") — so an
# empty or non-numeric value is a ValueError at import, i.e. a silent no-capture,
# rather than a fallback to 30. Reject junk here and log it instead.
: "${CAPTURE_TIMEOUT_SECONDS:=${CLAUDE_PLUGIN_OPTION_TIMEOUT_SECONDS:-}}"
if [[ -n "${CAPTURE_TIMEOUT_SECONDS:-}" ]]; then
    if [[ "$CAPTURE_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]]; then
        export CAPTURE_TIMEOUT_SECONDS
    else
        printf 'CAPTURE_BAD_TIMEOUT\t%s\ttimeout_seconds=%s is not an integer — using the 30s default\n' \
            "$NOW" "$CAPTURE_TIMEOUT_SECONDS" >> "$HOOKS_LOG"
        unset CAPTURE_TIMEOUT_SECONDS
    fi
fi

# Runtime state (dedup index, per-session log, scrub-failure log): prefer the
# plugin's persistent data dir, which survives plugin updates. Standalone use
# falls back to the in-repo eval/state default baked into curate.py / scrub.py.
if [[ -n "${CLAUDE_PLUGIN_DATA:-}" ]]; then
    export CAPTURE_STATE_DIR="$CLAUDE_PLUGIN_DATA/state"
    export SCRUB_FAILURES_PATH="$CLAUDE_PLUGIN_DATA/state/scrub-failures.md"
    mkdir -p "$CLAUDE_PLUGIN_DATA/state"
fi

# Read hook JSON from stdin
HOOK_JSON=$(cat)

# Extract fields
TRANSCRIPT_PATH=$(echo "$HOOK_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('transcript_path',''))" 2>/dev/null || true)
SESSION_ID=$(echo "$HOOK_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null || true)
CWD=$(echo "$HOOK_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null || true)

# Guard: if we couldn't parse the fields, log why and bail. This also covers a
# missing python3 (the three extractions above all fail silently), which would
# otherwise be indistinguishable from "the hook never fired" in hooks.log.
if [[ -z "$SESSION_ID" || -z "$TRANSCRIPT_PATH" ]]; then
    if command -v python3 >/dev/null 2>&1; then
        printf 'CAPTURE_HOOK_JSON_UNPARSED\t%s\tno session_id/transcript_path in hook JSON\n' \
            "$NOW" >> "$HOOKS_LOG"
    else
        printf 'CAPTURE_NO_PYTHON3\t%s\tpython3 not on PATH — cannot parse the hook payload\n' \
            "$NOW" >> "$HOOKS_LOG"
    fi
    exit 0
fi

# Guard: refuse to run unconfigured. Without a vault we have no destination, so
# log a marker and exit cleanly. (Plugin users set this via /plugin config; the
# vault_dir userConfig field is marked required, so this path is rare.)
if [[ -z "${CAPTURE_VAULT_DIR:-}" ]]; then
    printf 'CAPTURE_NOT_CONFIGURED\t%s\tCAPTURE_VAULT_DIR unset — set vault_dir in plugin config\n' \
        "$NOW" >> "$HOOKS_LOG"
    exit 0
fi

# Claude Code sanitizes its environment before spawning hooks, so credentials are
# often absent even when the desktop app has them. Resolve from plugin config,
# then fall back to token files.
if [[ "${CAPTURE_USE_SUBSCRIPTION:-}" == "1" ]]; then
    # Subscription mode: the Claude Agent SDK authenticates with this OAuth token
    # (generate it once with `claude setup-token`; stored in the OS keychain when
    # supplied via the sensitive oauth_token plugin config field).
    : "${CLAUDE_CODE_OAUTH_TOKEN:=${CLAUDE_PLUGIN_OPTION_OAUTH_TOKEN:-}}"
    if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" && -f "$HOME/.claude_vault_oauth_token" ]]; then
        # shellcheck disable=SC2155  # export masks the helper's exit code on purpose —
        # a token-read failure (including bad perms) must not abort this close-path
        # hook under `set -e`; it just leaves the token empty.
        export CLAUDE_CODE_OAUTH_TOKEN="$(_read_secret_file "$HOME/.claude_vault_oauth_token")"
    fi
    export CLAUDE_CODE_OAUTH_TOKEN
else
    : "${ANTHROPIC_API_KEY:=${CLAUDE_PLUGIN_OPTION_ANTHROPIC_API_KEY:-}}"
    if [[ -z "${ANTHROPIC_API_KEY:-}" && -f "$HOME/.claude_vault_token" ]]; then
        # shellcheck disable=SC2155  # see rationale above: don't abort the close path
        export ANTHROPIC_API_KEY="$(_read_secret_file "$HOME/.claude_vault_token")"
    fi
    export ANTHROPIC_API_KEY
fi

# Ground-truth marker BEFORE backgrounding (pre-log crash gap detection)
printf 'SESSION_END_RECEIVED\t%s\t%s\n' "$SESSION_ID" "$NOW" >> "$HOOKS_LOG"

# Deploy identity: the June–July timeout outage was a checkout stuck behind
# origin/main, so the running code silently wasn't the merged code. Log which
# version produced every capture so drift is visible in hooks.log. Exactly one
# CAPTURE_DEPLOY line per session in either mode.
if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then
    # Installed plugin: the plugin version is the authoritative identity, and
    # git would be actively misleading — $REPO is rarely a git root, and `git -C`
    # walks UP, so it would describe whatever repo encloses the plugin (the
    # marketplace clone, or an unrelated repo someone vendored it into) and
    # compare against THAT repo's origin/main, reporting false STALE_DEPLOYs.
    # `|| true`: under `set -euo pipefail` a missing/unreadable plugin.json makes
    # sed exit non-zero, and that would abort the hook — skipping the capture
    # entirely over a cosmetic log line. ${...:-unknown} covers the empty result.
    PLUGIN_VERSION="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
        "$REPO/.claude-plugin/plugin.json" 2>/dev/null | head -1 || true)"
    printf 'CAPTURE_DEPLOY\tv%s\tplugin\t%s\n' "${PLUGIN_VERSION:-unknown}" \
        "$NOW" >> "$HOOKS_LOG"
else
    # Standalone/dev checkout: log the running SHA and flag when the last-fetched
    # origin/main is not an ancestor of HEAD. Local-only git ops — never fetch on
    # the close path.
    DEPLOY_SHA="$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    DEPLOY_STATE="ok"
    if [[ "$DEPLOY_SHA" == "unknown" ]]; then
        DEPLOY_STATE="unknown"
    elif git -C "$REPO" rev-parse --verify -q origin/main >/dev/null 2>&1 \
        && ! git -C "$REPO" merge-base --is-ancestor origin/main HEAD 2>/dev/null; then
        DEPLOY_STATE="STALE_DEPLOY(behind origin/main as last fetched)"
    fi
    printf 'CAPTURE_DEPLOY\t%s\t%s\t%s\n' "$DEPLOY_SHA" "$DEPLOY_STATE" \
        "$NOW" >> "$HOOKS_LOG"
fi

# Choose the interpreter. A pre-built .venv (standalone/dev `uv sync`) wins, but
# ONLY outside a plugin install: running `uv sync` inside an installed plugin (as
# the README's own Tests section invites) leaves a .venv holding just the dev
# group, which would then shadow the PEP 723 deps and silently break subscription
# mode — that venv has no claude-agent-sdk, and `--with` is only passed on the uv
# path. An installed plugin therefore always goes through `uv run`.
if [[ -z "${CLAUDE_PLUGIN_ROOT:-}" && -x "$VENV_PYTHON" ]]; then
    RUN=("$VENV_PYTHON" "$CURATE")
elif command -v uv >/dev/null 2>&1; then
    # Build RUN incrementally: expanding an empty array via "${ARR[@]}" is an
    # "unbound variable" error under `set -u` on bash < 4.4, and macOS ships 3.2 —
    # a single interpolated array here killed every marketplace-install capture.
    RUN=(uv run --quiet)
    if [[ "${CAPTURE_USE_SUBSCRIPTION:-}" == "1" ]]; then
        RUN+=(--with "claude-agent-sdk==0.2.89")
    fi
    RUN+=("$CURATE")
else
    printf 'CAPTURE_NO_INTERPRETER\t%s\tneither %s nor uv found — install uv (https://docs.astral.sh/uv/)\n' \
        "$NOW" "$VENV_PYTHON" >> "$HOOKS_LOG"
    exit 0
fi

# Background the worker — detached, stdout/stderr → hooks.log
nohup "${RUN[@]}" "$TRANSCRIPT_PATH" "$SESSION_ID" "$CWD" \
    >>"$HOOKS_LOG" 2>&1 &

exit 0
