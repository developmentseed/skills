#!/usr/bin/env python3
"""Report which Claude Code sessions on this machine left a handoff note, and which didn't.

Read-only and safe to re-run. A session is running if the registry (<config>/sessions/*.json) or
`claude agents --json` lists it (inside Claude Code's Bash sandbox the CLI lists only some, or none,
so it never replaces the registry); each session's transcript
(<config>/projects/*/<sessionId>.jsonl, plus its subagents' under projects/*/<sessionId>/subagents/)
records every Write, Edit and NotebookEdit with its file path and time. Neither the registry nor the
transcript is a documented interface: if they can't be read, it exits with an error rather than
print an empty report (a registry that moved isn't noticed: every session the CLI doesn't list then
reads as closed). Run from a terminal, it can't tell that from a window in which no session used a
tool, and exits with an error for both. <config> is $CLAUDE_CONFIG_DIR, else ~/.claude. The session
running this ($CLAUDE_CODE_SESSION_ID) is left out, and so is automation (claude -p, the SDK) that
is no longer running. A session opened to run this report (its first tool call runs this script or
loads the skill) is never reported as lacking a note.

The window runs from the start of --date to now. --date defaults to 5 hours ago, so a run
shortly after midnight still covers the evening.

A note is a .md file whose name contains "handoff", or a dated one in a handoff(s)/ directory
(not a PR or issue body), outside memory/, temp dirs and git worktrees.
- Out of date: a session is stale when, after its latest write to a note, it made more than 30
  tool calls in its main conversation or file edits through its subagents. More than 5 when that
  write is another session's snapshot of it, which can't know what came after it.
- Listed: its notes that still exist, don't open with a SUPERSEDED banner or a COMPANION line,
  and have any date in their name between --date and 3 days after it. If none qualify, its
  latest usable note. A snapshot named ..._snapshot-<sid8>.md that a run of the report writes
  (a session opened for it, or any session's subagent, as in step 5) counts for the session
  it describes, not its writer; another session's write of it is that session's own note. It
  counts until the session's own note (its newest named for --date, else its newest) covers it:
  written after it, or at most 5 calls before it (replaced). Only a snapshot a run of the report
  wrote last is replaced; one marked SUPERSEDED always is.

Prints the day covered and the time now, then TSV after a header: one row per listed note, one
per session without one, and one per replaced snapshot:
  verdict  session  written  calls_after  last_active  project  path  title
verdict: fresh | stale | none                (running sessions)
         closed | closed-stale | closed-none (sessions no longer running)
         replaced: a snapshot its session's own note covers; title is that note's path
Sessions without a note that made fewer than 30 calls (a quick question) are left out.

--digest NAME|SID8 instead prints that session's latest note, the path for its snapshot (in
--notes-dir if given, else the project dir of the session running this), and a compact log of its
window: prompts, Claude's messages, messages from other sessions, one line per tool call, no tool
output, common secret shapes and IPv4 addresses masked (best effort: a password written in prose
gets through). NAME is a running session's name; SID8 is the first 8+ characters of any session's
id. It exits with an error instead of printing a path or log a snapshot can't use: a NAME or SID8
that matches no session or several, a --notes-dir that isn't an absolute path to a folder where
notes are found, a snapshot that a session other than a run of the report wrote last (it may work
from it) unless it opens with a SUPERSEDED banner, or an empty log.
"""

import argparse
import json
import os
import re
import subprocess
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TEMP_ROOTS = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")
STALE_AFTER = 30  # work after the latest note that makes it out of date
SNAPSHOT_STALE_AFTER = 5  # a snapshot can't know what came after it
MIN_WORK = 30  # below this, a session without a note is not worth reporting
# kinds of a running working session: interactive, and `claude --bg` sessions, which the registry
# calls "bg" and `claude agents --json` "background"
LIVE_KINDS = ("interactive", "bg", "background")
# a note may be named for a day up to this far ahead (written on Friday for Monday)
AHEAD_DAYS = 3
FILE_TOOLS = ("Write", "Edit", "NotebookEdit")
# a date, maybe followed by a time (202609281030), but not inside a longer number
NAME_DATE = re.compile(
    r"(?<!\d)(20\d\d)[-_]?([01]\d)[-_]?([0-3]\d)(?=(?:\d{4}|\d{6})?(?!\d))"
)
SNAPSHOT = re.compile(r"snapshot-([0-9a-f]{8})\.md$")
REPORT_RUN = re.compile(r"python3?\s+\S*/handoff_status\.py")
# a line that opens with the word, maybe after a date, and says what replaced it:
# "> ⏭️ **SUPERSEDED by x.md**", "> **2026-09-28: superseded. START AT …**", "SUPERSEDED 2026-09-24 → x".
# Not "## Superseded options", "superseded in part", or the word in the middle of prose. Also
# "> COMPANION of <path>": a note kept on purpose beside the current one, which links it. Only
# that quoted form: many notes open with "Companion notes: …" naming live companions.
COMPANION = re.compile(r">\W*companion of\b", re.I)
BANNER = re.compile(
    COMPANION.pattern
    + r"|\W*(?:\d{4}-\d{2}-\d{2}[^:\n]{0,20}:\s*\W*)?superseded\b(?=\s*(?:by\b|as\b|for\b|[.:;,→—–*-]|\d|$))",
    re.I,
)
# a private key block, up to its END line (or the end of the text when it has none); masked
# before SECRET, whose labels ("private_key": …) would otherwise hide only its first word
PEM = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY[A-Z ]*-----.*?(?:-----END [A-Z ]*PRIVATE KEY[A-Z ]*-----|$)"
)
SECRET = re.compile(
    "|".join(
        (
            # a value after its label, which is kept: "Bearer x", "Authorization: Token x",
            # "TOKEN=x", "S3_KEY: x", "--password 'x'"; a quoted value is masked whole. The
            # bounded {0,40} keeps a long unbroken blob from taking quadratic time.
            r"(?i:((?:bearer|basic)\s+|authorization:\s*(?:\w+\s+)?"
            r"|[\w-]{0,40}(?:token|passw(?:or)?d|secret|(?:api|access|[_-])key|credential)[\w-]{0,40}[\"']?\s*[=:]\s*"
            r"|--[\w-]{0,40}(?:token|password|secret|key)[\w-]{0,40} +))"
            r"(?:\"[^\"]*\"|'[^']*'|[^\s\"',}]+)",
            # values recognisable by their shape
            r"\b(?:ghp_|gho_|ghs_|ghu_|github_pat_|glpat-|hf_|pypi-|npm_|[rs]k_(?:live|test)_|sk-"
            r"|xox[abeprs]-)[A-Za-z0-9_-]{10,}",
            r"\bAKIA[0-9A-Z]{16}\b",
            r"\bAIza[\w-]{35}",  # Google API key
            r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]*",  # JWT
            r"(?<=[?&])sig=[^&\s\"']+",  # signed URL (Azure SAS)
            r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)",  # user:password@ in a URL
            r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}\b(?!\.\d)",  # IPv4 address
        )
    )
)
DIGEST_CHARS = 25_000  # under Claude Code's default Bash output cap (30k characters)


def default_day(now):
    return (now - timedelta(hours=5)).date()


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


def in_worktree(path):
    # a `git worktree add` checkout (Claude's .claude/worktrees/ included) has a .git file pointing
    # into .git/worktrees/; a submodule's points into .git/modules/, a main checkout has a .git dir
    for parent in Path(path).parents:
        dot_git = parent / ".git"
        if dot_git.is_file():
            try:
                return "/worktrees/" in dot_git.read_text(errors="replace")
            except OSError:
                return False
        if dot_git.is_dir():
            return False
    return False


def is_note(path):
    p = Path(path.lower())
    return (
        (
            "handoff" in p.name
            # a dated note, not the folder's README or template, nor a PR or issue body kept there
            # ("body" anywhere in the name, "antibody" too; other drafts kept there still count)
            or (
                p.parent.name in ("handoff", "handoffs")
                and NAME_DATE.search(p.name)
                and "body" not in p.name
            )
        )
        and p.name.endswith(".md")
        and "/memory/" not in path
        and not path.startswith(TEMP_ROOTS)
        and not in_worktree(path)
    )


def dated_for(path, day):
    # an older note edited that day isn't the one to start from, nor is one named after a
    # deadline; one written a few days ahead (on Friday for Monday) is
    dates = {"-".join(d) for d in NAME_DATE.findall(Path(path).name)}
    ahead = (day + timedelta(days=AHEAD_DAYS)).isoformat()
    return not dates or any(day.isoformat() <= d <= ahead for d in dates)


def note_title(path, banner=BANNER):
    """Return the note's title (its `#` heading, else its file name), or None if it's gone (a denied
    Write leaves no file) or opens with a SUPERSEDED or COMPANION line (it points to another note)."""
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
    if any(banner.match(line) for line in head):
        return None
    # a level-2 heading is a section ("## Status"), not the note's title
    heading = next((h[2:].strip() for h in head if h.startswith("# ")), "")
    return heading or Path(path).stem


def tilde(path):
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home + os.sep) else path


def hhmm(ts):
    return ts.strftime("%H:%M") if ts else "-"


def short(text, n):
    text = PEM.sub("***", " ".join(str(text).split()))
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


def opened_for_report(transcript):
    """True if the session's first tool call ever runs this script or loads this skill."""
    for _, entry in entries(
        transcript, datetime.fromtimestamp(0, timezone.utc), needle='"tool_use"'
    ):
        for block in (entry.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                i = block.get("input") or {}
                return bool(REPORT_RUN.search(str(i.get("command")))) or str(
                    i.get("skill")
                ).endswith("session-handoffs")
    return False


def transcripts(claude_dir, day):
    """Yield each session's transcript written to since the start of `day`."""
    for t in sorted(claude_dir.glob("projects/*/*.jsonl")):
        try:
            if (
                SESSION_ID.fullmatch(t.stem)
                and datetime.fromtimestamp(t.stat().st_mtime).date() >= day
            ):
                yield t
        except OSError:
            continue


def scan(transcript, subagents, day):
    """Return ({note path: last write time}, {notes whose last write came from a subagent},
    [work times], entrypoint, tool calls read) from the start of `day`. Work is every tool call in
    the main conversation plus file edits by subagents: their reads are noise, their edits (new
    worktrees, files) are what a handoff must mention. The entrypoint (cli, sdk-py, …) tells an
    interactive session from automation."""
    # last: note path -> (last write, whether a subagent made it)
    last, work, entrypoint, calls = {}, [], None, 0
    for f in (transcript, *subagents):
        for ts, entry in entries(f, start_of(day), needle='"tool_use"'):
            if entry.get("type") != "assistant":
                continue
            if f is transcript and entrypoint is None:
                entrypoint = entry.get("entrypoint")
            for block in (entry.get("message") or {}).get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                calls += 1
                i = block.get("input") or {}
                path = str(i.get("file_path") or i.get("notebook_path") or "")
                edit = block.get("name") in FILE_TOOLS
                if edit and is_note(path):
                    last[path] = max(
                        last.get(path, (ts, False)), (ts, f is not transcript)
                    )
                if f is transcript or (edit and not path.startswith(TEMP_ROOTS)):
                    work.append(ts)
    # step 5 writes each snapshot from a subagent, so a subagent's write is a run's. A session's
    # own conversation works from what it writes, even after it ran this script
    runs = {n for n, (_, sub) in last.items() if sub}
    return {n: ts for n, (ts, _) in last.items()}, runs, work, entrypoint, calls


def agents():
    """Running sessions from `claude agents --json`, the documented list, or [] if it can't be
    read. Inside Claude Code's Bash sandbox it lists only some sessions, or none, even with the
    session running this among them, so it adds to the registry and never replaces it."""
    try:
        sessions = json.loads(
            subprocess.run(
                ["claude", "agents", "--json"],
                capture_output=True,
                text=True,
                timeout=10,
                # no call to api.anthropic.com, which the sandbox blocks with a warning
                env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
            ).stdout
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return sessions if isinstance(sessions, list) else []


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--date",
        type=date.fromisoformat,
        default=default_day(datetime.now()),
        help="start of the window",
    )
    p.add_argument(
        "--digest",
        metavar="NAME|SID8",
        help="print a session's latest note and a compact log of its day",
    )
    p.add_argument(
        "--notes-dir",
        type=lambda s: Path(s).expanduser(),  # the model may pass a quoted "~/…"
        help="folder for the --digest snapshot",
    )
    p.add_argument(
        "--claude-dir",
        type=Path,
        default=Path(
            os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude"
        ).expanduser(),
    )
    a = p.parse_args(argv)
    me = os.environ.get("CLAUDE_CODE_SESSION_ID")

    projects = a.claude_dir / "projects"
    if not projects.is_dir():
        raise SystemExit(
            f"{tilde(str(projects))} not found: "
            "set CLAUDE_CONFIG_DIR if Claude Code keeps its data elsewhere"
        )

    registry = list((a.claude_dir / "sessions").glob("*.json"))
    entries = []
    for f in registry:
        try:
            entries.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    # from the registry alone: a CLI list mustn't hide a registry that changed
    registered = any(isinstance(s, dict) and s.get("sessionId") for s in entries)
    live = {}  # running working sessions, in either list: session id -> name
    for s in agents() + entries:
        sid = s.get("sessionId") if isinstance(s, dict) else None
        if sid and sid != me and s.get("kind", "interactive") in LIVE_KINDS:
            live[sid] = s.get("name") or sid[:8]

    def subagents(sid):
        return list(a.claude_dir.glob(f"projects/*/{sid}/subagents/**/*.jsonl"))

    if a.digest:
        # a running session by name, or any session by the first 8+ characters of its id
        named = [s for s, n in live.items() if n == a.digest]
        if len(named) > 1:
            raise SystemExit(
                f"{a.digest}: {len(named)} running sessions have this name, give the sid8"
            )
        sid = named[0] if named else None
        if sid is None and re.fullmatch(r"[0-9a-f-]{8,36}", a.digest):
            sid = a.digest + "*"
        matches = {
            t.stem: t
            for t in (a.claude_dir.glob(f"projects/*/{sid}.jsonl") if sid else ())
            if SESSION_ID.fullmatch(t.stem)
        }
        if len(matches) > 1:
            raise SystemExit(
                f"{a.digest}: matches {len(matches)} sessions, give more of the id"
            )
        if not matches:
            raise SystemExit(f"{a.digest}: no transcript found")
        (t,) = matches.values()
        own = next(a.claude_dir.glob(f"projects/*/{me}.jsonl"), None) if me else None
        snapshot = (a.notes_dir or (own or t).parent) / (
            f"handoff_{a.date}_snapshot-{t.stem[:8]}.md"
        )
        # the script doesn't create the folder; a snapshot the check can't find would never count,
        # nor would a relative one, which lands wherever the subagent runs
        if a.notes_dir and not (
            a.notes_dir.is_absolute()
            and a.notes_dir.is_dir()
            and is_note(str(snapshot))
        ):
            raise SystemExit(
                f"--notes-dir '{tilde(str(a.notes_dir))}': not an absolute path, no such folder, or notes in it aren't found (memory/, temp dirs, git worktrees)"
            )
        # a snapshot someone else wrote last, the session it describes included, is a note they
        # work from: replacing it would lose their edits. Not once it opens with a SUPERSEDED
        # banner (and no COMPANION line): nobody works from it then
        superseded = note_title(snapshot) is None and note_title(snapshot, COMPANION)
        if snapshot.exists() and not superseded:
            writes = {}  # session: (its last write of the snapshot, whether a run made it)
            for s in transcripts(a.claude_dir, a.date):
                notes, runs = scan(s, subagents(s.stem), a.date)[:2]
                if str(snapshot) in notes:
                    writes[s] = notes[str(snapshot)], str(snapshot) in runs
            by = max(writes, key=writes.get, default=None)
            run = by and (writes[by][1] or by.stem == me or opened_for_report(by))
            if by and (by == t or not run):
                raise SystemExit(
                    f"{tilde(str(snapshot))}: session {live.get(by.stem, by.stem[:8])} wrote it last, "
                    "not a run of /session-handoffs, and may work from it: not replacing it"
                )
        # an empty log would make an empty snapshot: a format change, or nothing in the window
        log = digest(t, start_of(a.date))
        if not log:
            raise SystemExit(
                f"{a.digest}: nothing since {a.date} could be read from its transcript"
            )
        notes = scan(t, subagents(t.stem), a.date)[0]
        # its own notes, not the snapshots it wrote about other sessions
        about = {n: SNAPSHOT.search(n) for n in notes}
        written = {
            n: ts
            for n, ts in notes.items()
            if note_title(n) is not None
            and (about[n] is None or t.stem.startswith(about[n].group(1)))
        }
        if written:
            latest = max(written, key=written.get)
            print(
                f"latest note: {tilde(latest)} ({note_title(latest)}), last written {hhmm(written[latest])}"
            )
        else:
            print(f"latest note: none since {a.date}")
        print(f"snapshot: {tilde(str(snapshot))}")
        print(log)
        return

    # only the report needs the registry: --digest finds any session by its id
    if registry and not registered:
        raise SystemExit(
            f"no sessionId in {tilde(str(registry[0].parent))}/*.json: "
            "Claude Code's session registry may have changed"
        )
    # run from a session, its transcript holds the call running this script (from a subagent, in
    # the subagent's): if that can't be found or read, the format changed, even when sessions
    # started before an update still write the old one
    if me and not next(a.claude_dir.glob(f"projects/*/{me}.jsonl"), None):
        raise SystemExit(
            f"this session's transcript isn't in {tilde(str(projects))}/*/: "
            "Claude Code's transcript layout may have changed"
        )
    found, reports, credited, last, runs = {}, set(), set(), {}, {}
    changed = calls = 0  # transcripts written in the window, tool calls read from them
    for t in transcripts(a.claude_dir, a.date):
        sid = t.stem
        notes, runs[sid], work, entrypoint, read = scan(t, subagents(sid), a.date)
        changed, calls = changed + 1, calls + read
        if sid == me and not read:
            raise SystemExit(
                f"no tool call could be read from this session's transcript since {a.date}: "
                "Claude Code's transcript format may have changed"
            )
        if str(entrypoint).startswith("sdk") and sid not in live:
            continue  # automation (claude -p, the SDK), not someone's working session
        if opened_for_report(t):
            reports.add(sid)  # its calls ran the report: not work that needs a note
        found[sid] = (t, notes, work)
    # from a terminal there is no call of our own to look for, so a day without tools looks the same
    if changed and not calls:
        raise SystemExit(
            f"no tool call could be read from the transcripts changed since {a.date}: "
            "Claude Code's transcript format may have changed, or no session used a tool"
        )
    # a snapshot a run of this report wrote (this session included, which is then left out of the
    # report) counts for the session it describes. Another session's write of it stays its own
    # note: it works from it
    for sid, (_, notes, _) in found.items():
        for path, ts in list(notes.items()):
            m = SNAPSHOT.search(path)
            if not m:
                continue
            run = sid in reports or sid == me or path in runs[sid]
            run = run and not sid.startswith(m.group(1))
            last[path] = max(last.get(path, (ts, run)), (ts, run))
            source = next((s for s in found if s.startswith(m.group(1))), None)
            if run and source:
                own = found[source][1].get(path)
                del notes[path]
                if own is None or ts > own:  # unless the session edited it later itself
                    found[source][1][path] = ts
                    credited.add(path)
    # written last by a run of this report, not by a session working from it
    ours = {path for path, (_, run) in last.items() if run}
    # nor is an edit a run has since written over (step 5 rewrites a bannered snapshot)
    for _, notes, _ in found.values():
        for path in ours & notes.keys():
            if notes[path] < last[path][0]:
                del notes[path]
    found.pop(me, None)
    names = Counter(live.values())

    rows = [
        "verdict session written calls_after last_active project path title".split()
    ]
    for sid, (t, notes, work) in found.items():
        name = live.get(sid)
        label = f"{name} ({sid[:8]})" if names[name] > 1 else name or sid[:8]
        last = max(work, default=None)
        titles = {n: note_title(n) for n in notes}
        # notes that still exist and don't point elsewhere; only these count, so marking an old
        # note superseded doesn't make the session look up to date
        usable = {n: ts for n, ts in notes.items() if titles[n] is not None}
        # a snapshot fills a gap: once the session's own note covers it (written after it, or at
        # most SNAPSHOT_STALE_AFTER calls before it), that note replaces it. Found by name and on
        # disk, so one marked superseded is still reported as replaced, whenever the banner went
        # in (that edit is its last write); one a session edited without marking it is a note
        # someone works from, and stays
        snaps = [n for n in notes if sid[:8] in SNAPSHOT.findall(n)]
        own = {n: ts for n, ts in usable.items() if n not in snaps}
        # one named for another day is likely about other work: only if there is no other
        own = {n: ts for n, ts in own.items() if dated_for(n, a.date)} or own
        mine = max(own, key=own.get, default=None)
        replaced = [
            n
            for n in snaps
            if mine
            and os.path.exists(n)
            and (
                titles[n] is None
                or (
                    n in ours
                    and sum(own[mine] < w <= notes[n] for w in work)
                    <= SNAPSHOT_STALE_AFTER
                )
            )
        ]
        usable = {n: ts for n, ts in usable.items() if n not in replaced}
        if usable:
            newest = max(usable, key=usable.get)
            latest = usable[newest]
            after = sum(w > latest for w in work)
            stale = after > (
                SNAPSHOT_STALE_AFTER if newest in credited else STALE_AFTER
            )
            verdict = (
                ("stale" if stale else "fresh")
                if name
                else ("closed-stale" if stale else "closed")
            )
            listed = {n: ts for n, ts in usable.items() if dated_for(n, a.date)}
            if not listed:
                listed = {newest: latest}
            # before the session's notes, so a line for the snapshot is swapped, not doubled
            rows += [
                (
                    "replaced",
                    label,
                    hhmm(notes[n]),
                    "-",
                    hhmm(last),
                    t.parent.name,
                    tilde(n),
                    tilde(mine),
                )
                for n in replaced
            ]
            for n, ts in sorted(listed.items(), key=lambda kv: kv[1]):
                title = titles[n].replace("\t", " ")
                after_n = str(sum(w > ts for w in work))
                rows.append(
                    (
                        verdict,
                        label,
                        hhmm(ts),
                        after_n,
                        hhmm(last),
                        t.parent.name,
                        tilde(n),
                        title,
                    )
                )
        elif len(work) >= MIN_WORK and sid not in reports:
            rows.append(
                (
                    "none" if name else "closed-none",
                    label,
                    "-",
                    "-",
                    hhmm(last),
                    t.parent.name,
                    "-",
                    "-",
                )
            )

    # the run has the date but not the clock: after midnight, "today" is the wrong day
    print(f"date: {a.date}, now: {datetime.now():%Y-%m-%d %H:%M}")
    print("\n".join("\t".join(r) for r in rows))


if __name__ == "__main__":
    main()
