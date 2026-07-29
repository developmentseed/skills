#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["anthropic==0.105.2"]
# ///
# PEP 723 inline metadata: when this plugin is installed via the Claude Code
# marketplace there is no pre-built virtualenv, so the SessionEnd hook launches
# this worker with `uv run`, which builds (and caches) the environment above on
# first use. Standalone/dev checkouts that ran `uv sync` use `.venv` instead and
# ignore this block. Subscription mode adds `claude-agent-sdk` via `uv run --with`.
"""curate.py — sessionEnd hook worker.

Usage: curate.py <transcript_path> <session_id> <cwd>

Runs the curation path (Path A, sonnet) — extracts a durable artifact or null,
resampling once on a non-deterministic null or an unparseable reply — writes it
to the Obsidian Inbox, and appends to the eval state log. (The *_a naming
survives from a retired A/B experiment — Path B, a Haiku raw baseline, lost and
was removed upstream 2026-06-04 — and is kept for log-schema compatibility.)

All errors go to stderr / ~/.claude/hooks.log — never to the user's terminal.
"""

import sys
import os
import json
import re
import pathlib
import fcntl
import threading
import datetime
import unicodedata
import subprocess

# ── constants ──────────────────────────────────────────────────────────────────

# Default token ceiling; the env var of the same name overrides it at call time
# (see is_above_token_limit), so this constant is the single home of the literal.
CAPTURE_MAX_EST_TOKENS: int = 50000

# Slash commands whose sessions are NOT captured. Empty by default — the public
# pipeline archives everything. Set CAPTURE_EXCLUDED_COMMANDS (env var or
# capture.env) to skip capturing specific workflows' sessions.
EXCLUDED_COMMANDS: list[str] = [
    c.strip()
    for c in os.environ.get("CAPTURE_EXCLUDED_COMMANDS", "").split(",")
    if c.strip()
]

# Repo root is derived from this file's location, so the checkout can live anywhere.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Runtime state (dedup index + per-session log) lives under eval/state by default.
# As an installed plugin there is no writable repo dir, so session-end-capture.sh
# sets CAPTURE_STATE_DIR to the plugin's persistent data dir (${CLAUDE_PLUGIN_DATA}),
# which survives plugin updates. Tests pass explicit log_path/index_path and are
# unaffected by either default.
STATE_DIR = pathlib.Path(
    os.environ.get("CAPTURE_STATE_DIR") or (REPO_ROOT / "eval" / "state")
)

# The vault location is user-specific — there is no universal default. It is set via
# the CAPTURE_VAULT_DIR env var: plugin installs map it from the vault_dir plugin
# config (CLAUDE_PLUGIN_OPTION_VAULT_DIR), standalone checkouts from a sourced
# capture.env — both handled by session-end-capture.sh before launching this script.
# The fallback below only applies when curate.py is run by hand without config;
# the hook refuses to launch when the vault is unconfigured, so the real hook path
# always provides an explicit value.
VAULT_DIR = pathlib.Path(
    os.environ.get("CAPTURE_VAULT_DIR") or (pathlib.Path.home() / "Obsidian")
)
LOG_PATH = STATE_DIR / "log.md"
INDEX_PATH = STATE_DIR / "session-index.tsv"
HOOKS_LOG = pathlib.Path.home() / ".claude" / "hooks.log"

MODEL_A = "claude-sonnet-4-6"
MAX_TOKENS_A = 2000
# Hard wall on a single model call. Overridable via CAPTURE_TIMEOUT_SECONDS for
# environments with large sessions or slow links (e.g. subscription mode, where a
# big transcript can take longer than the 30s default). All model work is
# backgrounded off the SessionEnd close path, so a higher value never delays a session.
TIMEOUT_SECONDS: int = int(os.environ.get("CAPTURE_TIMEOUT_SECONDS", "30"))
# Shared resample budget for BOTH non-deterministic reply failures: a `null` that
# a second call would have answered with a real artifact, and an unparseable reply
# (prose instead of JSON). One resample recovers those misses at zero precision
# cost — a genuinely empty session re-nulls. Resample tokens are folded into the
# usage totals so cost accounting stays accurate.
PATH_A_RESAMPLES = 1

LOG_REQUIRED_KEYS = [
    "schema_version",
    "timestamp",
    "date",
    "session_id",
    "path_a",
    "skip_reason_a",
    "tokens_in_a",
    "tokens_out_a",
    "cost_usd_a",
    "redactions",
]

_STATE_LOCK = threading.Lock()  # guards both log.md and session-index.tsv

# ── title sanitization ─────────────────────────────────────────────────────────

_BAD_CHARS_RE = re.compile(r"[\|\[\]#`\x00-\x1f\x7f]")
_MULTI_SPACE_RE = re.compile(r"\s+")


def sanitize_title(title: str) -> str:
    """Strip chars unsafe in Obsidian wikilinks; collapse whitespace; truncate to 120."""
    return sanitize_summary(title, max_len=120)


def sanitize_summary(s: str, max_len: int = 140) -> str:
    """Strip chars unsafe in Obsidian wikilinks; collapse whitespace; truncate."""
    s = _BAD_CHARS_RE.sub(" ", s)
    s = _MULTI_SPACE_RE.sub(" ", s)
    s = s.strip()
    return s[:max_len]


# Model-supplied frontmatter fields are hostile input (the transcript can carry
# prompt injection): `type` is allowlisted, tags are collapsed to inert slugs.
_ALLOWED_TYPES = {"decision", "runbook", "gotcha", "spec"}
_TAG_BAD_RE = re.compile(r"[^a-z0-9-]+")


def sanitize_type(fm_type) -> str:
    """Collapse anything off the artifact-type allowlist to 'decision'."""
    # isinstance guard: an unhashable model value (list/dict) must not raise
    return fm_type if isinstance(fm_type, str) and fm_type in _ALLOWED_TYPES else "decision"


def sanitize_tag(tag) -> str:
    """Coerce a model-supplied tag to a [a-z0-9-] slug (max 40 chars, may be '')."""
    s = unicodedata.normalize("NFKD", str(tag))
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    s = _TAG_BAD_RE.sub("-", s)
    return s.strip("-")[:40]


# ── slug generation ────────────────────────────────────────────────────────────

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_CODE_FENCE_RE = re.compile(
    r"(?:^|\n)\s*`{3,}(?:[Jj][Ss][Oo][Nn])?\s*\n(.*?)\n\s*`{3,}\s*(?:\n|$)",
    re.DOTALL,
)


def _strip_fences(text: str) -> str:
    """Strip optional markdown code fences the model sometimes wraps around JSON."""
    m = _CODE_FENCE_RE.search(text)
    return m.group(1).strip() if m else text


# The artifact contract from prompts/curation-system-prompt.md. Required on the
# salvage path so a stray JSON-looking object in prose can't be written as an
# artifact: a reply that continued the conversation once contained a fabricated
# `[TOOL] Read: {"file_path": …}` line, which parsed as a dict and would have
# been written to Inbox/ as an empty "untitled" note (the write path fills every
# field with a default).
_ARTIFACT_KEYS = frozenset({"title", "type", "body"})


def _is_artifact(obj) -> bool:
    """True when *obj* satisfies the artifact contract: the three keys, as strings.

    Applied to the directly-parsed reply as well as to salvaged objects. The
    write path substitutes defaults for missing fields but assumes strings for
    the ones present, so a `body` that arrives as a dict or a `title` as a number
    raises mid-write — after the model call is already paid for, and before
    _append_index/append_log run, which loses the session with no log.md row at
    all. Rejecting it here routes it through the normal resample-then-
    malformed_json path, which is logged.
    """
    return isinstance(obj, dict) and all(
        isinstance(obj.get(k), str) for k in _ARTIFACT_KEYS
    )


def _salvage_artifact(raw: str) -> dict | None:
    """Extract the artifact object from a reply that isn't bare JSON.

    Scans every `{` offset with raw_decode and keeps the LAST object that is
    artifact-shaped. Scanning beats a find('{')..rfind('}') window, which spans
    the first brace to the last anywhere in the reply: prose ahead of the
    artifact containing any `{` (a fabricated tool call, a code sample) moved
    the window's start and destroyed an otherwise-valid artifact. Last-wins
    because the artifact is the reply's conclusion — quoted examples come first.

    Shape means the three contract keys present AND holding strings: the write
    path substitutes defaults for missing fields but assumes strings for the
    ones present, so a mined object with a null or numeric title would raise
    mid-write. Salvage is a recovery path — it must not widen what reaches disk.
    """
    decoder = json.JSONDecoder()
    found: dict | None = None
    for idx, ch in enumerate(raw):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(raw, idx)
        except (json.JSONDecodeError, RecursionError):
            # Both mean "no artifact starts here" — deeply nested prose JSON can
            # exhaust the stack, and letting that escape would drop the usage
            # accounting the caller attaches on the way out.
            continue
        if _is_artifact(obj):
            found = obj
    return found


def make_slug(title: str) -> str:
    """Derive a deterministic URL-safe slug from *title* (max 60 chars)."""
    # NFKD-normalize and strip non-ASCII
    s = unicodedata.normalize("NFKD", sanitize_title(title))
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    # Replace runs of non-alnum with dash
    s = _NON_ALNUM_RE.sub("-", s)
    # Strip leading/trailing dashes
    s = s.strip("-")

    if not s:
        return "untitled"

    # Truncate to 60 at a dash boundary where possible
    if len(s) > 60:
        truncated = s[:60]
        # Walk back to last dash
        last_dash = truncated.rfind("-")
        if last_dash > 0:
            truncated = truncated[:last_dash]
        s = truncated.strip("-")

    return s or "untitled"


def make_filename(date_str: str, slug: str, session_id: str) -> str:
    """Return YYYY-MM-DD-<slug>-<sid8>.md"""
    sid8 = session_id[:8]
    return f"{date_str}-{slug}-{sid8}.md"


# ── frontmatter rendering ──────────────────────────────────────────────────────


def render_frontmatter(
    *,
    title: str,
    fm_type: str,
    project: str,
    tags: list[str],
    source: str,
    session_id: str,
    created: str,
    model: str,
    cost_usd: float | None,
    redactions: dict[str, int],
) -> str:
    """Render YAML frontmatter block. Title is sanitized inside here.

    Every string scalar goes through json.dumps: a JSON string is valid YAML
    and inert, so a title like "Decision: use X" (the house style) or any
    residual ':'/'#'/quote in a model-supplied value cannot break parsing or
    inject keys. Obsidian/pyyaml both read the quoted form identically.
    """
    clean_title = sanitize_title(title)

    def q(v) -> str:
        return json.dumps(str(v), ensure_ascii=False)

    tags_yaml = "[" + ", ".join(q(t) for t in tags) + "]"
    redact_yaml = "{" + ", ".join(f"{q(k)}: {int(v)}" for k, v in redactions.items()) + "}"
    cost_str = f"{cost_usd:.4f}" if cost_usd is not None else "null"
    return (
        f"---\n"
        f"title: {q(clean_title)}\n"
        f"type: {q(fm_type)}\n"
        f"project: {q(project)}\n"
        f"tags: {tags_yaml}\n"
        f"source: {q(source)}\n"
        f"session_id: {q(session_id)}\n"
        f"created: {created}\n"
        f"model: {q(model)}\n"
        f"cost_usd: {cost_str}\n"
        f"redactions: {redact_yaml}\n"
        f"---\n"
    )


# ── dedup ──────────────────────────────────────────────────────────────────────


def is_duplicate_session(
    session_id: str,
    *,
    index_path: pathlib.Path | None = None,
) -> bool:
    """Return True if session_id already appears in the index TSV."""
    if index_path is None:
        index_path = INDEX_PATH
    if not index_path.exists():
        return False
    with open(index_path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            cols = line.rstrip("\n").split("\t")
            if cols and cols[0] == session_id:
                return True
    return False


# ── threshold check ────────────────────────────────────────────────────────────


def is_below_threshold(messages: list[dict]) -> bool:
    """< 3 user turns OR < 1500 chars of user content → True (skip)."""
    user_turns = [m for m in messages if m.get("role") == "user"]
    user_chars = sum(len(m.get("content", "")) for m in user_turns)
    return len(user_turns) < 3 or user_chars < 1500


def uses_excluded_command(
    messages: list[dict],
    excluded_commands: list[str] | None = None,
) -> bool:
    """Return True if any user turn invokes an excluded slash command.

    Matches only when the command appears at the start of a line (possibly
    preceded by whitespace), so mentions of the command in prose are ignored.
    """
    if excluded_commands is None:
        excluded_commands = EXCLUDED_COMMANDS
    patterns = [
        re.compile(r"(?m)^\s*" + re.escape(cmd) + r"(?:\s|$)")
        for cmd in excluded_commands
    ]
    for msg in messages:
        if msg.get("role") != "user":
            continue
        text = msg.get("content", "")
        if any(p.search(text) for p in patterns):
            return True
    return False


# ── token guard ────────────────────────────────────────────────────────────────


def is_above_token_limit(text: str) -> bool:
    """True if estimated token count exceeds CAPTURE_MAX_EST_TOKENS."""
    limit = int(os.environ.get("CAPTURE_MAX_EST_TOKENS", str(CAPTURE_MAX_EST_TOKENS)))
    return len(text) // 4 > limit


# ── project derivation ─────────────────────────────────────────────────────────


def derive_project(cwd: str) -> str:
    """Return nearest git repo basename, or 'home' if not in a repo."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return pathlib.Path(result.stdout.strip()).name
    except Exception:
        pass
    return "home"


# ── log building ───────────────────────────────────────────────────────────────


def build_log_entry(
    *,
    session_id: str,
    skip_reason_a: str | None,
    redactions: dict[str, int],
    path_a: str | None = None,
    tokens_in_a: int | None = None,
    tokens_out_a: int | None = None,
    cost_usd_a: float | None = None,
) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        # schema_version 2: single-path capture (Path B retired 2026-06-04). v1
        # rows carry path_b/*_b fields; readers must tolerate their absence in v2.
        "schema_version": 2,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date": now.strftime("%Y-%m-%d"),
        "session_id": session_id,
        "path_a": path_a,
        "skip_reason_a": skip_reason_a,
        "tokens_in_a": tokens_in_a,
        "tokens_out_a": tokens_out_a,
        "cost_usd_a": cost_usd_a,
        "redactions": redactions,
    }


# ── concurrent-safe append ────────────────────────────────────────────────────


def append_log(entry: dict, *, log_path: pathlib.Path | None = None) -> None:
    """Append one JSON line to log_path with cross-process flock + in-process lock.

    log_path resolves to the module-level LOG_PATH at call time (not frozen as a
    default arg) so tests that monkeypatch curate.LOG_PATH are honored even for
    call sites that don't thread an explicit path — main()'s transcript_missing
    logging wrote 6 test rows into the live W30 log via the frozen default.
    """
    if log_path is None:
        log_path = LOG_PATH
    line = json.dumps(entry) + "\n"
    with _STATE_LOCK:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(line)
            fh.flush()
            fcntl.flock(fh, fcntl.LOCK_UN)


def _log_skip(
    session_id: str,
    reason: str,
    redactions: dict[str, int],
    *,
    log_path: pathlib.Path | None = None,
) -> None:
    """Log a no-capture outcome. Every skip must reach log.md — unlogged skips
    are invisible to the weekly no-capture alarm."""
    append_log(
        build_log_entry(
            session_id=session_id, skip_reason_a=reason, redactions=redactions
        ),
        log_path=log_path,
    )


def _append_index(
    session_id: str,
    path_a: str | None,
    date_str: str,
    *,
    index_path: pathlib.Path | None = None,
) -> None:
    """Append one line to session-index.tsv, creating the file with header if absent."""
    if index_path is None:
        index_path = INDEX_PATH
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with _STATE_LOCK:
        with open(index_path, "a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            if fh.tell() == 0:
                # schema_version 2: path_b column dropped with Path B retirement.
                fh.write("# schema_version: 2\n")
            fh.write(f"{session_id}\t{path_a or 'null'}\t{date_str}\n")
            fh.flush()
            fcntl.flock(fh, fcntl.LOCK_UN)


# ── API call stubs (overridable in tests) ─────────────────────────────────────


def _use_subscription() -> bool:
    """True when model calls should route through the Claude Max subscription
    (Claude Agent SDK) instead of the metered Messages API."""
    return os.environ.get("CAPTURE_USE_SUBSCRIPTION") == "1"


# Appended after the transcript on every model call, by BOTH transports, because
# _invoke_model adds it before dispatch. Terminating the transcript is what keeps
# the model curating: without a closing delimiter and a restated contract, the
# prompt is an unfinished chat log — an opening delimiter, then tens of thousands
# of tokens of [USER]:/[ASSISTANT]: dialogue ending mid-thought on an assistant
# turn. The most recent signal is then "an unfinished conversation", and the model
# writes its next turn instead of an artifact: observed in production emitting
# fabricated [TOOL] lines in render_transcript's own syntax, and inventing an
# "END TRANSCRIPT" delimiter it was never given. Measured on the two transcripts
# that failed this way: 3/6 continuations without this tail, 0/7 with it.
_TRANSCRIPT_TAIL = (
    "\n----- END OF TRANSCRIPT -----\n"
    "The transcript above is finished input data, not a conversation to continue. "
    "Do not write the next turn of it. Reply now with your entire response being "
    "either one JSON object starting with `{` or the single word null.\n"
)


def _invoke_model(
    model: str, max_tokens: int, system_prompt: str, user_text: str
) -> tuple[str, int | None, int | None]:
    """Single-shot request. Returns (raw_text, tokens_in, tokens_out).

    Routes through the Claude Max subscription when CAPTURE_USE_SUBSCRIPTION=1,
    otherwise the metered Anthropic Messages API. Both transports raise
    TimeoutError on a >TIMEOUT_SECONDS call, which run_capture maps to the
    `timeout` skip reason. Token counts are None when the transport could not
    observe usage (the subscription salvage path) — never a fabricated 0.

    _TRANSCRIPT_TAIL is appended HERE, once, so neither transport can ship an
    unterminated transcript — the failure mode that made the model continue the
    conversation instead of curating it.
    """
    user_text = user_text + _TRANSCRIPT_TAIL
    if _use_subscription():
        return _invoke_via_subscription(model, system_prompt, user_text)
    return _invoke_via_api_key(model, max_tokens, system_prompt, user_text)


def _invoke_via_api_key(
    model: str, max_tokens: int, system_prompt: str, user_text: str
) -> tuple[str, int, int]:
    import anthropic

    # max_retries=0 so TIMEOUT_SECONDS is a hard wall — the SDK retries on timeout
    # by default, which would multiply the effective deadline well past 30s.
    client = anthropic.Anthropic(max_retries=0)
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_text}],
            timeout=TIMEOUT_SECONDS,
        )
    except anthropic.APITimeoutError as exc:
        # The SDK's timeout type is NOT a subclass of the builtin TimeoutError that
        # run_capture maps to the `timeout` skip reason, so translate it here.
        raise TimeoutError(str(exc)) from exc
    return msg.content[0].text.strip(), msg.usage.input_tokens, msg.usage.output_tokens


# The Claude Code runtime frames every request as an agentic coding task, so a
# capable model (Sonnet especially) tries to investigate files and use tools
# instead of just summarizing the transcript — burning its single turn on
# "Let me find where…" and never emitting the JSON. Leading the user message with
# this directive forces the one-shot, data-in/JSON-out behavior the prompts assume.
# It must lead the *user* message; in the system prompt it has no effect.
_SUBSCRIPTION_DIRECTIVE = (
    "IMPORTANT: You are not in an interactive coding session. Do not use tools, do not "
    "investigate files, do not ask questions, do not take any action. The text below the "
    "line is a completed Claude Code session transcript, provided purely as input data. "
    "Read it and respond with exactly one message containing only the output your "
    "instructions specify — no preamble, no prose, no code fences. Your entire reply "
    "must be either a single JSON object (first character `{`) or the single word "
    "null. Never repeat or echo the transcript or its delimiter lines.\n\n----- TRANSCRIPT -----\n"
)


def _invoke_via_subscription(
    model: str, system_prompt: str, user_text: str
) -> tuple[str, int | None, int | None]:
    """Drive the model through the Claude Code runtime using subscription auth.

    Auth comes from CLAUDE_CODE_OAUTH_TOKEN (see `claude setup-token`). The
    runtime controls output length, so max_tokens has no equivalent here — our
    prompts already constrain the response to compact JSON. tools=[] disables
    the runtime's built-in toolset so this stays a pure text→text call
    (allowed_tools only skips permission prompting, it does not remove tools);
    the user text is prefixed with _SUBSCRIPTION_DIRECTIVE to suppress agentic
    behavior. max_turns is a safety valve, not a single-shot constraint: at
    max_turns=1 the CLI ends the run with error_max_turns whenever the agent
    burns its only turn on anything but the final reply, discarding paid
    output (regression provenance: tests/test_subscription_invoke.py). A reply
    that streamed before an error result is kept — see the salvage below. Note
    CAPTURE_TIMEOUT_SECONDS bounds the whole run, not one turn; raise it, not
    max_turns, if legitimate multi-turn recoveries start logging `timeout`.
    """
    import asyncio
    from claude_agent_sdk import (
        query,
        ClaudeAgentOptions,
        AssistantMessage,
        TextBlock,
        ResultMessage,
    )

    prompt = _SUBSCRIPTION_DIRECTIVE + user_text

    async def _run() -> tuple[str, int | None, int | None]:
        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=model,
            max_turns=4,
            tools=[],
            allowed_tools=[],
        )
        parts: list[str] = []  # every text block in stream order, for salvage
        reply: list[str] = []  # text of the latest assistant message only
        tokens_in: int | None = None
        tokens_out: int | None = None
        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    texts = [
                        b.text for b in message.content if isinstance(b, TextBlock)
                    ]
                    parts.extend(texts)
                    if texts:
                        reply = texts
                elif isinstance(message, ResultMessage):
                    usage = message.usage or {}
                    # The runtime serves most input from cache (its own ~22k-token harness
                    # system prompt dominates), so input_tokens alone is misleadingly tiny.
                    # Sum all three to reflect what the model actually processed. Note this
                    # makes subscription cost estimates non-comparable to API mode: they
                    # include Claude Code's harness overhead the subscription absorbs, and
                    # a multi-turn run repeats the cache-read sum per turn, so this is an
                    # upper-bound estimate.
                    tokens_in = (
                        (usage.get("input_tokens", 0) or 0)
                        + (usage.get("cache_creation_input_tokens", 0) or 0)
                        + (usage.get("cache_read_input_tokens", 0) or 0)
                    )
                    tokens_out = usage.get("output_tokens", 0) or 0
        except Exception as exc:
            # The CLI exits non-zero after an error result (e.g. error_max_turns)
            # and the SDK surfaces that as an exception mid-iteration — after the
            # reply text already streamed. Discarding it loses a paid, often-
            # complete response. The terminal ResultMessage rarely arrives on
            # this path, so tokens usually stay None (unknown, never a fake 0).
            if not parts:
                raise
            _log_error(
                f"SUBSCRIPTION_SALVAGE partial reply kept (usage "
                f"{'captured' if tokens_out is not None else 'not captured'}) "
                f"after: {exc}"
            )
            # Everything that streamed, in order: the downstream outermost-brace
            # salvage in _call_path_a can dig JSON out of preamble+reply text.
            return "".join(parts).strip(), tokens_in, tokens_out
        # Only the latest assistant message is the reply. A multi-turn run may
        # emit preamble text on early turns; concatenating it would turn an
        # exact-match `null` reply into malformed_json downstream.
        return "".join(reply).strip(), tokens_in, tokens_out

    # asyncio.TimeoutError is TimeoutError on 3.11+, so the existing
    # `except TimeoutError` in run_capture catches a stalled subscription call.
    return asyncio.run(asyncio.wait_for(_run(), timeout=TIMEOUT_SECONDS))


def _call_path_a(scrubbed_text: str, prompts_dir: pathlib.Path) -> dict | None:
    """Call claude-sonnet-4-6 with the curation prompt.

    Returns the artifact dict with usage keys (tokens_in/tokens_out/cost_usd)
    merged in. A model null does NOT return None: it returns the usage dict
    plus {"_null": True} so the spend still reaches the log. (Test doubles may
    return bare None; run_capture accepts both null spellings.)
    """
    if os.environ.get("CAPTURE_MOCK_SDK") == "1":
        raise RuntimeError(
            "CAPTURE_MOCK_SDK=1 but no mock injected — call monkeypatched version"
        )

    system_prompt = (prompts_dir / "curation-system-prompt.md").read_text()

    # Sum tokens across attempts so a retry's cost is fully accounted for. A
    # salvaged subscription reply arrives with unknown usage (None); once any
    # attempt's usage is lost the totals are unknown too, and the log gets
    # null rather than an understated number.
    tokens_in = tokens_out = 0
    usage_lost = False

    def _usage() -> dict:
        if usage_lost:
            return {"tokens_in": None, "tokens_out": None, "cost_usd": None}
        return {
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            # Under subscription this is an estimated API-equivalent cost, not billed.
            "cost_usd": _estimate_cost_a(tokens_in, tokens_out),
        }

    data: dict | None = None
    # Holds the first unparseable reply so a later null can't relabel the outcome.
    unparsed: json.JSONDecodeError | None = None
    for _attempt in range(PATH_A_RESAMPLES + 1):
        text, tin, tout = _invoke_model(
            MODEL_A, MAX_TOKENS_A, system_prompt, scrubbed_text
        )
        if tin is None or tout is None:
            usage_lost = True
        else:
            tokens_in += tin
            tokens_out += tout
        raw = _strip_fences(text)
        if raw.lower() == "null":
            data = None
            continue  # non-deterministic null — try once more, then give up
        bad: json.JSONDecodeError | None = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            bad = exc
        else:
            if data is None:
                continue  # payload was a literal `null` — same as the raw case
            if not _is_artifact(data):
                # Parses fine but does not satisfy the contract: the wrong type
                # entirely (a quoted "null", a list, a number), or an object
                # whose title/body/type is not a string. Neither reaches the
                # except branch, and both used to fall through to the write path
                # and die there — as an AttributeError or a TypeError — after
                # the call was paid for and before anything was logged. Give
                # them the same recovery path as an unparseable reply.
                bad = json.JSONDecodeError(
                    "model reply is not an artifact-shaped object", raw, 0
                )

        if bad is not None:
            # The runtime sometimes wraps otherwise-valid JSON in prose or
            # transcript echoes (fences not at line start defeat _CODE_FENCE_RE).
            # Salvage the artifact before declaring the response malformed — it
            # was already paid for.
            salvaged = _salvage_artifact(raw)
            if salvaged is None:
                if _attempt < PATH_A_RESAMPLES:
                    # Resample like a null: an unusable reply is a
                    # non-deterministic generation failure, not a permanent one.
                    # Costs one extra input pass on a session already paid for.
                    # Held, not raised: if a later attempt also fails to produce
                    # an artifact this is what gets logged, so a malformed reply
                    # is never erased from log.md by a subsequent null.
                    unparsed = bad
                    data = None
                    continue
                _log_error(f"PATH_A malformed_json: {raw[:200]}")
                bad.usage = _usage()  # type: ignore[attr-defined]
                raise bad
            data = salvaged
        break  # got an artifact

    usage = _usage()
    if data is None:
        if unparsed is not None:
            # No artifact, and at least one attempt was unparseable — that is the
            # notable event, so log it as malformed_json rather than letting a
            # trailing null relabel it (the malformed_json rate in log.md is the
            # instrument this failure class is tracked by).
            _log_error("PATH_A malformed_json: unparseable reply, resample gave null")
            unparsed.usage = _usage()  # type: ignore[attr-defined]
            raise unparsed
        return {**usage, "_null": True}
    data.update(usage)
    return data


def _estimate_cost_a(tokens_in: int, tokens_out: int) -> float:
    # claude-sonnet-4-6: $3/M input, $15/M output
    return (tokens_in * 3 + tokens_out * 15) / 1_000_000


# ── file writing ───────────────────────────────────────────────────────────────


def _write_artifact(
    path: pathlib.Path,
    *,
    title: str,
    fm_type: str,
    project: str,
    source: str,
    session_id: str,
    created: str,
    model: str,
    cost_usd: float | None,
    redactions: dict[str, int],
    tags: list[str],
    body: str,
    source_links: list[str],
) -> None:
    fm = render_frontmatter(
        title=title,
        fm_type=fm_type,
        project=project,
        tags=tags,
        source=source,
        session_id=session_id,
        created=created,
        model=model,
        cost_usd=cost_usd,
        redactions=redactions,
    )
    clean_title = sanitize_title(title)
    source_section = ""
    if source_links:
        source_section = (
            "\n## Source\n" + "\n".join(f"- {link}" for link in source_links) + "\n"
        )

    content = f"{fm}\n# {clean_title}\n{body}\n{source_section}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ── transcript rendering for the model ───────────────────────────────────────

_ROLE_MAP = {"user": "[USER]", "assistant": "[ASSISTANT]"}

# Per-block render caps (chars). Bash commands and edit diffs are the high-signal,
# low-volume parts; error results are kept near-whole; successful output is headed.
_BASH_CMD_CAP = 300
_EDIT_DIFF_CAP = 200
_OTHER_INPUT_CAP = 120
_ERROR_CAP = 600


def _tool_result_text(block: dict) -> str:
    """Flatten a tool_result's content (str or list of text blocks) to text."""
    c = block.get("content", "")
    if isinstance(c, list):
        return "\n".join(
            b.get("text", "")
            for b in c
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return c if isinstance(c, str) else ""


def _scrub_cap(text: str, cap: int, counts: dict[str, int] | None) -> str:
    """Scrub *text*, then truncate to *cap* — in that order, never the reverse.

    Truncating first defeats the scrubber outright: the private_key rule needs
    its closing -----END … PRIVATE KEY----- to match, and the length-anchored
    token rules (AIza…{35}, AKIA…{16}) need their full body. A cap that lands
    mid-secret leaves a fragment no rule matches, and that fragment is what
    would reach the model and the note. Redaction counts are accumulated into
    *counts* so the artifact's `redactions:` total still reflects what was
    caught here rather than under-reporting it.
    """
    import scrub as scrub_mod

    scrubbed, found = scrub_mod.scrub(text)
    if counts is not None:
        for name, n in found.items():
            counts[name] = counts.get(name, 0) + n
    return scrubbed[:cap]


def _render_tool_use(block: dict, counts: dict[str, int] | None = None) -> str:
    """Render one tool_use block as a compact `[TOOL] …` line."""
    name = block.get("name", "tool")
    inp = block.get("input", {}) or {}
    if name == "Bash":
        cmd = _scrub_cap(str(inp.get("command", "")), _BASH_CMD_CAP, counts)
        return f"[TOOL] Bash: {cmd}"
    if name in ("Edit", "MultiEdit"):
        diff = f"{inp.get('old_string', '')} -> {inp.get('new_string', '')}"
        return (
            f"[TOOL] {name}: {inp.get('file_path', '')} | "
            f"{_scrub_cap(diff, _EDIT_DIFF_CAP, counts)}"
        )
    if name == "Write":
        body = _scrub_cap(str(inp.get("content", "")), _EDIT_DIFF_CAP, counts)
        return f"[TOOL] Write: {inp.get('file_path', '')} | {body}"
    # Any other tool: name + a compact slice of its input for context.
    blob = _scrub_cap(json.dumps(inp, default=str), _OTHER_INPUT_CAP, counts)
    return f"[TOOL] {name}: {blob}"


def render_transcript(
    messages: list[dict], redactions: dict[str, int] | None = None
) -> str:
    """Build the curator's input text from loaded messages.

    Each message's text becomes `[ROLE]: <text>`. When raw content `blocks` are
    present (list-form transcript lines), tool activity is surfaced too — this is
    what the model never used to see:
      - tool_use            → `[TOOL] <Name>: <command/diff/input>`
      - tool_result success → `[OUT] <head>` (CAPTURE_SUCCESS_HEAD_CHARS; 0 = drop)
      - tool_result error   → `[ERROR] <text>` (always kept, prioritised over budget)

    Tool-derived chars accumulate against CAPTURE_TOOL_CHARS_BUDGET; once spent,
    further tool_use / [OUT] lines are dropped (text and [ERROR] still emitted), so
    the enriched transcript stays under the token guard on pathological runs. The
    text-only `content` the filters read is untouched — only the model input grows.

    Every tool-derived string is scrubbed BEFORE its length cap is applied (see
    _scrub_cap); pass a dict as *redactions* to collect what those scrubs caught,
    since the caller's own scrub of the finished text cannot see them.
    """
    budget = int(os.environ.get("CAPTURE_TOOL_CHARS_BUDGET", "30000"))
    head = int(os.environ.get("CAPTURE_SUCCESS_HEAD_CHARS", "200"))
    used = 0
    lines: list[str] = []

    for m in messages:
        role = _ROLE_MAP.get(m.get("role", ""), "[UNKNOWN]")
        blocks = m.get("blocks")
        if not isinstance(blocks, list):
            lines.append(f"{role}: {m.get('content', '')}")
            continue

        parts: list[str] = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            btype = b.get("type")
            if btype == "text":
                parts.append(b.get("text", ""))
            elif btype == "tool_use":
                rendered = _render_tool_use(b, redactions)
                if used + len(rendered) <= budget:
                    parts.append(rendered)
                    used += len(rendered)
            elif btype == "tool_result":
                text = _tool_result_text(b).strip()
                if not text:
                    continue  # nothing to surface (e.g. image-only / empty result)
                if b.get("is_error"):
                    rendered = f"[ERROR] {_scrub_cap(text, _ERROR_CAP, redactions)}"
                    parts.append(rendered)  # errors always kept
                    used += len(rendered)
                elif head > 0 and used < budget:
                    rendered = f"[OUT] {_scrub_cap(text, head, redactions)}"
                    parts.append(rendered)
                    used += len(rendered)
        parts = [p for p in parts if p]
        lines.append(f"{role}: " + "\n".join(parts))

    return "\n".join(lines)


# ── main capture pipeline ─────────────────────────────────────────────────────


def run_capture(
    *,
    transcript: list[dict],
    session_id: str,
    cwd: str,
    vault_dir: str | pathlib.Path | None = None,
    log_path: pathlib.Path | None = None,
    index_path: pathlib.Path | None = None,
    date_str: str | None = None,
    prompts_dir: pathlib.Path | None = None,
) -> None:
    """Full capture pipeline: scrub → threshold → dedup → API calls → write → log."""
    import scrub as scrub_mod

    if vault_dir is None:
        vault_dir = VAULT_DIR
    vault_dir = pathlib.Path(vault_dir)
    if log_path is None:
        log_path = LOG_PATH
    if index_path is None:
        index_path = INDEX_PATH
    if prompts_dir is None:
        prompts_dir = REPO_ROOT / "prompts"
    if date_str is None:
        date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    # ── 1. scrub transcript ───────────────────────────────────────────────────
    # render_transcript surfaces tool activity ([TOOL]/[OUT]/[ERROR]) for the model;
    # scrub still runs on the full assembled text, so secrets in commands/output are
    # redacted exactly as prose is.
    # Tool blocks are scrubbed inside render (before their length caps chop a
    # secret into an unmatchable fragment); those counts come back here so the
    # artifact's `redactions:` total covers them too.
    tool_redactions: dict[str, int] = {}
    raw_text = render_transcript(transcript, tool_redactions)
    scrubbed_text, redactions = scrub_mod.scrub(raw_text)
    for _name, _n in tool_redactions.items():
        redactions[_name] = redactions.get(_name, 0) + _n

    # ── 2–5. pre-flight skips (excluded command / threshold / tokens / dedup) ─
    if uses_excluded_command(transcript):
        skip = "excluded_command"
    elif is_below_threshold(transcript):
        skip = "threshold"
    elif is_above_token_limit(scrubbed_text):
        skip = "token_limit"
    elif is_duplicate_session(session_id, index_path=index_path):
        skip = "duplicate"
    else:
        skip = None
    if skip:
        _log_skip(session_id, skip, redactions, log_path=log_path)
        return

    # ── 6. project derivation ─────────────────────────────────────────────────
    project = derive_project(cwd)

    # ── 7. curation API call (or mock) ────────────────────────────────────────
    result_a: dict | None = None
    skip_reason_a: str | None = None
    tokens_in_a = tokens_out_a = None
    cost_usd_a = None

    try:
        result_a = _call_path_a(scrubbed_text, prompts_dir)
        if result_a is not None:
            tokens_in_a = result_a.get("tokens_in")
            tokens_out_a = result_a.get("tokens_out")
            cost_usd_a = result_a.get("cost_usd")
        if result_a is None or result_a.get("_null"):
            skip_reason_a = "model_returned_null"
            result_a = None
    except json.JSONDecodeError as exc:
        skip_reason_a = "malformed_json"
        usage = getattr(exc, "usage", None)
        if usage:
            tokens_in_a = usage.get("tokens_in")
            tokens_out_a = usage.get("tokens_out")
            cost_usd_a = usage.get("cost_usd")
    except TimeoutError:
        skip_reason_a = "timeout"
    except Exception as exc:
        skip_reason_a = f"error:{type(exc).__name__}"
        # log.md keeps only the type name; without the message a bare SDK
        # `Exception` (e.g. a control-request timeout) is undiagnosable.
        _log_error(f"PATH_A {type(exc).__name__}: {exc}")

    # ── 8. scrub model output (title, body, tags, source_links) ──────────────
    if result_a:
        result_a["title"], _ = scrub_mod.scrub(result_a.get("title", ""))
        result_a["body"], _ = scrub_mod.scrub(result_a.get("body", ""))
        _tags = result_a.get("tags", [])
        result_a["tags"] = (
            [scrub_mod.scrub(str(t))[0] for t in _tags] if isinstance(_tags, list) else []
        )
        # str() the elements and tolerate a non-list: these come straight from the
        # model, and a non-string element here would raise inside scrub() after
        # the call was already paid for.
        _links = result_a.get("source_links", [])
        result_a["source_links"] = (
            [scrub_mod.scrub(str(lnk))[0] for lnk in _links]
            if isinstance(_links, list)
            else []
        )

    # ── 9 & 10. sanitize title + write Path A ────────────────────────────────
    path_a_rel: str | None = None
    if result_a and skip_reason_a is None:
        title_a = sanitize_title(result_a.get("title", "untitled"))
        slug_a = make_slug(title_a)
        fname_a = make_filename(date_str, slug_a, session_id)
        rel_a = f"Inbox/auto/{fname_a}"
        full_path_a = vault_dir / "Inbox" / "auto" / fname_a
        _write_artifact(
            full_path_a,
            title=title_a,
            fm_type=sanitize_type(result_a.get("type", "decision")),
            project=project,
            source="claude-code-curated",
            session_id=session_id,
            created=date_str,
            model=MODEL_A,
            cost_usd=cost_usd_a,
            redactions=redactions,
            # model tags are scrubbed (step 8) then slug-coerced; empties drop out
            tags=["claude-code", "curated"]
            + [s for s in (sanitize_tag(t) for t in result_a["tags"][:10]) if s],
            body=result_a.get("body", ""),
            source_links=result_a.get("source_links", []),
        )
        path_a_rel = rel_a

    # ── 11. append session index ─────────────────────────────────────────────
    _append_index(session_id, path_a_rel, date_str, index_path=index_path)

    # ── 12. append log ───────────────────────────────────────────────────────
    entry = build_log_entry(
        session_id=session_id,
        path_a=path_a_rel,
        skip_reason_a=skip_reason_a,
        tokens_in_a=tokens_in_a,
        tokens_out_a=tokens_out_a,
        cost_usd_a=cost_usd_a,
        redactions=redactions,
    )
    append_log(entry, log_path=log_path)


# ── CLI entry point ────────────────────────────────────────────────────────────


def _extract_text(content) -> str:
    """Flatten content that may be a string or a list of content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            if isinstance(block, dict) and block.get("type") == "text"
            else block
            if isinstance(block, str)
            else ""
            for block in content
        ]
        return "\n".join(p for p in parts if p)
    return ""


def _load_transcript(transcript_path: str) -> list[dict]:
    messages = []
    with open(transcript_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                for role in ("user", "assistant"):
                    if obj.get("type") == role or obj.get("role") == role:
                        raw = obj.get("message", {}).get(
                            "content", obj.get("content", "")
                        )
                        messages.append(
                            {
                                "role": role,
                                "content": _extract_text(raw),
                                # Raw blocks travel alongside the text-only content
                                # so render_transcript can surface tool activity to
                                # the model while the filters keep reading content.
                                "blocks": raw if isinstance(raw, list) else None,
                            }
                        )
                        break
            except json.JSONDecodeError:
                continue
    return messages


def main():
    if len(sys.argv) < 4:
        print("Usage: curate.py <transcript_path> <session_id> <cwd>", file=sys.stderr)
        sys.exit(1)

    transcript_path, session_id, cwd = sys.argv[1], sys.argv[2], sys.argv[3]

    mock = os.environ.get("CAPTURE_MOCK_SDK") == "1"
    if _use_subscription():
        if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") and not mock:
            _log_error(
                "CAPTURE_USE_SUBSCRIPTION=1 but CLAUDE_CODE_OAUTH_TOKEN not set — skipping capture"
            )
            sys.exit(0)
    elif not os.environ.get("ANTHROPIC_API_KEY") and not mock:
        _log_error("ANTHROPIC_API_KEY not set — skipping capture")
        sys.exit(0)

    try:
        transcript = _load_transcript(transcript_path)
    except Exception as exc:
        _log_error(f"Failed to load transcript {transcript_path!r}: {exc}")
        # Must still be visible in log.md: exiting before any entry made these
        # sessions invisible to the weekly no-capture alarm (15 unlogged
        # losses in W28 alone). Never let the logging itself fail the hook.
        try:
            _log_skip(session_id, "transcript_missing", {})
        except Exception as log_exc:
            _log_error(f"Failed to log transcript_missing: {log_exc}")
        sys.exit(0)

    try:
        run_capture(transcript=transcript, session_id=session_id, cwd=cwd)
    except Exception as exc:
        _log_error(f"CURATE_ERROR session={session_id}: {exc}")
        sys.exit(0)


def _log_error(msg: str) -> None:
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"{ts} {msg}", file=sys.stderr)


if __name__ == "__main__":
    main()
