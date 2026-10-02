#!/usr/bin/env python3
"""Start a Claude Code session for each open item of the daily note's focus list that links a
handoff note, asking it to read the note and say what to do next.

--open agents (default): background sessions, listed together by `claude agents`.
--open tabs: tabs of one new Terminal window, opened with ⌘T, which needs Accessibility
  permission for the app running this.
--open windows: a Terminal window each.

The focus list runs from the heading to the next heading of its level or higher, or a --- rule.
An item is a top-level "- " or "1. " line in it; one checked "[x]" or cancelled "[-]" is
skipped. Its note is its first link to a handoff note: a .md file whose name contains "handoff",
or a dated one in a handoff/ or handoffs/ directory, outside memory/. A link is a path (~/… or
/…, in backticks or not) or an Obsidian [[wikilink]], looked up in the daily note's vault.

The session starts in the project the note belongs to: ~/.claude/projects/<dir>/… maps back to
the real path listed in ~/.claude.json. A /session-handoffs snapshot (…_snapshot-<sid8>.md) sits
in the project of the session that wrote it, so it starts in the project of the session it
describes. Any other note starts in the current directory.

A note that a session already works from is skipped, so a re-run starts nothing twice and a
session left open since yesterday is found: the session a snapshot describes, or one whose first
prompt names the note, or that wrote or edited it (itself or through a subagent). Reading a note
doesn't count, nor do later messages: a /session-handoffs run reads every note, and tool output,
workflow results and other sessions' messages name notes the session isn't working on. Sessions
come from `claude agents --json --all`: running ones and background ones that finished, but not
failed ones. This one counts only through its first prompt, so a re-run from a session kickoff
started leaves that session's note alone. Of several sessions on one note, the newest (by its
transcript's first timestamp) is named. Inside Claude Code's sandbox, which lists running
sessions as failed, it stops with an error. Their transcripts and ~/.claude.json are not a
documented interface.

Prints TSV, one row per open item:  item  status  name  dir  note  title
status: opened | would open (--dry-run) | open in <session> | no note | missing | superseded |
        failed: … | not tried (after a failed tab)
        + " · carried Nd" when the date in the note's name is N ≥ 3 working days before
        today: a prompt to drop, delegate or do it

--digest opens nothing: for each open item, the session an "open in" row would name, found the
same way (whatever the note's state now), and the "Next:" line of its answer to the latest
request (else that answer's first line). Prints TSV:  item  state  name  answer
state: the session's state in `claude agents` (working, blocked, done…, - for an interactive
       one), else no session | no note | missing | superseded
"""

import argparse
import functools
import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

# one line, for a tab to type; --digest picks the reply's "Next:" line
PROMPT = (
    "Can you open {note} and tell me what I should do next? End with one plain line, no "
    "formatting: Next: <one step> · Needs me: yes/no · Time: <estimate>"
)
HEADING = re.compile(r"(#{1,6})\s")
FENCE = ("```", "~~~")
ITEM = re.compile(r"(?:[-*+]|\d+\.)\s+(?:\[(.)\]\s+)?(.*)")
DONE = "xX-"
# a path, not part of a URL or a query: "~/x/handoff.md", "`/Users/…/h.md`", "(~/…/h.md)", and
# at the end of a sentence "…/h.md."; not "…/h.md.bak"
PATH = re.compile(r"(?<![\w:/.~=-])(~?/[^\s`'\"<>()\[\]|]+?\.md)(?![\w-]|\.\w)")
WIKILINK = re.compile(r"\[\[([^\]|#]+)[^\]]*\]\]")
BOLD = re.compile(r"\*\*(.+?)\*\*")
DATED = re.compile(r"(?<!\d)20\d\d[-_]?[01]\d[-_]?[0-3]\d")
SNAPSHOT = re.compile(r"snapshot-([0-9a-f]{8})\.md$")
CARRIED = 3  # working days since the note's date that get an item flagged
# /session-handoffs' SUPERSEDED banner: a line that opens with the word, maybe after a date, and
# says what replaced it ("> ⏭️ **SUPERSEDED by x.md**", "> **2026-09-28: superseded. START AT …**")
BANNER = re.compile(
    r"\W*(?:\d{4}-\d{2}-\d{2}[^:\n]{0,20}:\s*\W*)?superseded\b(?=\s*(?:by\b|as\b|for\b|[.:;,→—–*-]|\d|$))",
    re.I,
)
EDIT_TOOLS = ("Write", "Edit")
# user entries that aren't a request: a local command (/model, /clear) or a ! shell line and
# their output, and a background task's notification. A skill command starts
# "<command-message>" and is one.
NOT_ASKED = ("<command-name>", "<local-command-", "<bash-", "<task-notification>")
# the answer's own "Next:" line, bold or not ("Next: x", "**Next step:** x"), with its text on
# that line; not "> Next: x" quoted from the note, "Next week: x" or "Next.js: x"
NEXT = re.compile(r"^[ \t]*[-*_#]*[ \t]*Next(?: steps?)?[*_]*:[*_]*[ \t]*(\S.*)$", re.M)
# Terminal can't be scripted to make a tab, so press ⌘T. Type the command only into a tab whose
# tty is new: if the keystroke went elsewhere, typing into the selected tab would feed it to
# whatever runs there, maybe another Claude session.
TAB = """
on run {cmd, wid}
    tell application "Terminal"
        activate
        if wid is "" then
            do script cmd
            return id of front window
        end if
        set w to window id (wid as integer)
        set index of w to 1
        set oldTtys to tty of every tab of w
    end tell
    tell application "System Events" to keystroke "t" using command down
    repeat 30 times
        delay 0.1
        tell application "Terminal"
            set t to selected tab of w
            if tty of t is not "" and oldTtys does not contain tty of t then
                do script cmd in t
                return wid
            end if
        end tell
    end repeat
    error "⌘T didn't open a new tab in the kickoff window"
end run
"""


def tilde(path):
    path, home = str(path), str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home + os.sep) else path


def is_handoff(path):
    p = Path(str(path).lower())
    return (
        p.suffix == ".md"
        and "memory" not in p.parts
        and (
            "handoff" in p.name
            # a dated note, not the folder's README or template
            or (p.parent.name in ("handoff", "handoffs") and DATED.search(p.name))
        )
    )


def section(text, heading):
    """Return the lines under the first heading containing `heading` (its #s and spacing aside),
    up to the next heading of its level or higher or a --- rule, leaving out code blocks."""
    want = heading.lstrip("#").strip()
    out, level, fenced = [], None, False
    for line in text.splitlines():
        if line.startswith(FENCE):
            fenced = not fenced
        if fenced or line.startswith(FENCE):
            continue
        m = HEADING.match(line)
        if level is None:
            if m and want in line:
                level = len(m.group(1))
        elif (m and len(m.group(1)) <= level) or line.strip() == "---":
            break
        else:
            out.append(line)
    if level is None:
        raise SystemExit(f'no heading containing "{want}"')
    return out


def items(lines):
    """Yield (done, text) for each top-level list item."""
    for line in lines:
        if m := ITEM.match(line):
            yield (m.group(1) or " ") in DONE, m.group(2)


def vault_of(daily):
    return next(
        (d for d in daily.parents if os.path.isdir(d / ".obsidian")), daily.parent
    )


@functools.cache
def vault_notes(vault):
    """{"/folder/name.md" in lowercase: path} for the vault's notes, hidden folders left out."""
    found = {}
    for root, dirs, files in os.walk(vault):  # skips folders it can't read
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.endswith(".md"):
                p = Path(root, f)
                found["/" + str(p.relative_to(vault)).lower()] = p
    return found


def wikilink(vault, name):
    """Find [[name]] or [[folder/name]] as Obsidian does: by the end of its path, in any case,
    the shallowest when several match; if none does, the path it would have."""
    name = name.strip().removesuffix(".md")
    want = f"/{name.lower()}.md"
    hits = [p for k, p in vault_notes(vault).items() if k.endswith(want)]
    return min(hits, key=lambda p: (len(p.parts), str(p)), default=vault / f"{name}.md")


def note_of(text, vault):
    """Return the item's first link to a handoff note (maybe a file that doesn't exist), or None."""
    links = [(m.start(), Path(m.group(1)).expanduser()) for m in PATH.finditer(text)]
    links += [(m.start(), wikilink(vault, m.group(1))) for m in WIKILINK.finditer(text)]
    return next((p for _, p in sorted(links) if is_handoff(p)), None)


def unusable(note):
    """Why a session can't start from the note ("missing", "superseded"), or None."""
    try:
        text = note.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:  # gone, a folder, or in one this process can't read
        return "missing"
    lines = [line.strip() for line in text.splitlines()[:200]]
    if lines and lines[0] == "---":  # skip YAML frontmatter
        end = next(
            (i for i, line in enumerate(lines[1:], 1) if line == "---"), len(lines)
        )
        lines = lines[end + 1 :]
    head = [line for line in lines if line][:6]
    return "superseded" if any(BANNER.match(line) for line in head) else None


def snapshot_of(note):
    """The sid8 of the session a /session-handoffs snapshot (…_snapshot-<sid8>.md) describes."""
    m = SNAPSHOT.search(note.name)
    return m.group(1) if m else None


def day_of(name):
    """The date in a file name (2026-09-28, 2026_09_28 or 20260928), or None."""
    m = DATED.search(name)
    try:
        return (
            datetime.strptime(re.sub(r"[-_]", "", m.group()), "%Y%m%d").date()
            if m
            else None
        )
    except ValueError:
        return None


def carried(note, day):
    """Working days (Mon–Fri) from the date in the note's name to `day`, or None if undated. A
    date over a year back is taken for an ID that looks like one ("pr2015-01-02"): no note gets
    carried that long."""
    since = day_of(note.name)
    if since is None or (day - since).days > 366:
        return None
    return sum(
        (since + timedelta(n)).weekday() < 5 for n in range(1, (day - since).days + 1)
    )


def title(text):
    m = BOLD.search(text)
    t = m.group(1) if m else PATH.sub("", WIKILINK.sub("", text))
    return " ".join(t.split()).strip(" :—-`")


def slug(text, taken):
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(base) > 40:  # cut at a word
        base = base[:41].rsplit("-", 1)[0][:40]
    name, n = base or "kickoff", 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    taken.add(name)
    return name


def project_dir(note, claude_dir, known):
    """The project a note belongs to, from the ~/.claude/projects/<dir>/ it sits in, or for a
    snapshot the one holding the transcript of the session it describes; else None."""
    sid8 = snapshot_of(note)
    source = next(claude_dir.glob(f"projects/*/{sid8}*.jsonl"), None) if sid8 else None
    try:
        encoded = (source or note).relative_to(claude_dir / "projects").parts[0]
    except (ValueError, IndexError):
        return None
    return next(
        (
            k
            for k in known
            if re.sub(r"[^A-Za-z0-9]", "-", k) == encoded and os.path.isdir(k)
        ),
        None,
    )


def transcript_of(claude_dir, sid):
    return next(
        (t for t in claude_dir.glob(f"projects/*/{sid}.jsonl") if t.is_file()), None
    )


def created(claude_dir, sid):
    """When a session began: its transcript's first timestamp, which resuming or respawning it
    doesn't move ("" without one)."""
    t = transcript_of(claude_dir, sid)
    stamps = (e["timestamp"] for e in entries(t) if isinstance(e.get("timestamp"), str))
    return next(stamps, "") if t else ""


def sessions(me, claude_dir):
    """Return {session id: (name, state)}, oldest first, for the sessions, this one included:
    running, or in the background and finished but not failed."""
    if os.environ.get("SANDBOX_RUNTIME"):
        raise SystemExit(
            "Claude Code's sandbox lists running sessions as failed, so they can't be checked. "
            "Run this outside the sandbox."
        )
    r = subprocess.run(
        ["claude", "agents", "--json", "--all"], capture_output=True, text=True
    )
    if r.returncode:
        raise SystemExit(f"`claude agents --json --all` failed: {r.stderr.strip()}")
    listed = json.loads(r.stdout)
    if me and me not in {s.get("sessionId") for s in listed}:
        raise SystemExit(
            "`claude agents --json` doesn't list this session, so the running sessions can't be "
            "checked. Run this outside the sandbox."
        )
    live = [s for s in listed if s.get("sessionId") and s.get("state") != "failed"]
    # startedAt moves when a session is resumed or respawned: it only breaks ties
    live.sort(
        key=lambda s: (created(claude_dir, s["sessionId"]), s.get("startedAt") or 0)
    )
    return {
        s["sessionId"]: (s.get("name") or s["sessionId"][:8], s.get("state") or "-")
        for s in live
    }


def blocks(entry):
    """A transcript entry's content blocks; plain-text content is one text block."""
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return (
        [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
    )


def text_of(entry):
    return "\n".join(
        str(b.get("text")) for b in blocks(entry) if b.get("type") == "text"
    )


def prompt(entry):
    """The text of a request the user typed in a transcript entry, else None: tool output, skill
    text, or a local command (/model, a ! shell line) and its output."""
    if (
        entry.get("type") != "user"
        or entry.get("isMeta")
        or entry.get("isCompactSummary")
    ):
        return None
    text = text_of(entry)
    return text if text and not text.lstrip().startswith(NOT_ASKED) else None


def names(text, note):
    return str(note) in text or tilde(note) in text


def edits(entry):
    """The paths a transcript entry writes or edits."""
    return {
        str((b.get("input") or {}).get("file_path"))
        for b in blocks(entry)
        if b.get("type") == "tool_use" and b.get("name") in EDIT_TOOLS
    }


def entries(transcript, keep=lambda line: True):
    """A transcript's entries on the lines `keep` passes (checked before parsing, which is the
    slow part), skipping lines that aren't JSON objects; none if it can't be read."""
    try:
        with transcript.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not keep(line):
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict):
                    yield entry
    except OSError:  # gone since the glob, a folder, or not ours to read
        return


def worked_from(transcript, notes, sid, main, edited=True):
    """The notes a transcript names in its first prompt (if it's the session's `main` one, not a
    subagent's) or, if `edited`, writes or edits. A snapshot is written by another session than
    the one it describes, so its writer doesn't work from it."""
    found, first = set(), None if main else ""

    def keep(line):  # after the first prompt, only lines naming a note matter
        return first is None or any(n.name in line for n in notes)

    for entry in entries(transcript, keep):
        if first is None and (first := prompt(entry)) is not None:
            found.update(n for n in notes if names(first, n))
            if not edited:
                break
        elif edited:
            found.update(
                n
                for n in notes
                if str(n) in edits(entry) and snapshot_of(n) in (None, sid[:8])
            )
    return found


def claims(live, notes, claude_dir, me=None):
    """Return {note: session id} for the notes a session in `live` (ids, oldest first) already
    works from: of several, the newest, so today's session wins over yesterday's. This session
    (`me`) works only from the note its first prompt names, not from ones it or its subagents
    touched since: it may be the morning session tidying notes."""
    held = {}
    for sid in live:
        own = sid == me
        for n in notes:
            if snapshot_of(n) == sid[:8]:
                held[n] = sid
        for t in claude_dir.glob(f"projects/*/{sid}.jsonl"):
            subagents = () if own else t.parent.glob(f"{sid}/subagents/**/*.jsonl")
            for f in (t, *subagents):
                for n in worked_from(f, notes, sid, main=f == t, edited=not own):
                    held[n] = sid
    return held


def latest_reply(transcript):
    """The session's latest answer: the text of its end-of-turn messages since the last request,
    not the narration between tool calls. None before it has answered."""
    latest, turn = None, []
    for entry in entries(transcript):
        msg = entry.get("message")
        if prompt(entry) is not None:
            turn = []
        elif (
            isinstance(msg, dict)
            and msg.get("stop_reason") == "end_turn"
            and text_of(entry)
        ):
            turn.append(text_of(entry))
            latest = "\n".join(turn).strip() or latest
    return latest


def answer(reply):
    """The reply's "Next:" line (the last that says "Needs me", else the last), else its first
    line cut to 120 characters, on one line."""
    if not reply:
        return "(no reply yet)"
    hits = [h.strip("*_ ") for h in NEXT.findall(reply)]
    hits = [h for h in hits if "Needs me" in h] or [
        h for h in hits if h
    ]  # not a bare "**"
    text = hits[-1] if hits else reply.splitlines()[0][:120]
    return " ".join(text.split())


def digest(todo, state, live, claude_dir, me):
    """Rows (item, state, name, answer): for each open item, the session kickoff would name for
    its note (whatever the note's state: a session may have replaced it), and its latest answer."""
    held = claims(live, {n for _, _, n in todo if n}, claude_dir, me)
    rows = []
    for i, _, note in todo:
        sid = held.get(note)
        if sid is None:
            why = "no note" if note is None else state[note] or "no session"
            rows.append((str(i), why, "-", "-"))
            continue
        name, status = live[sid]
        t = transcript_of(claude_dir, sid)
        rows.append((str(i), status, name, answer(latest_reply(t) if t else None)))
    return rows


def start(how, window, where, name, prompt):
    """Start `claude -n name prompt` in `where`: in the background (agents), in a new Terminal
    window (windows, or the first of tabs), or in a new tab of `window` (tabs). Return the
    Terminal window's id, or None."""
    if how == "agents":
        subprocess.run(
            ["claude", "--bg", "-n", name, prompt],
            cwd=where,
            check=True,
            capture_output=True,
            text=True,
        )
        return None
    claude = shutil.which("claude") or "claude"
    # the Terminal shell doesn't inherit this environment: carry the config dir across
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    env = f"CLAUDE_CONFIG_DIR={shlex.quote(config)} " if config else ""
    cmd = (
        f"cd {shlex.quote(where)} && {env}exec {shlex.quote(claude)} "
        f"-n {shlex.quote(name)} {shlex.quote(prompt)}"
    )
    out = subprocess.run(
        ["osascript", "-", cmd, (window or "") if how == "tabs" else ""],
        input=TAB,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("note", type=Path, help="the daily note")
    p.add_argument(
        "--heading", default="Today's Focus", help="text in the focus list's heading"
    )
    p.add_argument(
        "--only", type=int, nargs="+", metavar="N", help="open only these items"
    )
    p.add_argument(
        "--open",
        choices=("agents", "tabs", "windows"),
        default="agents",
        help="where the sessions go (default: agents)",
    )
    p.add_argument("--dry-run", action="store_true", help="report, open nothing")
    p.add_argument(
        "--digest",
        action="store_true",
        help="list each item's session and its latest answer, open nothing",
    )
    p.add_argument(
        "--claude-dir",
        type=Path,
        default=Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser(),
    )
    a = p.parse_args(argv)

    daily = a.note.expanduser()
    vault = vault_of(daily)
    todo = [
        (i, text, note_of(text, vault))
        for i, (done, text) in enumerate(
            items(section(daily.read_text(), a.heading)), 1
        )
        if not done and (not a.only or i in a.only)
    ]
    state = {n: unusable(n) for _, _, n in todo if n}
    me = os.environ.get("CLAUDE_CODE_SESSION_ID")
    live = sessions(me, a.claude_dir)
    if a.digest:
        rows = [
            ("item", "state", "name", "answer"),
            *digest(todo, state, live, a.claude_dir, me),
        ]
        print("\n".join("\t".join(r) for r in rows))
        return
    usable = {n for n, s in state.items() if not s}
    held = {
        n: live[sid][0] for n, sid in claims(live, usable, a.claude_dir, me).items()
    }
    config = (
        a.claude_dir / ".claude.json"
        if os.environ.get("CLAUDE_CONFIG_DIR")
        else Path.home() / ".claude.json"
    )
    try:
        known = list(json.loads(config.read_text()).get("projects", {}))
    except (OSError, ValueError):
        known = []

    taken, window, failed = {name for name, _ in live.values()}, None, False
    rows = [("item", "status", "name", "dir", "note", "title")]
    for i, text, note in todo:
        t = title(text) or (note.stem if note else "")
        name = where = "-"
        if note is None:
            status = "no note"
        elif state[note]:
            status = state[note]
        elif note in held:
            status = f"open in {held[note]}"
        else:
            where = project_dir(note, a.claude_dir, known) or os.getcwd()
            name = slug(t, taken)
            status = "would open"
            if failed:  # ⌘T may be landing in another app: press no more
                status = "not tried"
            elif not a.dry_run:
                try:
                    prompt = PROMPT.format(note=tilde(note))
                    window = start(a.open, window, where, name, prompt)
                    status = "opened"
                except (OSError, subprocess.CalledProcessError) as err:
                    why = getattr(err, "stderr", None) or str(err)
                    status = f"failed: {' '.join(why.split())}"
                    failed = a.open == "tabs"
            if status in ("opened", "would open"):
                held[note] = name  # a second item with this note gets no second session
        days = carried(note, date.today()) if note and not state[note] else None
        if (days or 0) >= CARRIED:  # flagged after the held check: it still opens once
            status += f" · carried {days}d"
        rows.append(
            (str(i), status, name, tilde(where), tilde(note) if note else "-", t)
        )
    print("\n".join("\t".join(r) for r in rows))


if __name__ == "__main__":
    main()
