#!/usr/bin/env python3
"""Report which Claude Code sessions on this machine left a handoff note on a given day.

Read-only. Joins the live-session registry (<config>/sessions/<pid>.json: name -> sessionId)
with each session's transcript (<config>/projects/*/<sessionId>.jsonl, plus its subagents'),
where every Write and Edit tool call is recorded with its file path and time. Neither is a
documented interface: a running session that can't be matched is reported as `unknown`, so the
caller asks it instead. <config> is $CLAUDE_CONFIG_DIR, else ~/.claude.

A note counts as a handoff when its file name contains "handoff", it ends in .md, it is not
under a memory/ directory, and any date in its name is the day being checked. It must also
still exist and not sit in a temp directory or a .claude/worktrees/ checkout (both get deleted).

Prints TSV, one row per handoff note (one row per session without one):
  verdict  session  written  calls_after  last_active  project  path
verdict: fresh | stale | none | unknown   (running sessions, from --live)
         closed | closed-none             (sessions no longer running that worked that day)
"""

import argparse
import json
import os
import re
from datetime import date, datetime
from pathlib import Path

SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TEMP_ROOTS = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")
STALE_AFTER = 10  # tool calls after the latest handoff that make it stale


def is_handoff(path, day):
    name = Path(path).name.lower()
    # an older note edited today (e.g. marked superseded) is not today's handoff
    dates = set(re.findall(r"\d{4}-\d{2}-\d{2}", name))
    return (
        "handoff" in name
        and name.endswith(".md")
        and "/memory/" not in path
        and (not dates or day.isoformat() in dates)
    )


def usable(path):
    # a denied or failed Write leaves no file; temp dirs and worktrees get deleted
    return (
        Path(path).is_file()
        and not path.startswith(TEMP_ROOTS)
        and "/.claude/worktrees/" not in path
    )


def tilde(path):
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home + os.sep) else path


def hhmm(ts):
    return ts.strftime("%H:%M") if ts else "-"


def scan(transcripts, day):
    """Return ({handoff path: last write time}, [tool call times]) for calls made on `day`."""
    handoffs, calls = {}, []
    for transcript in transcripts:
        try:
            fh = transcript.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"tool_use"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(
                        entry["timestamp"].replace("Z", "+00:00")
                    ).astimezone()
                except (ValueError, KeyError, TypeError, AttributeError):
                    continue
                if entry.get("type") != "assistant" or ts.date() != day:
                    continue
                for block in (entry.get("message") or {}).get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    calls.append(ts)
                    path = (block.get("input") or {}).get("file_path") or ""
                    if block.get("name") in ("Write", "Edit") and is_handoff(path, day):
                        handoffs[path] = max(ts, handoffs.get(path, ts))
    return {p: ts for p, ts in handoffs.items() if usable(p)}, calls


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
    p.add_argument("--date", type=date.fromisoformat, default=date.today())
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
            latest = max(handoffs.values())
            after = sum(c > latest for c in calls)
            verdict = (
                ("fresh" if after <= STALE_AFTER else "stale") if name else "closed"
            )
            for path, ts in sorted(handoffs.items(), key=lambda kv: kv[1]):
                rows.append(
                    (
                        verdict,
                        name or sid[:8],
                        hhmm(ts),
                        str(sum(c > ts for c in calls)),
                        hhmm(last),
                        t.parent.name,
                        tilde(path),
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
                )
            )

    for n in names:
        if n not in registry:
            rows.append(("unknown", n, "-", "-", "-", "-", "-"))
        elif registry[n]["sessionId"] not in seen:
            rows.append(("none", n, "-", "-", "-", "-", "-"))

    print("\n".join("\t".join(r) for r in rows))


if __name__ == "__main__":
    main()
