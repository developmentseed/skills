#!/usr/bin/env python3
"""Claude Code hook for /session-handoffs: one current handoff note per piece of work, and a line
for the user when a busy session has none.

Opt-in and read-only: it reads the hook's JSON on stdin and this session's transcript, prints JSON
or nothing, and never writes a file. With SESSION_HANDOFFS_GUARD=1:
- UserPromptSubmit, when the prompt asks for a handoff (any spelling; a path, a file name or a
  /command is not a request): this session's notes that are still current, and the memory lines
  naming them.
- PostToolUse after a Write that created a note: this session's other notes still current.
- Stop: if a note created this turn says it supersedes or replaces notes that still have no
  banner, Claude gets the list and one more turn. This session's snapshots it didn't edit are
  left to /session-handoffs.
With SESSION_HANDOFFS_NUDGE=1:
- Stop: the first time a session has made 30 tool calls over 2 hours without a note, a line for the
  user (not for Claude). Nothing is stored: it fires at the Stop where that holds and didn't at
  the previous Stop.
A turn is everything since the previous Stop.
A session's notes are the ones it wrote (another session's snapshot too, as in the report), read
(Read, or a shell command naming it) or was given in a prompt, plus snapshots of it
(..._snapshot-<sid8>.md) in any project dir or in the folder on the `session-handoffs notes:` line
of <config>/CLAUDE.md. Silent in subagents, plan and dontAsk modes and SDK runs the session
registry doesn't list as interactive. On any error: exit 0, no output.
"""

import json
import mmap
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# no __pycache__ beside the scripts either: this hook writes nothing
sys.dont_write_bytecode = True
# a half-edited collector must act like no guard, not break every prompt
try:
    from handoff_status import (
        LIVE_KINDS,
        MIN_WORK,
        SNAPSHOT,
        is_note,
        note_title,
        opened_for_report,
        tilde,
    )
except BaseException:
    sys.exit(0)

# handoff as typed: handsoff, hansoff, hansdoff, hansodd, handsoof, hand-off
ASK = re.compile(r"\bhan[a-z]{0,3}o{1,2}[fd]{1,2}|\bhand[- ]off", re.I)
# not a request: the skill's name, pasted text, quoted code, a path or a file name
# ("continue from ~/x/handoff_a.md", "run handoff_status.py"). Paths and file names are only
# tried where a word starts: tried at every character, a long pasted token took seconds
NOT_ASKED = re.compile(
    r"session-handoffs|<pasted_content[^>]*>.*?</pasted_content[^>]*>|`[^`]*`"
    r"|(?<![^\s`>])\S*/\S*|(?<![^\s`>])\S+\.[a-z]\w*",
    re.I | re.S,
)
# a path starts at a / (or ~/) that isn't inside a word or another path: the same paths as
# trying every /, without being quadratic on a long base64 run. Not handoff.md.bak or .md-old
MD = re.compile(r"(?<![\w~.+/-])~?/[^\s'\"`()<>\[\],;]+?\.md(?![\w-]|\.\w)", re.I)
MD_BYTES = re.compile(rb"\.md", re.I)
NAME = re.compile(r"[\w.-]+\.md(?![\w-]|\.\w)", re.I)
# a line that starts, after bullets, quote marks, emphasis or a heading's #, with Supersedes or
# Replaces; not what follows a word that negates: "Supersedes nothing", "a.md, not b.md"
SAYS = re.compile(r"[\s>*_+\-\"'`#]*(?:supersedes|replaces)\b", re.I)
CONTINUED = re.compile(r"(?:,|\band)\s*$", re.I)  # "Supersedes a.md and" + "b.md"
NEGATED = re.compile(r"\b(?:not|no|nothing|none|never)\b|n['’]t\b", re.I)
# the folder in backticks, else the rest of the line or of its inline code (an iCloud vault path
# has a space) less quotes, a final period and a trailing ", …" or " (…)" remark, unless the
# folder's own name has it ("Dropbox (Personal)")
NOTES_LINE = re.compile(r"session-handoffs notes:[ \t]*(?:`([^`\n]+)`|([^`\n]+))")
REMARK = re.compile(r"(?:,\s.*|\s+\(.*\))$")
SUMMARY = b'"stop_hook_summary"'
PATH_MAX = 4096  # no path is longer: a longer word (a pasted classpath) is not searched
MIN_HOURS = 2  # with the collector's MIN_WORK calls: a session worth a note
SHOW = 5
WROTE, READ, GIVEN = "written here", "read here", "its path was in a prompt"
SNAP, CHANGED = "snapshot of this session", "changed since this session last touched it"
# facts, not orders: text that reads like a system instruction can trip injection defences
FACTS = (
    "How /session-handoffs keeps one current note per piece of work: a note is updated in "
    "place with Edit, or replaced by a new note whose first lines say `Supersedes <old "
    "file>.md`; the replaced note's first line after any frontmatter then reads `> SUPERSEDED "
    "by <new path> (<YYYY-MM-DD>)`, so the next /session-handoffs report leaves it out. A "
    "snapshot of this session was written by another session from this one's transcript: it "
    "is replaced, not edited, and /session-handoffs adds its banner. A note kept on "
    "purpose beside the current one starts with `> COMPANION of <path>`. Memory lines that "
    "name a replaced note can point at its replacement. Notes about other work, and notes "
    "changed since this session last touched them, belong to other sessions."
)


def load(line):
    try:
        e = json.loads(line)
    except ValueError:
        return {}
    return e if isinstance(e, dict) else {}


def stamp(e):
    try:
        return datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")).timestamp()
    except (KeyError, TypeError, AttributeError, ValueError):
        return None


def is_prompt(e):
    # typed and queued prompts, /commands, task notifications, peer messages and idle
    # notices; not tool results, skill bodies, /compact or ! shell output
    return e.get("type") == "user" and bool(e.get("origin") or e.get("promptSource"))


def starts_turn(e):
    # so does a ! command's output (turnOrigin only): Claude answers it and Stop runs. The
    # paths it prints weren't given to this session, so it isn't a prompt
    return is_prompt(e) or (e.get("type") == "user" and bool(e.get("turnOrigin")))


def text(e):
    c = (e.get("message") or {}).get("content") or ""
    if isinstance(c, str):
        return c
    return " ".join(str(b.get("text", "")) for b in c if isinstance(b, dict))


def tool_uses(e):
    content = (e.get("message") or {}).get("content")
    if e.get("type") != "assistant" or not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]


def created(e):
    r = e.get("toolUseResult")
    ok = isinstance(r, dict) and r.get("type") == "create"
    return str(r.get("filePath") or "") if ok else ""


def own_note(path, sid):
    """A note, and not a snapshot of another session."""
    m = SNAPSHOT.search(path)
    return is_note(path) and (not m or sid.startswith(m.group(1)))


def notes_in(s):
    # a path has no whitespace, so word by word finds the same paths; MD is quadratic on a
    # long word, so only words that hold ".md" and could be a path are searched
    return [
        p
        for w in s.split()
        if len(w) <= PATH_MAX and ".md" in w.lower()
        for p in map(os.path.expanduser, MD.findall(w))
        if is_note(p)
    ]


def mapped(transcript):
    with open(transcript, "rb") as fh:
        return mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)


def last_turn(transcript):
    """(byte offset of the entry the turn starts from, that entry, the entries after it), or
    None. That is the previous Stop's stop_hook_summary entry, which Claude Code writes at each
    Stop when a Stop hook is configured (this one is), so a prompt, message or task notification
    queued mid-turn doesn't split the turn; an interrupted turn has none. Without one (a first
    turn), the latest prompt. Read back from the end: a long session costs no more than this."""
    with mapped(transcript) as m:
        cut = len(m)
        while (hit := m.rfind(SUMMARY, 0, cut)) >= 0:
            start, end = m.rfind(b"\n", 0, hit) + 1, m.find(b"\n", hit)
            end = len(m) if end < 0 else end
            e = load(m[start:end])
            if e.get("type") == "system" and e.get("subtype") == "stop_hook_summary":
                return start, e, [x for x in map(load, m[end:].split(b"\n")) if x]
            cut = start
        end, after = len(m), []
        while end > 0:
            start = m.rfind(b"\n", 0, end) + 1
            e = load(m[start:end])
            if starts_turn(e):
                return start, e, after[::-1]
            if e:
                after.append(e)
            end = start - 1
    return None


def before(transcript, offset):
    """(time of the first entry, tool calls up to MIN_WORK) before byte `offset`."""
    first, n, pos = None, 0, 0
    with open(transcript, "rb") as fh:
        for line in fh:
            pos += len(line)
            if pos > offset or (first and n >= MIN_WORK):
                break
            if first is None or b'"tool_use"' in line:
                e = load(line)
                first = first or stamp(e)
                n += len(tool_uses(e))
    return first, n


def lineage(transcript, sid):
    """{note: (how this session knows it, when it last touched it)} for the notes it wrote,
    read or was given; another session's snapshot only once it writes it. Only lines naming a
    .md file are parsed, so most tool output is skipped."""
    mine = {}

    def seen(path, how, ts, touched=True):
        # only a write or a Read moves the time: after `ls <note>` or a message naming it, a
        # rewrite by another session must still show as CHANGED. Writing another session's
        # snapshot makes it this session's note, as in the report: it works from it
        ours = path in mine or own_note(path, sid) or (how == WROTE and is_note(path))
        if ours and (touched or path not in mine):
            old = mine.get(path)
            mine[path] = (old[0] if old and how != WROTE else how, ts)

    with mapped(transcript) as m:
        hit = MD_BYTES.search(m)
        while hit:
            start, end = m.rfind(b"\n", 0, hit.start()) + 1, m.find(b"\n", hit.end())
            end = len(m) if end < 0 else end
            hit = MD_BYTES.search(m, end)
            e = load(m[start:end])
            ts, r = stamp(e), e.get("toolUseResult")
            # a Write or an Edit that went through
            if isinstance(r, dict) and r.get("filePath"):
                seen(str(r["filePath"]), WROTE, ts)
            elif is_prompt(e):
                for p in notes_in(text(e)):
                    seen(p, GIVEN, ts, touched=False)
            for b in tool_uses(e):
                i = b.get("input") or {}
                # a Read's path as is: an iCloud or Dropbox path has spaces
                if b.get("name") == "Read":
                    seen(str(i.get("file_path") or ""), READ, ts)
                elif b.get("name") == "Bash":
                    for p in notes_in(str(i.get("command") or "")):
                        seen(p, READ, ts, touched=False)
    return mine


def snapshots(sid, config):
    """Snapshots of this session, in any project dir or in the notes folder named in
    <config>/CLAUDE.md."""
    found = list(config.glob(f"projects/*/*_snapshot-{sid[:8]}.md"))
    try:  # a bad line loses only that folder: "~notes" raises RuntimeError
        m = NOTES_LINE.search((config / "CLAUDE.md").read_text(errors="replace"))
        if m:
            rest = (m.group(2) or "").strip().rstrip(".")
            # the remark is cut only when the whole text isn't the folder
            for s in (m.group(1), rest, REMARK.sub("", rest).rstrip(".")):
                folder = Path((s or "").strip().strip("'\"")).expanduser()
                if s and folder.is_absolute() and folder.is_dir():
                    found += folder.glob(f"*_snapshot-{sid[:8]}.md")
                    break
    except (OSError, RuntimeError):
        pass
    return [str(p) for p in found]


def current(sid, mine, config, skip=()):
    """[(note, how)] for this session's notes that exist and open without a banner:
    snapshots of it first, then the newest."""
    notes = dict(mine)
    # one it edited is its note, as in the report: step 2 won't banner that one
    notes.update(
        (p, (SNAP, None))
        for p in snapshots(sid, config)
        if notes.get(p, (None,))[0] != WROTE
    )
    rows = []
    for p, (how, ts) in notes.items():
        if p in skip or note_title(p) is None:
            continue
        if ts and os.path.getmtime(p) > ts + 60:
            how = f"{how}, {CHANGED}"  # another session may be writing it
        rows.append((p, how))
    return sorted(rows, key=lambda r: (r[1] != SNAP, -os.path.getmtime(r[0])))


def replaced(new, rows, sid):
    """The notes `new` names near its top on a line starting with Supersedes or Replaces (the
    next line's first name only when the line has none or ends in "," or "and"): full paths,
    then names of notes beside it, else of this session's one note by that name. Not this
    session's snapshots, unless it edited them: /session-handoffs banners those."""
    try:
        with open(new, encoding="utf-8", errors="replace") as fh:
            top = [line for line, _ in zip(fh, range(40))]
    except OSError:
        return set()
    said = []
    for line, below in zip(top, [*top[1:], ""]):
        if not SAYS.match(line):
            continue
        # up to a word that negates, not one in a path or file name ("go-no-go/"): a remark
        # after a name ("(no longer current)") keeps the name
        words = line.split()
        cut = next(
            (
                i
                for i, w in enumerate(words)
                if NEGATED.search(w) and "/" not in w and not NAME.search(w)
            ),
            None,
        )
        if cut is not None:
            said += words[:cut]
        elif NAME.search(line) and not CONTINUED.search(line):
            said.append(line)
        else:  # up to the end of the next line's first name: a link, a path with spaces
            n = NAME.search(below)
            said += [line, below[: n.end()] if n else ""]
    text = " ".join(said)
    named = set(notes_in(text))
    by_name = {}
    for p, _ in rows:
        by_name.setdefault(Path(p).name, []).append(p)
    # bare names, not the file name that ends a full path
    for n in NAME.findall(" ".join(w for w in text.split() if not MD.search(w))):
        beside, mine = str(Path(new).parent / n), by_name.get(n, [])
        if os.path.exists(beside):
            named.add(beside)
        elif len(mine) == 1:  # a name two of its notes share is skipped
            named.add(mine[0])
    # another session's snapshot it wrote is its note: nobody else banners that
    wrote = {p for p, how in rows if how == WROTE}
    return {
        p
        for p in named
        if (p in wrote or own_note(p, sid) and not SNAPSHOT.search(p))
        and note_title(p) is not None
    }


def names(line, note):
    """True if `line` names `note`: its file name as a whole path component, alone or ending a
    path to it (~/…, /…, projects/<dir>/…), not another folder's note of that name."""
    name = Path(note).name
    for m in re.finditer(
        r"(?<![^\s/`\"'(\[*])" + re.escape(name) + r"(?![\w-]|\.\w)", line
    ):
        # the full path first: an iCloud or Dropbox one has spaces
        if line[: m.end()].endswith((note, tilde(note))):
            return True
        head = re.split(r"[\s`\"'(\[*]", line[: m.start()])[-1]
        path = head + name
        if not head or os.path.expanduser(path) == note or note.endswith("/" + path):
            return True
    return False


def memory_lines(paths, transcript, config):
    """file:line of the memory entries naming these notes, in this session's project memory
    and in the memory of the project dirs that hold them. Not a snapshot's dir: that is the
    /session-handoffs run's project, and its memory lines are that run's."""
    projects = config / "projects"
    dirs = {transcript.parent}
    for p in map(Path, paths):
        if p.is_relative_to(projects) and not SNAPSHOT.search(p.name):
            dirs.add(projects / p.relative_to(projects).parts[0])
    return [
        f"{tilde(str(m))}:{n}"
        for d in sorted(dirs)
        for m in sorted((d / "memory").glob("*.md"))
        for n, line in enumerate(m.read_text(errors="replace").splitlines(), 1)
        if any(Path(p).name in line and names(line, p) for p in paths)
    ]


def listing(head, rows, transcript, config):
    if not rows:
        return None
    out = [head]
    for p, how in rows[:SHOW]:
        when = datetime.fromtimestamp(os.path.getmtime(p))
        # titles only of notes this session wrote and of its snapshots, unchanged since: a note
        # it only read or was pointed at may be anyone's file, and this is hook context
        ours = how.startswith((WROTE, SNAP)) and CHANGED not in how
        title = f": {note_title(p)[:80]}" if ours else ""
        out.append(f"- {tilde(p)} ({how}; modified {when:%d %b %H:%M}){title}")
    if len(rows) > SHOW:
        out.append(f"- and {len(rows) - SHOW} more")
    # not for this session's snapshots: their memory line is the /session-handoffs run's
    refs = memory_lines(
        [p for p, how in rows if not how.startswith(SNAP)], transcript, config
    )
    if refs:
        out.append("Memory lines naming them: " + ", ".join(refs[:8]))
    return "\n".join(out + [FACTS])


def context(event, s):
    return s and {
        "hookSpecificOutput": {"hookEventName": event, "additionalContext": s}
    }


def nudge(transcript, sid, config, turn):
    """A line for the user at the Stop where this session first has MIN_WORK tool calls over
    MIN_HOURS and no note. At every later Stop that already held at the previous one (else at
    the turn's prompt), so it is said once, with nothing stored."""
    offset, start, after = turn
    first, calls_before = before(transcript, offset)
    then = stamp(start)
    first = first or then  # a first turn: nothing before its prompt
    now = max(filter(None, map(stamp, after)), default=then)
    if not (first and then and now):
        return None

    def busy(calls, ts):
        return calls >= MIN_WORK and ts - first >= MIN_HOURS * 3600

    calls = calls_before + sum(len(tool_uses(e)) for e in after)
    if not busy(calls, now) or busy(calls_before, then):
        return None
    # not another session's snapshot it only bannered, as a /session-handoffs run does
    wrote = any(
        how == WROTE and (own_note(p, sid) or note_title(p) is not None)
        for p, (how, _) in lineage(transcript, sid).items()
    )
    # a /session-handoffs run is never listed as lacking a note either
    if wrote or snapshots(sid, config) or opened_for_report(transcript):
        return None
    return (
        f"session-handoffs: this session has made {MIN_WORK}+ tool calls over "
        f"{(now - first) / 3600:.0f} h and has no handoff note. Ask it for one, or snapshot it "
        f"later from another session with /session-handoffs --from-transcript {sid[:8]}"
    )


def on_stop(t, sid, config, turn, guard_on, nudge_on):
    new_notes = [p for p in map(created, turn[2]) if p and own_note(p, sid)]
    if not new_notes:
        s = nudge_on and nudge(t, sid, config, turn)
        return {"systemMessage": s} if s else None
    if not guard_on:
        return None
    rows = current(sid, lineage(t, sid), config, skip=set(new_notes))
    named = set().union(*(replaced(n, rows, sid) for n in new_notes)) - set(new_notes)
    left = [(p, how) for p, how in rows if p in named and CHANGED not in how]
    known = {p for p, _ in rows}
    left += [
        (p, "named on a Supersedes or Replaces line") for p in sorted(named - known)
    ]
    head = (
        f"session-handoffs: this turn created {', '.join(map(tilde, new_notes))}. These notes "
        "are named on a Supersedes or Replaces line of it and still open without a "
        "SUPERSEDED banner:"
    )
    return context("Stop", listing(head, left, t, config))


def interactive(config, sid):
    """True if <config>/sessions/ lists this session as a running working session, interactive
    or `claude --bg` (the report's rule)."""
    for f in (config / "sessions").glob("*.json"):
        try:
            s = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(s, dict) and s.get("sessionId") == sid:
            return s.get("kind", "interactive") in LIVE_KINDS
    return False


def guard(h, env):
    """The hook's JSON output for input `h`, or None to stay silent."""
    event, sid = h.get("hook_event_name"), str(h.get("session_id") or "")
    guard_on = env.get("SESSION_HANDOFFS_GUARD") == "1"
    nudge_on = env.get("SESSION_HANDOFFS_NUDGE") == "1"
    # a subagent's notes are its parent's business; plan and dontAsk can't write one
    if h.get("agent_id") or h.get("permission_mode") in ("plan", "dontAsk"):
        return None
    if not sid or not h.get("transcript_path"):
        return None
    t = Path(str(h["transcript_path"])).expanduser()
    # <config>/projects/<project>/<session>.jsonl: works when $CLAUDE_CONFIG_DIR is scrubbed
    config = t.parents[2]
    # the cheap checks first; the transcript is read only past them
    if event == "UserPromptSubmit":
        prompt = str(h.get("prompt") or "")
        asked = ASK.search(NOT_ASKED.sub(" ", prompt))
        if not guard_on or prompt.lstrip().startswith("/") or not asked:
            return None
    elif event == "PostToolUse":
        # a rewrite, not a note, or /session-handoffs writing another session's snapshot
        new = str((h.get("tool_input") or {}).get("file_path") or "")
        made = (h.get("tool_response") or {}).get("type") == "create"
        if not guard_on or not made or not own_note(new, sid):
            return None
    elif event != "Stop" or h.get("stop_hook_active") or not (guard_on or nudge_on):
        return None
    turn = last_turn(t)
    entries = [turn[1], *turn[2]] if turn else []
    entrypoint = str(
        next((e["entrypoint"] for e in entries[::-1] if e.get("entrypoint")), "")
    )
    # claude -p and the Agent SDK: automation, nobody to read it, unless the registry lists it as
    # interactive, as the report does. Unknown (a session's first prompt, before any turn is
    # saved) counts as automation too: -p has only that one
    if not entrypoint or (
        entrypoint.startswith("sdk") and not interactive(config, sid)
    ):
        return None

    if event == "UserPromptSubmit":
        mine = lineage(t, sid)
        for p in notes_in(prompt):  # this prompt isn't in the transcript yet
            if own_note(p, sid):
                mine.setdefault(p, (GIVEN, None))
        head = (
            "session-handoffs: this session's handoff notes that are still current "
            "(no SUPERSEDED banner):"
        )
        return context(event, listing(head, current(sid, mine, config), t, config))
    if event == "PostToolUse":
        rows = current(sid, lineage(t, sid), config, skip={new})
        head = (
            f"session-handoffs: {tilde(new)} is a new handoff note. This session's other "
            "notes that are still current:"
        )
        return context(event, listing(head, rows, t, config))
    return on_stop(t, sid, config, turn, guard_on, nudge_on) if turn else None


def main():
    # silence on any error, and never exit 2: SystemExit(2) would erase the user's prompt
    try:
        out = guard(json.load(sys.stdin), os.environ)
        if out:
            print(json.dumps(out), flush=True)
    except BaseException:
        pass


if __name__ == "__main__":
    main()
