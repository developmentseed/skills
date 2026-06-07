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
retrying once on a non-deterministic null — writes it to the Obsidian Inbox, and
appends to the eval state log. (Path B, the Haiku raw baseline, was retired
2026-06-04; see eval/experiments/FINDINGS.md.)

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

CAPTURE_MAX_EST_TOKENS: int = int(os.environ.get("CAPTURE_MAX_EST_TOKENS", "50000"))

# Slash commands whose sessions are NOT captured. Empty by default — the public
# pipeline archives everything. An external extension sets CAPTURE_EXCLUDED_COMMANDS
# in capture.env to skip capturing its own workflow sessions.
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
# the CAPTURE_VAULT_DIR env var, which install.sh writes into capture.env and the hook
# sources before launching this script. The fallback below only applies when curate.py
# is run by hand without config; session-end-capture.sh refuses to launch when the
# vault is unconfigured, so the real hook path always provides an explicit value.
VAULT_DIR = pathlib.Path(
    os.environ.get("CAPTURE_VAULT_DIR") or (pathlib.Path.home() / "Obsidian")
)
LOG_PATH = STATE_DIR / "log.md"
INDEX_PATH = STATE_DIR / "session-index.tsv"
HOOKS_LOG = pathlib.Path.home() / ".claude" / "hooks.log"

MOCK_RESPONSES_PATH = (
    pathlib.Path(__file__).parent.parent / "eval" / "fixtures" / "mock-responses.json"
)

MODEL_A = "claude-sonnet-4-6"
MAX_TOKENS_A = 2000
TIMEOUT_SECONDS = 30
# Path A nulls non-deterministically: the same transcript can return `null` on
# one call and a real artifact on the next. Retry once on null to recover those
# misses at zero precision cost (a genuinely empty session re-nulls). Retry
# tokens are folded into the usage totals so cost accounting stays accurate.
PATH_A_NULL_RETRIES = 1

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
    s = _BAD_CHARS_RE.sub(" ", title)
    s = _MULTI_SPACE_RE.sub(" ", s)
    s = s.strip()
    return s[:120]


def sanitize_summary(s: str, max_len: int = 140) -> str:
    """Same rules as sanitize_title but with a 140-char cap by default."""
    s = _BAD_CHARS_RE.sub(" ", s)
    s = _MULTI_SPACE_RE.sub(" ", s)
    s = s.strip()
    return s[:max_len]


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
    """Render YAML frontmatter block. Title is sanitized inside here."""
    clean_title = sanitize_title(title)
    tags_yaml = "[" + ", ".join(tags) + "]"
    redact_yaml = "{" + ", ".join(f"{k}: {v}" for k, v in redactions.items()) + "}"
    cost_str = f"{cost_usd:.4f}" if cost_usd is not None else "null"
    return (
        f"---\n"
        f"title: {clean_title}\n"
        f"type: {fm_type}\n"
        f"project: {project}\n"
        f"tags: {tags_yaml}\n"
        f"source: {source}\n"
        f"session_id: {session_id}\n"
        f"created: {created}\n"
        f"model: {model}\n"
        f"cost_usd: {cost_str}\n"
        f"redactions: {redact_yaml}\n"
        f"---\n"
    )


# ── dedup ──────────────────────────────────────────────────────────────────────


def is_duplicate_session(
    session_id: str,
    *,
    index_path: pathlib.Path = INDEX_PATH,
) -> bool:
    """Return True if session_id already appears in the index TSV."""
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
    excluded_commands: list[str] = EXCLUDED_COMMANDS,
) -> bool:
    """Return True if any user turn invokes an excluded slash command.

    Matches only when the command appears at the start of a line (possibly
    preceded by whitespace), so mentions of the command in prose are ignored.
    """
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
    limit = int(os.environ.get("CAPTURE_MAX_EST_TOKENS", "50000"))
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
    path_a: str | None,
    skip_reason_a: str | None,
    tokens_in_a: int | None,
    tokens_out_a: int | None,
    cost_usd_a: float | None,
    redactions: dict[str, int],
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


def append_log(entry: dict, *, log_path: pathlib.Path = LOG_PATH) -> None:
    """Append one JSON line to log_path with cross-process flock + in-process lock."""
    line = json.dumps(entry) + "\n"
    with _STATE_LOCK:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(line)
            fh.flush()
            fcntl.flock(fh, fcntl.LOCK_UN)


def _append_index(
    session_id: str,
    path_a: str | None,
    date_str: str,
    *,
    index_path: pathlib.Path = INDEX_PATH,
) -> None:
    """Append one line to session-index.tsv, creating the file with header if absent."""
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


def _invoke_model(
    model: str, max_tokens: int, system_prompt: str, user_text: str
) -> tuple[str, int, int]:
    """Single-shot request. Returns (raw_text, tokens_in, tokens_out).

    Routes through the Claude Max subscription when CAPTURE_USE_SUBSCRIPTION=1,
    otherwise the metered Anthropic Messages API. Both transports raise
    TimeoutError on a >TIMEOUT_SECONDS call, which run_capture maps to the
    `timeout` skip reason.
    """
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
    "instructions specify — no preamble, no prose, no code fences.\n\n----- TRANSCRIPT -----\n"
)


def _invoke_via_subscription(
    model: str, system_prompt: str, user_text: str
) -> tuple[str, int, int]:
    """Drive the model through the Claude Code runtime using subscription auth.

    Auth comes from CLAUDE_CODE_OAUTH_TOKEN (see `claude setup-token`). The
    runtime controls output length, so max_tokens has no equivalent here — our
    prompts already constrain the response to compact JSON. Runs single-shot
    (max_turns=1) with no tools, so this stays a pure text→text call. The user
    text is prefixed with _SUBSCRIPTION_DIRECTIVE to suppress agentic behavior.
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

    async def _run() -> tuple[str, int, int]:
        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=model,
            max_turns=1,
            allowed_tools=[],
        )
        parts: list[str] = []
        tokens_in = tokens_out = 0
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
            elif isinstance(message, ResultMessage):
                usage = message.usage or {}
                # The runtime serves most input from cache (its own ~22k-token harness
                # system prompt dominates), so input_tokens alone is misleadingly tiny.
                # Sum all three to reflect what the model actually processed. Note this
                # makes subscription cost estimates non-comparable to API mode: they
                # include Claude Code's harness overhead the subscription absorbs.
                tokens_in = (
                    (usage.get("input_tokens", 0) or 0)
                    + (usage.get("cache_creation_input_tokens", 0) or 0)
                    + (usage.get("cache_read_input_tokens", 0) or 0)
                )
                tokens_out = usage.get("output_tokens", 0) or 0
        return "".join(parts).strip(), tokens_in, tokens_out

    # asyncio.TimeoutError is TimeoutError on 3.11+, so the existing
    # `except TimeoutError` in run_capture catches a stalled subscription call.
    return asyncio.run(asyncio.wait_for(_run(), timeout=TIMEOUT_SECONDS))


def _call_path_a(scrubbed_text: str, prompts_dir: pathlib.Path) -> dict | None:
    """Call claude-sonnet-4-6 with curation prompt. Returns artifact dict or None."""
    if os.environ.get("CAPTURE_MOCK_SDK") == "1":
        raise RuntimeError(
            "CAPTURE_MOCK_SDK=1 but no mock injected — call monkeypatched version"
        )

    system_prompt = (prompts_dir / "curation-system-prompt.md").read_text()

    # Sum tokens across attempts so a retry's cost is fully accounted for.
    tokens_in = tokens_out = 0
    data: dict | None = None
    for _attempt in range(PATH_A_NULL_RETRIES + 1):
        text, tin, tout = _invoke_model(
            MODEL_A, MAX_TOKENS_A, system_prompt, scrubbed_text
        )
        tokens_in += tin
        tokens_out += tout
        raw = _strip_fences(text)
        if raw.lower() == "null":
            data = None
            continue  # non-deterministic null — try once more, then give up
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Malformed JSON is not a null; don't retry it (keep the prior
            # behavior). Attach accumulated usage for the caller's cost log.
            _log_error(f"PATH_A malformed_json: {raw[:200]}")
            exc.usage = {  # type: ignore[attr-defined]
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": _estimate_cost_a(tokens_in, tokens_out),
            }
            raise
        break  # got an artifact

    usage = {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        # Under subscription this is an estimated API-equivalent cost, not billed.
        "cost_usd": _estimate_cost_a(tokens_in, tokens_out),
    }
    if data is None:
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


# ── main capture pipeline ─────────────────────────────────────────────────────


def run_capture(
    *,
    transcript: list[dict],
    session_id: str,
    cwd: str,
    vault_dir: str | pathlib.Path = VAULT_DIR,
    log_path: pathlib.Path = LOG_PATH,
    index_path: pathlib.Path = INDEX_PATH,
    date_str: str | None = None,
    prompts_dir: pathlib.Path | None = None,
) -> None:
    """Full capture pipeline: scrub → threshold → dedup → API calls → write → log."""
    import scrub as scrub_mod

    vault_dir = pathlib.Path(vault_dir)
    if prompts_dir is None:
        prompts_dir = pathlib.Path(__file__).parent.parent / "prompts"
    if date_str is None:
        date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    # ── 1. scrub transcript ───────────────────────────────────────────────────
    role_map = {"user": "[USER]", "assistant": "[ASSISTANT]"}
    raw_text = "\n".join(
        f"{role_map.get(m.get('role', ''), '[UNKNOWN]')}: {m.get('content', '')}"
        for m in transcript
    )
    scrubbed_text, redactions = scrub_mod.scrub(raw_text)

    # ── 2. excluded command check ─────────────────────────────────────────────
    # Pass the module-level list explicitly (resolved at call time, not frozen as a
    # default arg) so it reflects CAPTURE_EXCLUDED_COMMANDS and stays test-patchable.
    if uses_excluded_command(transcript, EXCLUDED_COMMANDS):
        entry = build_log_entry(
            session_id=session_id,
            path_a=None,
            skip_reason_a="excluded_command",
            tokens_in_a=None,
            tokens_out_a=None,
            cost_usd_a=None,
            redactions=redactions,
        )
        append_log(entry, log_path=log_path)
        return

    # ── 3. threshold check ────────────────────────────────────────────────────
    if is_below_threshold(transcript):
        entry = build_log_entry(
            session_id=session_id,
            path_a=None,
            skip_reason_a="threshold",
            tokens_in_a=None,
            tokens_out_a=None,
            cost_usd_a=None,
            redactions=redactions,
        )
        append_log(entry, log_path=log_path)
        return

    # ── 4. token-count guard ──────────────────────────────────────────────────
    if is_above_token_limit(scrubbed_text):
        entry = build_log_entry(
            session_id=session_id,
            path_a=None,
            skip_reason_a="token_limit",
            tokens_in_a=None,
            tokens_out_a=None,
            cost_usd_a=None,
            redactions=redactions,
        )
        append_log(entry, log_path=log_path)
        return

    # ── 5. dedup check ────────────────────────────────────────────────────────
    if is_duplicate_session(session_id, index_path=index_path):
        entry = build_log_entry(
            session_id=session_id,
            path_a=None,
            skip_reason_a="duplicate",
            tokens_in_a=None,
            tokens_out_a=None,
            cost_usd_a=None,
            redactions=redactions,
        )
        append_log(entry, log_path=log_path)
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

    # ── 8. scrub model output (title, body, source_links) ───────────────────
    if result_a:
        result_a["title"], _ = scrub_mod.scrub(result_a.get("title", ""))
        result_a["body"], _ = scrub_mod.scrub(result_a.get("body", ""))
        result_a["source_links"] = [
            scrub_mod.scrub(lnk)[0] for lnk in result_a.get("source_links", [])
        ]

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
            fm_type=result_a.get("type", "decision"),
            project=project,
            source="claude-code-curated",
            session_id=session_id,
            created=date_str,
            model=MODEL_A,
            cost_usd=cost_usd_a,
            redactions=redactions,
            tags=["claude-code", "curated"] + result_a.get("tags", []),
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
                if obj.get("type") == "user" or obj.get("role") == "user":
                    raw = obj.get("message", {}).get("content", obj.get("content", ""))
                    messages.append({"role": "user", "content": _extract_text(raw)})
                elif obj.get("type") == "assistant" or obj.get("role") == "assistant":
                    raw = obj.get("message", {}).get("content", obj.get("content", ""))
                    messages.append(
                        {"role": "assistant", "content": _extract_text(raw)}
                    )
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
