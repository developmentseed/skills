#!/usr/bin/env python3
"""Report which Claude Code sessions on this machine left a handoff note since a given day.

Read-only. Joins the live-session registry (<config>/sessions/<pid>.json: name -> sessionId)
with each session's transcript (<config>/projects/*/<sessionId>.jsonl, plus its subagents'),
where every Write and Edit tool call is recorded with its file path and time. Neither is a
documented interface: a running session that can't be matched is reported as `unknown`, so the
caller asks it instead. <config> is $CLAUDE_CONFIG_DIR, else ~/.claude.

The window runs from the start of --date (default today) to now, so a run after midnight with
--date <yesterday> still sees the evening's work.

A note counts as a handoff when its file name contains "handoff", it ends in .md, it is not
under a memory/ directory, and any date in its name falls between the day checked and a few
days after it. It must also still exist, not sit in a temp directory or a git worktree (both
get deleted), and not open with a SUPERSEDED banner.

Prints TSV, one row per handoff note (one row per session without one):
  verdict  session  written  calls_after  last_active  project  path  title
verdict: fresh | stale | none | unknown   (running sessions, from --live)
         closed | closed-none             (sessions no longer running that worked in the window)

--digest NAME instead prints NAME's latest note and a compact log of its transcript over the
window (prompts, Claude's messages, one line per tool call, no tool output, secrets masked),
for writing its handoff from outside while it is busy.
"""

import argparse
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TEMP_ROOTS = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")
STALE_AFTER = 10  # tool calls after the latest handoff that make it stale
AHEAD_DAYS = (
    3  # a note may be named for a day up to this far ahead (written Friday for Monday)
)
NAME_DATE = re.compile(r"(20\d\d)[-_]?([01]\d)[-_]?([0-3]\d)")
# a line that opens with the word, e.g. "> ⏭️ **SUPERSEDED by x.md**"; "superseded in part" doesn't count
BANNER = re.compile(r"\W*superseded\b(?!\s+in\s+part)", re.I)
SECRET = re.compile(
    r"(?i)(bearer\s+|(?:token|password|passwd|secret|api[_-]?key)\s*[=:]\s*)\S+"
    r"|\b(?:ghp|gho|ghs|github_pat|sk|xox[abp])[-_A-Za-z0-9]{10,}"
)
DIGEST_CHARS = 25_000  # under Claude Code's default Bash output cap (30k characters)


def start_of(day):
    return datetime.combine(day, datetime.min.time()).astimezone()


def entries(transcript, since, needle=None):
    """Yield (local time, entry) for each transcript entry from `since`; skip what can't be read."""
    try:
        fh = transcript.open(encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            if needle and needle not in line:
                continue
            try:
                e = json.loads(line)
                ts = datetime.fromisoformat(
                    e["timestamp"].replace("Z", "+00:00")
                ).astimezone()
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            if ts >= since:
                yield ts, e


def is_handoff(path, day):
    name = Path(path).name.lower()
    # an older note edited today isn't today's handoff, nor is one named after a deadline;
    # one written a few days ahead (on Friday for Monday) is
    dates = {"-".join(d) for d in NAME_DATE.findall(name)}
    ahead = (day + timedelta(days=AHEAD_DAYS)).isoformat()
    return (
        "handoff" in name
        and name.endswith(".md")
        and "/memory/" not in path
        and (not dates or any(day.isoformat() <= d <= ahead for d in dates))
    )


def in_worktree(path):
    # a `git worktree add` checkout (Claude's .claude/worktrees/ included) has a .git *file*
    return any((p / ".git").is_file() for p in Path(path).parents)


def note_title(path):
    """Return the note's title (first heading, else its file name), or None if it can't be used:
    a denied or failed Write leaves no file, temp dirs and worktrees get deleted, and a note that
    opens with a SUPERSEDED banner points to another note."""
    if path.startswith(TEMP_ROOTS) or in_worktree(path):
        return None
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            lines = [line.strip() for line, _ in zip(fh, range(200))]
    except OSError:
        return None
    # skip YAML frontmatter; if it never closes, there is no body to read
    if lines and lines[0] == "---":
        end = next(
            (i for i, line in enumerate(lines[1:], 1) if line == "---"), len(lines)
        )
        lines = lines[end + 1 :]
    head = [line for line in lines if line][:6]
    if any(BANNER.match(line) for line in head):
        return None
    heading = next((h.lstrip("#").strip() for h in head if h.startswith("#")), "")
    return heading or Path(path).stem


def tilde(path):
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home + os.sep) else path


def hhmm(ts):
    return ts.strftime("%H:%M") if ts else "-"


def short(text, n):
    text = " ".join(str(text).split())
    text = SECRET.sub(lambda m: (m.group(1) or "") + "***", text)
    return text if len(text) <= n else text[: n - 1] + "…"


def digest(transcript, since):
    """Return a compact log of a transcript from `since`: the user's prompts, Claude's messages,
    peer messages and notices, and one line per tool call (its description before its command).
    Tool output is left out: it is most of the bulk and may hold secrets. Over DIGEST_CHARS, only
    the most recent part is kept."""
    out = []
    for ts, e in entries(transcript, since):
        if (
            e.get("type") not in ("user", "assistant")
            or e.get("isMeta")
            or e.get("isCompactSummary")
        ):
            continue  # skill bodies and compaction summaries are the harness talking, not the user
        content = (e.get("message") or {}).get("content")
        blocks = (
            [{"type": "text", "text": content}] if isinstance(content, str) else content
        )
        for b in blocks or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and str(b.get("text", "")).strip():
                text = str(b["text"])
                if e["type"] == "assistant":
                    who, n = "CLAUDE", 1500
                elif "<cross-session-message" in text:
                    who, n = "PEER", 600
                elif "<task-notification>" in text or "[Cross-session" in text:
                    who, n = "NOTICE", 200
                else:
                    who, n = "USER", 600
                out.append(f"{hhmm(ts)} {who}: {short(text, n)}")
            elif b.get("type") == "tool_use":
                i = b.get("input") or {}
                keys = ("description", "file_path", "to", "prompt", "command")
                what = next((str(i[k]) for k in keys if i.get(k)), "")
                first = what.splitlines()[0] if what.strip() else ""
                out.append(f"{hhmm(ts)}   → {b.get('name')}: {short(first, 120)}")
    text = "\n".join(out)
    if len(text) > DIGEST_CHARS:
        kept = text[-DIGEST_CHARS:].split("\n", 1)[-1]
        text = f"[{len(out) - kept.count(chr(10)) - 1} earlier lines omitted]\n{kept}"
    return text


def scan(transcripts, day):
    """Return ({handoff path: (last write time, title)}, [tool call times]) from the start of `day`."""
    handoffs, calls = {}, []
    for transcript in transcripts:
        for ts, entry in entries(transcript, start_of(day), needle='"tool_use"'):
            if entry.get("type") != "assistant":
                continue
            for block in (entry.get("message") or {}).get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                calls.append(ts)
                path = (block.get("input") or {}).get("file_path") or ""
                if block.get("name") in ("Write", "Edit") and is_handoff(path, day):
                    handoffs[path] = max(ts, handoffs.get(path, ts))
    notes = {}
    for path, ts in handoffs.items():
        if (title := note_title(path)) is not None:
            notes[path] = (ts, title)
    return notes, calls


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--live",
        nargs="*",
        default=[],
        help="names of the running sessions, from ListAgents",
    )
    p.add_argument(
        "--self", dest="me", help="this session's own name, left out of the report"
    )
    p.add_argument(
        "--date",
        type=date.fromisoformat,
        default=date.today(),
        help="start of the window",
    )
    p.add_argument(
        "--digest",
        metavar="NAME",
        help="print NAME's latest note and a compact log of its transcript",
    )
    p.add_argument(
        "--claude-dir",
        type=Path,
        default=Path(
            os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude"
        ).expanduser(),
    )
    a = p.parse_args(argv)

    # name -> registry entry; a name can linger in an old file, so the newest entry wins
    registry = {}
    for f in (a.claude_dir / "sessions").glob("*.json"):
        try:
            s = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        name = s.get("name")
        if name and s.get("updatedAt", 0) >= registry.get(name, {}).get("updatedAt", 0):
            registry[name] = s

    if a.digest:
        sid = registry.get(a.digest, {}).get("sessionId")
        t = next(a.claude_dir.glob(f"projects/*/{sid}.jsonl"), None) if sid else None
        if t is None:
            raise SystemExit(f"{a.digest}: no transcript found")
        notes, _ = scan([t, *t.with_suffix("").glob("subagents/**/*.jsonl")], a.date)
        # the session's notes live next to its memory, which can differ from the transcript's dir
        out_dir = str(t.parent)
        if notes:
            path, (ts, title) = max(notes.items(), key=lambda kv: kv[1][0])
            out_dir = str(Path(path).parent)
            print(f"latest note: {tilde(path)} ({title}), last written {hhmm(ts)}")
        else:
            print(f"latest note: none since {a.date}")
        print(f"write to: {tilde(out_dir)}")
        print(digest(t, start_of(a.date)))
        return

    names = [n for n in dict.fromkeys(a.live) if n != a.me]
    live = {registry[n]["sessionId"]: n for n in names if n in registry}
    skip = {registry[a.me]["sessionId"]} if a.me in registry else set()

    rows = [
        (
            "verdict",
            "session",
            "written",
            "calls_after",
            "last_active",
            "project",
            "path",
            "title",
        )
    ]
    seen = set()
    for t in sorted(a.claude_dir.glob("projects/*/*.jsonl")):
        sid = t.stem
        if not SESSION_ID.fullmatch(sid) or sid in skip:
            continue
        try:
            if datetime.fromtimestamp(t.stat().st_mtime).date() < a.date:
                continue
        except OSError:
            continue
        # work delegated to subagents and workflows counts towards staleness too
        handoffs, calls = scan(
            [t, *t.with_suffix("").glob("subagents/**/*.jsonl")], a.date
        )
        name = live.get(sid)
        if name is None and not calls:
            continue
        seen.add(sid)
        last = max(calls, default=None)
        if handoffs:
            latest = max(ts for ts, _ in handoffs.values())
            after = sum(c > latest for c in calls)
            verdict = (
                ("fresh" if after <= STALE_AFTER else "stale") if name else "closed"
            )
            for path, (ts, title) in sorted(handoffs.items(), key=lambda kv: kv[1][0]):
                rows.append(
                    (
                        verdict,
                        name or sid[:8],
                        hhmm(ts),
                        str(sum(c > ts for c in calls)),
                        hhmm(last),
                        t.parent.name,
                        tilde(path),
                        title.replace("\t", " "),
                    )
                )
        else:
            rows.append(
                (
                    "none" if name else "closed-none",
                    name or sid[:8],
                    "-",
                    "-",
                    hhmm(last),
                    t.parent.name,
                    "-",
                    "-",
                )
            )

    for n in names:
        if n not in registry:
            rows.append(("unknown", n, "-", "-", "-", "-", "-", "-"))
        elif registry[n]["sessionId"] not in seen:
            rows.append(("none", n, "-", "-", "-", "-", "-", "-"))

    print("\n".join("\t".join(r) for r in rows))


if __name__ == "__main__":
    main()
