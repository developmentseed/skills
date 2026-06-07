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

# Resolve the repo from this script's own location so the checkout can live anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
CURATE="$REPO/hooks/curate.py"
VENV_PYTHON="$REPO/.venv/bin/python3"

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

# Guard: if we couldn't parse the fields, bail silently
if [[ -z "$SESSION_ID" || -z "$TRANSCRIPT_PATH" ]]; then
    exit 0
fi

# Guard: refuse to run unconfigured. Without a vault we have no destination, so
# log a marker and exit cleanly. (Plugin users set this via /plugin config; the
# vault_dir userConfig field is marked required, so this path is rare.)
if [[ -z "${CAPTURE_VAULT_DIR:-}" ]]; then
    mkdir -p "$(dirname "$HOOKS_LOG")"
    printf 'CAPTURE_NOT_CONFIGURED\t%s\tCAPTURE_VAULT_DIR unset — set vault_dir in plugin config\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$HOOKS_LOG"
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
        # shellcheck disable=SC2155  # export masks cat's exit code on purpose — a
        # token-read hiccup must not abort this close-path hook under `set -e`.
        export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude_vault_oauth_token")"
    fi
    export CLAUDE_CODE_OAUTH_TOKEN
else
    : "${ANTHROPIC_API_KEY:=${CLAUDE_PLUGIN_OPTION_ANTHROPIC_API_KEY:-}}"
    if [[ -z "${ANTHROPIC_API_KEY:-}" && -f "$HOME/.claude_vault_token" ]]; then
        # shellcheck disable=SC2155  # see rationale above: don't abort the close path
        export ANTHROPIC_API_KEY="$(cat "$HOME/.claude_vault_token")"
    fi
    export ANTHROPIC_API_KEY
fi

# Ground-truth marker BEFORE backgrounding (pre-log crash gap detection)
mkdir -p "$(dirname "$HOOKS_LOG")"
printf 'SESSION_END_RECEIVED\t%s\t%s\n' "$SESSION_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$HOOKS_LOG"

# Choose the interpreter. A pre-built .venv (standalone/dev `uv sync`) wins; an
# installed plugin has none, so fall back to `uv run` with the PEP 723 deps
# declared in curate.py. Subscription mode adds the Agent SDK on top.
if [[ -x "$VENV_PYTHON" ]]; then
    RUN=("$VENV_PYTHON" "$CURATE")
elif command -v uv >/dev/null 2>&1; then
    WITH=()
    if [[ "${CAPTURE_USE_SUBSCRIPTION:-}" == "1" ]]; then
        WITH=(--with "claude-agent-sdk==0.2.89")
    fi
    RUN=(uv run --quiet "${WITH[@]}" "$CURATE")
else
    printf 'CAPTURE_NO_INTERPRETER\t%s\tneither %s nor uv found — install uv (https://docs.astral.sh/uv/)\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$VENV_PYTHON" >> "$HOOKS_LOG"
    exit 0
fi

# Background the worker — detached, stdout/stderr → hooks.log
nohup "${RUN[@]}" "$TRANSCRIPT_PATH" "$SESSION_ID" "$CWD" \
    >>"$HOOKS_LOG" 2>&1 &

exit 0
