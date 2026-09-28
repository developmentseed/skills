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

# Print a credential file only if it is owner-only (mode *00); a hand-made
# `echo $TOKEN > file` is 644, readable by every local user.
_read_secret_file() {
    local f="$1" perms
    # -L: judge the symlink target. GNU -c first: GNU stat misreads BSD's -f.
    perms="$(stat -L -c '%a' "$f" 2>/dev/null || stat -L -f '%Lp' "$f" 2>/dev/null)" || return 1
    if [[ "$perms" != *00 ]]; then
        printf 'CAPTURE_TOKEN_FILE_PERMS\t%s\t%s is mode %s (group/other-readable) — refusing to use it; run: chmod 600 %s\n' \
            "$NOW" "$f" "$perms" "$f" >> "$HOOKS_LOG"
        return 1
    fi
    cat "$f"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
CURATE="$REPO/hooks/curate.py"
VENV_PYTHON="$REPO/.venv/bin/python3"

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

# Export numeric settings only when they are positive integers: curate.py would
# crash on int("") or int("2 minutes"), and 0 would time out or skip everything.
_export_int_setting() {
    local name="$1" value
    value="${!name:-}"
    if [[ -z "$value" ]]; then
        unset "$name"  # an exported-but-empty value (e.g. from capture.env) too
        return 0
    fi
    if [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
        export "${name?}"
    else
        printf 'CAPTURE_BAD_SETTING\t%s\t%s=%s is not a positive whole number — using the default\n' \
            "$NOW" "$name" "$value" >> "$HOOKS_LOG"
        unset "$name"
    fi
}

: "${CAPTURE_TIMEOUT_SECONDS:=${CLAUDE_PLUGIN_OPTION_TIMEOUT_SECONDS:-}}"
_export_int_setting CAPTURE_TIMEOUT_SECONDS

: "${CAPTURE_MAX_EST_TOKENS:=${CLAUDE_PLUGIN_OPTION_MAX_EST_TOKENS:-}}"
_export_int_setting CAPTURE_MAX_EST_TOKENS

: "${CAPTURE_EXCLUDED_COMMANDS:=${CLAUDE_PLUGIN_OPTION_EXCLUDED_COMMANDS:-}}"
export CAPTURE_EXCLUDED_COMMANDS

# Runtime state goes in the plugin data dir (survives updates); standalone uses eval/state.
if [[ -n "${CLAUDE_PLUGIN_DATA:-}" ]]; then
    export CAPTURE_STATE_DIR="$CLAUDE_PLUGIN_DATA/state"
    export SCRUB_FAILURES_PATH="$CLAUDE_PLUGIN_DATA/state/scrub-failures.md"
    mkdir -p "$CLAUDE_PLUGIN_DATA/state"
fi

# Parse the hook JSON from stdin in one python3 call; fields are joined with \x1f
# (a non-whitespace IFS char, so an empty field doesn't shift the others).
FIELDS=$(python3 -c "import json,sys; d=json.load(sys.stdin); print('\x1f'.join(str(d.get(k) or '') for k in ('transcript_path','session_id','cwd')))" 2>/dev/null || true)
IFS=$'\x1f' read -r TRANSCRIPT_PATH SESSION_ID CWD <<<"$FIELDS" || true

# Guard: if we couldn't parse the fields (or python3 is missing), log why and bail.
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

# Guard: no vault, no destination — log and exit.
if [[ -z "${CAPTURE_VAULT_DIR:-}" ]]; then
    printf 'CAPTURE_NOT_CONFIGURED\t%s\tCAPTURE_VAULT_DIR unset — set vault_dir in plugin config\n' \
        "$NOW" >> "$HOOKS_LOG"
    exit 0
fi
# Config values arrive unexpanded; a relative path would resolve inside the
# session's project directory, so expand ~ and refuse anything else relative.
CAPTURE_VAULT_DIR="${CAPTURE_VAULT_DIR/#\~/$HOME}"
if [[ "$CAPTURE_VAULT_DIR" != /* ]]; then
    printf 'CAPTURE_VAULT_NOT_ABSOLUTE\t%s\tvault_dir %s is not an absolute path\n' \
        "$NOW" "$CAPTURE_VAULT_DIR" >> "$HOOKS_LOG"
    exit 0
fi

# Claude Code sanitizes its environment before spawning hooks, so credentials are
# often absent even when the desktop app has them. Resolve from plugin config,
# then fall back to token files.
if [[ "${CAPTURE_USE_SUBSCRIPTION:-}" == "1" ]]; then
    # OAuth token from `claude setup-token`.
    : "${CLAUDE_CODE_OAUTH_TOKEN:=${CLAUDE_PLUGIN_OPTION_OAUTH_TOKEN:-}}"
    if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" && -f "$HOME/.claude_vault_oauth_token" ]]; then
        # shellcheck disable=SC2155  # masking the exit code is deliberate: a failed
        # read (e.g. bad perms) must leave the token empty, not abort under set -e.
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

# Log which code version handles each session, so a stale deploy shows in hooks.log.
if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then
    # Plugin: use the plugin version; `git -C` would describe the enclosing repo.
    # `|| true` so a missing plugin.json can't abort the hook under pipefail.
    PLUGIN_VERSION="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
        "$REPO/.claude-plugin/plugin.json" 2>/dev/null | head -1 || true)"
    printf 'CAPTURE_DEPLOY\tv%s\tplugin\t%s\n' "${PLUGIN_VERSION:-unknown}" \
        "$NOW" >> "$HOOKS_LOG"
else
    # Standalone checkout: flag HEAD behind the last-fetched origin/main (no fetch).
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

# Choose the interpreter. A standalone .venv wins, but never inside a plugin
# install: a dev `uv sync` venv there lacks claude-agent-sdk and would shadow uv run.
if [[ -z "${CLAUDE_PLUGIN_ROOT:-}" && -x "$VENV_PYTHON" ]]; then
    RUN=("$VENV_PYTHON" "$CURATE")
elif command -v uv >/dev/null 2>&1; then
    # Built incrementally: "${EMPTY[@]}" is an unbound-variable error under
    # set -u on macOS's bash 3.2.
    RUN=(uv run --quiet)
    if [[ "${CAPTURE_USE_SUBSCRIPTION:-}" == "1" ]]; then
        RUN+=(--with "claude-agent-sdk==0.2.161")
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
