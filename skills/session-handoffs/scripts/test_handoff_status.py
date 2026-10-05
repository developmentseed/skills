"""Tests for handoff_status.py. Run: python3 -m unittest discover -s skills/session-handoffs/scripts"""

import contextlib
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import handoff_status

DAY = "2026-09-28"


def sid(c):
    return f"{c * 8}-{c * 4}-{c * 4}-{c * 4}-{c * 12}"


def call(name, path="", hour=12, day=DAY, **inputs):
    block = {"type": "tool_use", "name": name, "input": {"file_path": path, **inputs}}
    return {
        "type": "assistant",
        "timestamp": f"{day}T{hour:02d}:00:00.000Z",
        "message": {"content": [block]},
    }


def work(n, hour=12, day=DAY, tool="Bash", path=""):
    return [call(tool, path, hour=hour, day=day)] * n


def say(role, text, hour, **extra):
    content = text if role == "user" else [{"type": "text", "text": text}]
    return {
        "type": role,
        "timestamp": f"{DAY}T{hour:02d}:30:00.000Z",
        "message": {"content": content},
        **extra,
    }


def tool_output(text, hour):
    content = [{"type": "tool_result", "tool_use_id": "x", "content": text}]
    return {
        "type": "user",
        "timestamp": f"{DAY}T{hour:02d}:31:00.000Z",
        "message": {"content": content},
    }


class HandoffStatusTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "sessions").mkdir()
        (self.dir / "sessions" / "9.abc.key").write_text("not json, never read")
        # fixtures use UTC timestamps (the script compares local dates), live in a temp dir, are
        # compared as full paths (no ~ shortening), and "me" is the session running the report
        self.addCleanup(time.tzset)
        for patcher in (
            mock.patch.dict(os.environ, TZ="UTC", CLAUDE_CODE_SESSION_ID=sid("d")),
            mock.patch.object(handoff_status, "TEMP_ROOTS", ()),
            mock.patch("pathlib.Path.home", return_value=Path("/nonexistent-home")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        time.tzset()
        # `claude agents --json`: not installed, so the registry is read, unless a test sets it
        patcher = mock.patch.object(
            handoff_status.subprocess, "run", side_effect=FileNotFoundError
        )
        self.cli = patcher.start()
        self.addCleanup(patcher.stop)

    def agents(self, *entries):
        self.cli.side_effect = None
        self.cli.return_value = subprocess.CompletedProcess([], 0, json.dumps(entries))

    def note(self, rel, body="# note"):
        path = self.dir / "notes" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        return str(path)

    def session(self, pid, name, session_id, updated=1, kind="interactive"):
        entry = {
            "name": name,
            "sessionId": session_id,
            "kind": kind,
            "updatedAt": updated,
        }
        (self.dir / "sessions" / f"{pid}.json").write_text(
            json.dumps({k: v for k, v in entry.items() if v})
        )

    def transcript(self, session_id, *entries, sub=None, project="-proj"):
        path = self.dir / "projects" / project / f"{session_id}.jsonl"
        if sub:
            path = (
                self.dir
                / "projects"
                / project
                / session_id
                / "subagents"
                / f"{sub}.jsonl"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [json.dumps(e) for e in entries] + ["{not json", '{"type": "user"}']
            )
        )

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            handoff_status.main(["--claude-dir", str(self.dir), "--date", DAY, *args])
        return out.getvalue()

    def report(self):
        # run from a session, as in use: its call to the script is in its transcript
        me = os.environ.get("CLAUDE_CODE_SESSION_ID")
        if me and not any(self.dir.glob(f"projects/*/{me}.jsonl")):
            self.transcript(me, call("Bash"))
        _, header, *rows = [line.split("\t") for line in self.run_cli().splitlines()]
        return [dict(zip(header, r)) for r in rows]

    def verdicts(self):
        return sorted((r["session"], r["verdict"]) for r in self.report())

    def test_verdicts(self):
        note = self.note(f"handoff_{DAY}_a.md")
        self.session(1, "fresh-one", sid("a"))
        self.transcript(sid("a"), call("Write", note, 10), *work(30, 11))
        self.session(2, "stale-one", sid("b"))
        self.transcript(sid("b"), call("Write", note, 10), *work(31, 11))
        self.session(3, "quiet-one", sid("c"))
        self.transcript(sid("c"), *work(30))
        self.session(7, "denied-one", sid("8"))  # its only note write never landed
        self.transcript(
            sid("8"),
            call("Write", str(self.dir / f"handoff_{DAY}_denied.md"), 9),
            *work(30),
        )
        self.session(4, "short-one", sid("5"))
        self.transcript(sid("5"), *work(3))  # a quick question: not reported
        self.session(5, "me", sid("d"))
        self.transcript(sid("d"), call("Write", note))  # the session running the report
        self.session(6, None, sid("7"))  # running, but the registry has no name for it
        self.transcript(sid("7"), call("Write", note))
        self.transcript(sid("e"), call("Edit", note))  # closed, left a note
        self.transcript(
            sid("f"), call("Write", note, 10), *work(31, 11)
        )  # closed, worked on after it
        self.transcript(sid("1"), *work(40))  # closed, worked, no note
        self.transcript(
            sid("2"), *work(40, day="2026-09-27")
        )  # closed, nothing in the window
        self.transcript(
            "hp_residual_20260925", call("Write", note)
        )  # a data file, not a transcript
        self.assertEqual(
            self.verdicts(),
            [
                ("11111111", "closed-none"),
                ("77777777", "fresh"),
                ("denied-one", "none"),
                ("eeeeeeee", "closed"),
                ("ffffffff", "closed-stale"),
                ("fresh-one", "fresh"),
                ("quiet-one", "none"),
                ("stale-one", "stale"),
            ],
        )

    def test_background_sessions_count_as_running(self):
        # `claude --bg` sessions are registered with kind "bg": running, and reachable by --ask
        note = self.note(f"handoff_{DAY}_a.md")
        self.session(1, "bg-note", sid("a"), kind="bg")
        self.transcript(sid("a"), call("Write", note, 10))
        self.session(2, "bg-busy", sid("b"), kind="bg")
        self.transcript(sid("b"), *work(30))
        self.session(3, "other", sid("c"), kind="other")  # not a working session
        self.transcript(sid("c"), *work(30))
        self.assertEqual(
            self.verdicts(),
            [("bg-busy", "none"), ("bg-note", "fresh"), ("cccccccc", "closed-none")],
        )

    def test_a_session_either_list_has_is_running(self):
        self.session(1, "in-registry", sid("b"))
        for s in "ab":
            self.transcript(sid(s), *work(30))
        me = {"sessionId": sid("d"), "name": "me", "kind": "interactive"}
        bg = {"sessionId": sid("a"), "name": "bg-busy", "kind": "background"}
        both = [("bg-busy", "none"), ("in-registry", "none")]
        # inside Claude Code's Bash sandbox the CLI lists only some sessions, maybe this one
        for partial in ((me, bg), (bg,)):
            self.agents(*partial)
            self.assertEqual(self.verdicts(), both)
        registry = [("aaaaaaaa", "closed-none"), ("in-registry", "none")]
        for broken in ("", "{}", "[1]", "null"):
            self.cli.return_value.stdout = broken
            self.assertEqual(self.verdicts(), registry, broken)
        self.cli.side_effect = subprocess.TimeoutExpired("claude", 10)
        self.assertEqual(self.verdicts(), registry)
        # a registry that changed still stops the report, whatever the CLI lists
        self.agents(me, bg)
        (self.dir / "sessions" / "1.json").write_text(json.dumps({"id": sid("b")}))
        with self.assertRaisesRegex(SystemExit, "no sessionId in"):
            self.run_cli()

    def test_staleness_counts_main_calls_and_subagent_edits(self):
        note = self.note(f"handoff_{DAY}.md")
        self.session(1, "reader", sid("a"))  # its subagents only read after the note
        self.transcript(sid("a"), call("Write", note, 10), call("Agent", hour=11))
        self.transcript(
            sid("a"),
            *work(40, 11, tool="Read", path="/x/code.py"),
            sub="agent-1",
            project="-other",
        )
        self.session(
            2, "builder", sid("b")
        )  # its subagents edit files, here in another project dir
        self.transcript(sid("b"), call("Write", note, 10), call("Agent", hour=11))
        self.transcript(
            sid("b"),
            *work(31, 11, tool="Edit", path="/wt/new.py"),
            sub="agent-1",
            project="-other",
        )
        self.session(3, "scratch", sid("c"))  # its subagents only edit temp files
        self.transcript(sid("c"), call("Write", note, 10))
        self.transcript(
            sid("c"), *work(40, 11, tool="Write", path="/tmp-x/a.py"), sub="agent-1"
        )
        with mock.patch.object(handoff_status, "TEMP_ROOTS", ("/tmp-x/",)):
            got = self.verdicts()
        self.assertEqual(
            got, [("builder", "stale"), ("reader", "fresh"), ("scratch", "fresh")]
        )

    def test_listing_rules(self):
        self.session(1, "s", sid("a"))
        self.note(
            "wt/.git", "gitdir: /repo/.git/worktrees/wt"
        )  # a `git worktree add` checkout
        listed = [
            self.note("HANDOFF-cache.md"),  # undated
            self.note(f"handoff_{DAY}_b.md"),
            self.note(
                "handoff_2026-09-30_wednesday.md"
            ),  # written ahead for a later day
            self.note(f"handoffs/{DAY}-actions.md"),  # in a handoffs/ directory
            self.note("handoff_job-120260925.md"),  # build numbers, not dates
            self.note("handoff_202609251.md"),
            # "body" rules out a file in handoffs/ only
            self.note(f"handoff_{DAY}_body_parser.md"),
        ]
        not_listed = [
            self.note("memory/project-handoff.md"),  # memory pointer
            self.note("handoff_2026-09-25_old.md"),  # older note, edited that day
            self.note("handoff_s2_purge_20260903.md"),  # older, compact date
            self.note(
                "handoff_aria-due-2026-10-09.md"
            ),  # a deadline, not the day it's for
            self.note("handoff_status.py"),  # not a note
            self.note("session-handoffs/SKILL.md"),  # a directory named for handoffs
            self.note("handoffs/run.py"),  # not a note
            self.note("handoffs/README.md"),  # the folder's index, not a note
            self.note(f"handoffs/{DAY}-pr-12-body.md"),  # a PR body, not a note
            self.note("handoff_202609201030.md"),  # older, with a time
            str(self.dir / f"handoff_{DAY}_denied.md"),  # write never landed
            self.note(f"wt/handoff_{DAY}.md"),  # deleted with the worktree
        ]
        self.transcript(sid("a"), *[call("Write", p, 9) for p in not_listed + listed])
        self.assertEqual({r["path"] for r in self.report()}, set(listed))

    def test_an_older_dated_note_counts_and_is_listed_when_it_is_the_only_one(self):
        self.session(1, "s", sid("a"))
        old = self.note("openeo-handoff-2026-09-25.md", "# openEO")
        self.transcript(sid("a"), *work(40, 9), call("Edit", old, 10), *work(5, 11))
        self.assertEqual(
            [(r["verdict"], r["path"]) for r in self.report()], [("fresh", old)]
        )

    def test_the_window_runs_past_midnight(self):
        self.session(1, "s", sid("a"))
        note = self.note(f"handoff_{DAY}_late.md")
        self.transcript(
            sid("a"), call("Write", note, 22), *work(31, 0, day="2026-09-29")
        )
        self.assertEqual(
            [(r["verdict"], r["calls_after"]) for r in self.report()], [("stale", "31")]
        )
        # the day covered, for the daily note and --digest: after midnight, not today
        self.assertTrue(self.run_cli().startswith(f"date: {DAY}, now: "))

    def test_default_day_is_five_hours_ago(self):
        self.assertEqual(
            handoff_status.default_day(datetime(2026, 9, 29, 1, 30)), date(2026, 9, 28)
        )
        self.assertEqual(
            handoff_status.default_day(datetime(2026, 9, 29, 9, 0)), date(2026, 9, 29)
        )

    def test_superseded_banners_and_titles(self):
        self.session(1, "s", sid("a"))
        bodies = {
            "new": "# Handoff: part 3\n\nSupersedes the old one.",
            "banner": "# Handoff: old\n\n> ⏭️ **SUPERSEDED by part3**\n",
            "quoted": "# Upstream\n\n> **2026-09-28: superseded. START AT part3**\n",
            "front": "---\ntitle: x\ntags: [a]\n---\n\n## Front\n\n> SUPERSEDED as entry point\n",
            "unclosed": "---\nsuperseded: false\n" + "k: v\n" * 50,
            "prose": "\ufeff# Prose\n\nThe plan's scope table is superseded by §2.\n",
            "partly": "PARTLY SUPERSEDED: see §3\n\nbody",
            "inpart": "# Kept\n\n> superseded in part by §4\n",
            "arrow": "# Arrow\n\n> **SUPERSEDED 2026-09-24 → `x.md`.**\n",
            "quoted_prose": "# Plan\n\n> Note: approach A was superseded by B last week.\n",
            "section": "# Section\n\n## Superseded options\n",
            "companion": "> COMPANION of `handoff_new.md`\n\n# Kept beside it\n",
            "companions": "# Live\n\n**Companion notes:** `a.md`, `b.md`\n",
            "companion_to": "Companion to `a.md` (same directory)\n\n# Beside\n",
            # only a quoted line that opens with "companion of" is a banner
            "quoted_list": "> **Companion notes:** `a.md`, `b.md`\n\n# Quoted list\n",
            "unquoted_of": "Companion of `a.md`: the budget half\n\n# Unquoted\n",
            "mid_line": "> See the companion of `a.md` for costs\n\n# Mid-line\n",
            "no_h1": "## Status check\n\nbody",
        }
        paths = {
            k: self.note(f"handoff_{DAY}_{k}.md", body) for k, body in bodies.items()
        }
        self.transcript(sid("a"), *[call("Edit", p, 10) for p in paths.values()])
        self.assertEqual(
            sorted((r["path"], r["title"]) for r in self.report()),
            sorted(
                [
                    (paths["new"], "Handoff: part 3"),
                    (paths["unclosed"], f"handoff_{DAY}_unclosed"),
                    (paths["prose"], "Prose"),
                    (paths["partly"], f"handoff_{DAY}_partly"),
                    (paths["inpart"], "Kept"),
                    (paths["quoted_prose"], "Plan"),
                    (paths["section"], "Section"),
                    (paths["companions"], "Live"),
                    (paths["companion_to"], "Beside"),
                    (paths["quoted_list"], "Quoted list"),
                    (paths["unquoted_of"], "Unquoted"),
                    (paths["mid_line"], "Mid-line"),
                    (paths["no_h1"], f"handoff_{DAY}_no_h1"),
                ]
            ),
        )

    def test_a_snapshot_counts_for_the_session_it_describes(self):
        snapshot = self.note(f"handoff_{DAY}_snapshot-bbbbbbbb.md", "# Snapshot")
        run = 'python3 "/x/scripts/handoff_status.py"'
        self.transcript(  # an earlier run of the report wrote it
            sid("a"), call("Bash", hour=9, command=run), call("Write", snapshot, 10)
        )
        self.transcript(sid("b"), *work(40, 9))  # closed, no note of its own
        rows = [(r["session"], r["verdict"], r["path"]) for r in self.report()]
        self.assertEqual(rows, [("bbbbbbbb", "closed", snapshot)])

    def test_a_snapshot_another_session_edits_is_its_own_note(self):
        snap = self.note(f"handoff_{DAY}_snapshot-bbbbbbbb.md", "# Snapshot")
        self.transcript(sid("d"), call("Write", snap, 10))  # "me"
        self.session(1, "b", sid("b"))  # resumed from it, then worked on
        self.transcript(sid("b"), *work(40, 9), call("Edit", snap, 11), *work(6, 13))
        self.session(2, "c", sid("c"))  # then took it over
        self.transcript(sid("c"), *work(40, 9), call("Edit", snap, 12))
        # c's edit is c's note, not a snapshot write that puts b on the 5-call rule
        self.assertEqual(self.verdicts(), [("b", "fresh"), ("c", "fresh")])
        # step 5 doesn't write over it: whoever wrote it last may work from it
        run = ("--digest", "b", "--notes-dir", str(self.dir / "notes"))
        with self.assertRaisesRegex(SystemExit, "session c wrote it last"):
            self.run_cli(*run)
        self.transcript(sid("c"), *work(40, 9))
        with self.assertRaisesRegex(SystemExit, "session b wrote it last"):
            self.run_cli(*run)
        # a run of the report wrote it last: a new snapshot replaces it
        self.transcript(sid("d"), call("Write", snap, 10), call("Write", snap, 14))
        self.assertIn(f"snapshot: {snap}\n", self.run_cli(*run))

    def test_a_snapshot_written_by_this_session_counts_for_its_source(self):
        b, c = (self.note(f"handoff_{DAY}_snapshot-{x * 8}.md") for x in "bc")
        # "me", running the report, wrote one; its subagent wrote the other (step 5)
        self.transcript(sid("d"), call("Write", b, 10))
        self.transcript(sid("d"), call("Write", c, 10), sub="agent-1")
        self.transcript(sid("b"), *work(40, 9))
        self.transcript(sid("c"), *work(40, 9))
        rows = [(r["session"], r["verdict"], r["path"]) for r in self.report()]
        self.assertEqual(rows, [("bbbbbbbb", "closed", b), ("cccccccc", "closed", c)])

    def test_a_snapshot_a_subagent_writes_counts_for_its_source(self):
        # a run from a working session: its step-5 subagent writes a snapshot, which counts for
        # the session it describes. What its own conversation writes, even after running the
        # check, is a note it works from
        run = 'python3 "/x/scripts/handoff_status.py"'
        b, c, e = (self.note(f"handoff_{DAY}_snapshot-{x * 8}.md") for x in "bce")
        self.session(1, "w", sid("a"))
        self.transcript(
            sid("a"),
            call("Edit", e, 8),
            *work(40, 9),
            call("Bash", hour=12, command=run),
            call("Write", c, 13),
        )
        self.transcript(
            sid("a"),
            call("Bash", hour=12, command=f"{run} --digest b"),
            call("Write", b, 12),
            sub="agent-1",
        )
        for x in "bce":
            self.transcript(sid(x), *work(40, 9))
        self.assertEqual(
            sorted((r["session"], r["verdict"], r["path"]) for r in self.report()),
            [
                ("bbbbbbbb", "closed", b),
                ("cccccccc", "closed-none", "-"),
                ("eeeeeeee", "closed-none", "-"),
                ("w", "fresh", c),
                ("w", "fresh", e),
            ],
        )
        # so step 5 may write over the subagent's, not over one w works from
        notes = ("--notes-dir", str(self.dir / "notes"))
        self.assertIn(f"snapshot: {b}\n", self.run_cli("--digest", "bbbbbbbb", *notes))
        with self.assertRaisesRegex(SystemExit, "session w wrote it last"):
            self.run_cli("--digest", "cccccccc", *notes)

    def test_step_5_may_write_over_a_snapshot_marked_superseded(self):
        snap = self.note(
            f"handoff_{DAY}_snapshot-bbbbbbbb.md", "> SUPERSEDED by x.md\n# Snap"
        )
        run = ("--digest", "bbbbbbbb", "--notes-dir", str(self.dir / "notes"))
        # nobody works from it, whether the session it describes marked it or another did
        self.transcript(sid("b"), *work(40, 9), call("Edit", snap, 11))
        self.assertIn(f"snapshot: {snap}\n", self.run_cli(*run))
        own = self.note(f"handoff_{DAY}_c.md", "# C")
        self.transcript(
            sid("c"), *work(40, 9), call("Edit", snap, 12), call("Write", own, 12)
        )
        self.assertIn(f"snapshot: {snap}\n", self.run_cli(*run))
        # a note kept on purpose beside another is still someone's
        Path(snap).write_text("> COMPANION of x.md\n> SUPERSEDED by x.md\n# Snap")
        with self.assertRaisesRegex(SystemExit, "session cccccccc wrote it last"):
            self.run_cli(*run)
        # once a run writes over it, the edits before are gone from it: it is b's again
        Path(snap).write_text("# Snap")
        self.transcript(sid("d"), call("Write", snap, 14))  # "me"
        self.assertEqual(
            sorted((r["session"], r["path"]) for r in self.report()),
            [("bbbbbbbb", snap), ("cccccccc", own)],
        )

    def test_a_run_of_the_report_is_never_listed_as_lacking_a_note(self):
        run = 'python3 "/x/scripts/handoff_status.py"'
        snapshot = self.note(f"handoff_{DAY}_snapshot-bbbbbbbb.md", "# Snapshot")
        self.transcript(  # opened with /session-handoffs, snapshotted b
            sid("c"),
            call("Bash", hour=9, command=run),
            *work(40, 9),
            call("Write", snapshot, 10),
        )
        self.transcript(  # asked in words, so the skill was loaded by a tool call
            sid("e"), call("Skill", hour=9, skill="session-handoffs"), *work(40, 9)
        )
        self.transcript(sid("b"), *work(40, 9))  # closed, described by the snapshot
        self.transcript(  # opened for the report, then put to work and snapshotted
            sid("f"), call("Skill", hour=9, skill="session-handoffs"), *work(60, 10)
        )
        self.transcript(
            sid("d"),  # "me"
            call("Write", self.note(f"handoff_{DAY}_snapshot-ffffffff.md"), 12),
        )
        self.transcript(  # a working session that ran the report late in the day
            sid("a"),
            call("Bash", hour=9, command="python3 scripts/test_handoff_status.py"),
            *work(40, 9),
            call("Bash", hour=18, command=run),
        )
        self.transcript(  # its first call only names the script
            sid("1"),
            call("Bash", hour=9, command="git diff -- scripts/handoff_status.py"),
            *work(40, 9),
        )
        self.transcript(  # worked the day before; its first call today ran the report
            sid("2"),
            *work(3, 9, day="2026-09-27"),
            call("Bash", hour=8, command=run),
            *work(40, 9),
        )
        self.assertEqual(
            self.verdicts(),
            [
                ("11111111", "closed-none"),
                ("22222222", "closed-none"),
                ("aaaaaaaa", "closed-none"),
                ("bbbbbbbb", "closed"),
                ("ffffffff", "closed"),
            ],
        )

    def test_a_snapshot_goes_out_of_date_sooner_than_a_note(self):
        snapshots = [self.note(f"handoff_{DAY}_snapshot-{c * 8}.md") for c in "abc"]
        self.transcript(sid("d"), *[call("Write", s, 10) for s in snapshots])  # by "me"
        for pid, c, calls in ((1, "a", 5), (2, "b", 6)):
            self.session(pid, f"src-{c}", sid(c))
            self.transcript(sid(c), *work(40, 9), *work(calls, 11))
        # a session that then edited the snapshot of itself is judged as by its own note
        self.session(3, "src-c", sid("c"))
        self.transcript(
            sid("c"), *work(40, 9), call("Edit", snapshots[2], 11), *work(6, 12)
        )
        self.assertEqual(
            self.verdicts(),
            [("src-a", "fresh"), ("src-b", "stale"), ("src-c", "fresh")],
        )

    def test_an_own_note_replaces_the_snapshot_it_covers(self):
        snap = {
            c: self.note(f"handoff_{DAY}_snapshot-{c * 8}.md", "# Snap")
            for c in "abcef1234"
        }
        # written by "me", the session running the report
        self.transcript(sid("d"), *[call("Write", s, 10) for s in snap.values()])
        own = {c: self.note(f"handoffs/{DAY}-{c}.md", "# Own") for c in "abcef4"}
        self.session(1, "after", sid("a"))  # wrote its own note after the snapshot
        self.transcript(sid("a"), *work(40, 8), call("Write", own["a"], 11))
        self.session(2, "before", sid("b"))  # its own note, 5 calls, then the snapshot
        self.transcript(sid("b"), *work(40, 7), call("Write", own["b"], 8), *work(5, 9))
        self.session(3, "busy", sid("c"))  # 6 calls: the snapshot holds news
        self.transcript(sid("c"), *work(40, 7), call("Write", own["c"], 8), *work(6, 9))
        self.session(4, "marked", sid("e"))  # then marked the snapshot superseded
        self.note(f"handoff_{DAY}_snapshot-{'e' * 8}.md", "> SUPERSEDED by own\n# Snap")
        self.transcript(
            sid("e"),
            *work(40, 8),
            call("Write", own["e"], 11),
            call("Edit", snap["e"], 11),
        )
        self.session(5, "deleted", sid("f"))  # its snapshot is gone: nothing to replace
        os.remove(snap["f"])
        self.transcript(sid("f"), *work(40, 8), call("Write", own["f"], 11))
        self.session(6, "two", sid("1"))  # the newer of its own notes replaces it
        old, new = (
            self.note(f"handoffs/{DAY}-two-{x}.md", "# Own") for x in ("a", "b")
        )
        self.transcript(
            sid("1"), call("Write", old, 7), *work(40, 8), call("Write", new, 11)
        )
        self.session(7, "denied", sid("2"))  # its own note never landed
        self.transcript(
            sid("2"),
            *work(40, 8),
            call("Write", str(self.dir / f"handoff_{DAY}_x.md"), 11),
        )
        self.session(8, "older", sid("3"))  # then edited a note named for another day
        topic = self.note(f"handoff_{DAY}_topic.md", "# Own")
        other = self.note("handoff_2026-09-20_other.md", "# Other")
        self.transcript(
            sid("3"), call("Write", topic, 9), *work(20, 10), call("Edit", other, 13)
        )
        self.session(9, "late", sid("4"))  # marked it superseded 9 calls after its note
        self.note(f"handoff_{DAY}_snapshot-{'4' * 8}.md", "> SUPERSEDED by own\n# Snap")
        self.transcript(
            sid("4"),
            *work(40, 8),
            call("Write", own["4"], 11),
            *work(8, 12),
            call("Edit", snap["4"], 13),
        )
        report = self.report()
        # a snapshot's row comes first, so its line is swapped before the own note is added
        self.assertEqual(
            [r["verdict"] for r in report if r["session"] == "after"],
            ["replaced", "fresh"],
        )
        self.assertEqual(
            sorted((r["session"], r["verdict"], r["path"], r["title"]) for r in report),
            sorted(
                [
                    ("after", "fresh", own["a"], "Own"),
                    ("after", "replaced", snap["a"], own["a"]),
                    ("before", "fresh", own["b"], "Own"),
                    ("before", "replaced", snap["b"], own["b"]),
                    ("busy", "fresh", own["c"], "Own"),
                    ("busy", "fresh", snap["c"], "Snap"),
                    ("marked", "fresh", own["e"], "Own"),
                    ("marked", "replaced", snap["e"], own["e"]),
                    ("deleted", "fresh", own["f"], "Own"),
                    ("two", "fresh", old, "Own"),
                    ("two", "fresh", new, "Own"),
                    ("two", "replaced", snap["1"], new),
                    ("denied", "fresh", snap["2"], "Snap"),
                    ("older", "fresh", topic, "Own"),
                    ("older", "fresh", snap["3"], "Snap"),
                    ("late", "fresh", own["4"], "Own"),
                    ("late", "replaced", snap["4"], own["4"]),
                ]
            ),
        )

    def test_a_snapshot_someone_works_from_is_not_replaced(self):
        snap = {c: self.note(f"handoff_{DAY}_snapshot-{c * 8}.md") for c in "abf"}
        self.transcript(sid("d"), *[call("Write", s, 10) for s in snap.values()])
        other = {c: self.note(f"handoff_{DAY}_other-{c}.md") for c in "abf"}
        # continued from its snapshot, then did other work
        self.session(1, "resumed", sid("a"))
        self.transcript(
            sid("a"),
            *work(40, 8),
            call("Edit", snap["a"], 11),
            *work(20, 12),
            call("Write", other["a"], 13),
        )
        self.session(2, "shared", sid("b"))  # another session resumed from its snapshot
        self.transcript(sid("b"), *work(40, 8), call("Write", other["b"], 13))
        self.transcript(sid("c"), call("Edit", snap["b"], 12))
        # opened to run the report, then put to work: its edit is still its own
        self.session(3, "opened", sid("f"))
        self.transcript(
            sid("f"),
            call("Skill", hour=7, skill="session-handoffs"),
            *work(40, 8),
            call("Edit", snap["f"], 11),
            *work(20, 12),
            call("Write", other["f"], 13),
        )
        self.assertEqual(
            sorted((r["session"], r["verdict"], r["path"]) for r in self.report()),
            [
                ("cccccccc", "closed", snap["b"]),
                ("opened", "fresh", other["f"]),
                ("opened", "fresh", snap["f"]),
                ("resumed", "fresh", other["a"]),
                ("resumed", "fresh", snap["a"]),
                ("shared", "fresh", other["b"]),
                ("shared", "fresh", snap["b"]),
            ],
        )
        with self.assertRaisesRegex(SystemExit, "session opened wrote it last"):
            self.run_cli("--digest", "opened", "--notes-dir", str(self.dir / "notes"))

    def test_a_snapshot_an_earlier_run_wrote_is_replaced(self):
        snap = self.note(f"handoff_{DAY}_snapshot-{'a' * 8}.md", "# Snap")
        own = self.note(f"handoff_{DAY}_own.md", "# Own")
        run = 'python3 "/x/scripts/handoff_status.py"'
        # an earlier run of the report, not this one, wrote the snapshot
        self.transcript(
            sid("b"), call("Bash", hour=9, command=run), call("Write", snap, 10)
        )
        self.session(1, "s", sid("a"))
        self.transcript(sid("a"), *work(40, 8), call("Write", own, 11))
        self.assertEqual(
            [(r["verdict"], r["path"]) for r in self.report()],
            [("replaced", snap), ("fresh", own)],
        )

    def test_a_snapshot_edited_after_the_run_is_not_replaced(self):
        snap = self.note(f"handoff_{DAY}_snapshot-{'a' * 8}.md", "# Snap")
        own = self.note(f"handoff_{DAY}_own.md", "# Own")
        self.transcript(sid("d"), call("Write", snap, 10))  # "me"
        # another session edited it after this run wrote it: someone works from it
        self.transcript(sid("e"), call("Edit", snap, 12))
        self.session(1, "s", sid("a"))
        self.transcript(sid("a"), *work(40, 8), call("Write", own, 13))
        self.assertEqual(
            sorted((r["verdict"], r["path"]) for r in self.report()),
            [("closed", snap), ("fresh", own), ("fresh", snap)],
        )

    def test_two_running_sessions_with_the_same_name(self):
        self.session(1, "s", sid("a"))
        self.session(2, "s", sid("b"))
        self.transcript(sid("a"), call("Write", self.note(f"handoff_{DAY}_a.md")))
        self.transcript(sid("b"), call("Write", self.note(f"handoff_{DAY}_b.md")))
        self.assertEqual(
            self.verdicts(), [("s (aaaaaaaa)", "fresh"), ("s (bbbbbbbb)", "fresh")]
        )
        with self.assertRaisesRegex(SystemExit, "2 running sessions have this name"):
            self.run_cli("--digest", "s")

    def test_marking_an_old_note_superseded_does_not_refresh_a_session(self):
        today = self.note(f"handoff_{DAY}_x.md", "# Today")
        old = self.note(
            "handoff_2026-09-20_x.md", "# Old\n\n> SUPERSEDED by today's note\n"
        )
        self.session(1, "s", sid("a"))
        self.transcript(
            sid("a"), call("Write", today, 10), *work(40, 11), call("Edit", old, 20)
        )
        self.session(2, "t", sid("b"))  # its only note points elsewhere
        self.transcript(sid("b"), *work(40, 9), call("Edit", old, 10))
        self.assertEqual(self.verdicts(), [("s", "stale"), ("t", "none")])

    def test_automation_and_submodules(self):
        self.note(
            "repo/lib/.git", "gitdir: ../../.git/modules/lib"
        )  # a submodule, not a worktree
        kept = self.note(f"repo/lib/handoff_{DAY}.md")
        self.transcript(sid("a"), call("Write", kept))  # a closed interactive session
        self.transcript(
            sid("b"), *[dict(c, entrypoint="sdk-py") for c in work(40)]
        )  # automation
        self.transcript(  # automation whose first entry doesn't say so
            sid("c"), call("Bash"), *[dict(c, entrypoint="sdk-py") for c in work(40)]
        )
        rows = [(r["session"], r["path"]) for r in self.report()]
        self.assertEqual(rows, [("aaaaaaaa", kept)])

    def test_digest_covers_the_day_without_tool_output_or_secrets(self):
        self.session(1, "busy", sid("a"))
        self.transcript(
            sid("d"), call("Bash"), project="-own"
        )  # the session running the digest
        note = self.note(f"handoff_{DAY}_x.md", "# Handoff: x")
        self.transcript(
            sid("a"),
            say("user", "morning prompt", 8),
            say("user", "Base directory for this skill: /x", 8, isMeta=True),
            call("Write", note, 9),
            say(
                "user",
                '<cross-session-message from-name="other">please deploy</cross-session-message>',
                10,
            ),
            say("assistant", "Fixed it in skills-a5, tests pass.", 10),
            call(
                "Bash",
                hour=11,
                command="pytest -q\nsecond line",
                description="Run the tests",
            ),
            call(
                "Bash",
                hour=11,
                command='curl -H "Authorization: Bearer ghp_abcdefghijklmnopqrstu" https://x',
            ),
            call(
                "Bash",
                hour=11,
                command="aws s3 ls AKIAABCDEFGHIJKLMNOP postgres://me:hunter2@db/x TOKEN=abc",
            ),
            *[
                call("Bash", hour=11, command=secret)
                for secret in (
                    "export AWS_SECRET_ACCESS_KEY=wJalrX",
                    'echo \'{"password": "hunter3"}\'',
                    "mysql --password hunter4",
                    'curl -H "Authorization: Basic dXNlcjpwYXNz" https://x',
                    'curl -H "Authorization: Token tok123abc" https://x',
                    "echo eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.c2lnbmF0dXJl",
                    "cat <<EOF -----BEGIN RSA PRIVATE KEY----- MIIEowIBAAKCAQ",
                    "export GOOGLE=AIzaSyA1234567890abcdefghijklmnopqrstuv",
                    "export S3_KEY=s3secretvalue",
                    'curl "https://a.blob.core.windows.net/c?sv=2020&sig=sasSIGvalue"',
                    "ssh 203.0.113.7 uptime",
                    """echo '{"private_key": "-----BEGIN PRIVATE KEY----- MIIEvQIBADAN"}'""",
                    "cat -----BEGIN RSA PRIVATE KEY----- Proc-Type: 4,ENCRYPTED MIIEpAkey",
                    "gpg --import -----BEGIN PGP PRIVATE KEY BLOCK----- lQOYBFkey",
                    "mysql --password 'hunter5'",
                    'vault login --token "s.abcdefghijkl"',
                    'export DB_PASSWORD="correct horse battery"',
                    'curl -H "Authorization: rawtoken123" https://x',
                    "export GL=glpat-abcdefghij1234 HF=hf_abcdefghijklmn",
                    "export STRIPE=sk_live_abcdefghij12",
                )
            ],
            tool_output("SECRET_TOKEN=abc123", 11),
            # a snapshot it wrote about another session is not its own latest note
            call(
                "Write", self.note(f"handoff_{DAY}_snapshot-ffffffff.md", "# Other"), 12
            ),
        )
        out = self.run_cli("--digest", "busy")
        self.assertIn(f"latest note: {note} (Handoff: x), last written 09:00", out)
        snapshot = (
            self.dir / "projects" / "-own" / f"handoff_{DAY}_snapshot-aaaaaaaa.md"
        )
        self.assertIn(f"snapshot: {snapshot}", out)
        for text in (
            "USER: morning prompt",
            "PEER: <cross-session-message",
            "Fixed it in skills-a5",
            "→ Bash: Run the tests",
            "Bearer ***",
            "postgres://***@db",
            "TOKEN=***",
        ):
            self.assertIn(text, out)
        for text in (
            "Base directory",
            "pytest -q",
            "second line",
            "ghp_abc",
            "AKIAABC",
            "hunter2",
            "wJalrX",
            "hunter3",
            "hunter4",
            "dXNlcjpwYXNz",
            "SECRET_TOKEN",
            "tok123abc",
            "eyJhbGci",
            "MIIEow",
            "AIzaSyA",
            "s3secretvalue",
            "sasSIGvalue",
            "203.0.113.7",
            "MIIEvQ",
            "ENCRYPTED",
            "MIIEpA",
            "lQOYBF",
            "hunter5",
            "s.abcdefghijkl",
            "horse",
            "rawtoken123",
            "glpat-abc",
            "hf_abc",
            "sk_live",
        ):
            self.assertNotIn(text, out)

    def test_masking_a_long_unbroken_blob_is_fast(self):
        start = time.monotonic()
        handoff_status.short("a" * 30_000, 100)
        self.assertLess(time.monotonic() - start, 2)

    def test_digest_refuses_an_id_prefix_shared_by_two_sessions(self):
        self.transcript(sid("a"), *work(3))
        self.transcript("aaaaaaaa-bbbb-bbbb-bbbb-bbbbbbbbbbbb", *work(3))
        with self.assertRaisesRegex(SystemExit, "matches 2 sessions"):
            self.run_cli("--digest", "aaaaaaaa")
        # a longer prefix still finds one
        self.assertIn("latest note: none", self.run_cli("--digest", "aaaaaaaa-aaaa"))

    def test_a_quiet_day_or_a_new_install_is_not_an_error(self):
        (self.dir / "projects").mkdir()  # no transcript yet, run from a terminal
        with mock.patch.dict(os.environ, CLAUDE_CODE_SESSION_ID=""):
            self.assertEqual(self.report(), [])
        self.session(1, "me", sid("d"))  # the registry holds only this session
        self.transcript(sid("d"), call("Bash"))  # the report: the only tool call
        self.transcript(sid("b"), say("user", "hi", 9), say("assistant", "hello", 9))
        self.assertEqual(self.report(), [])
        # run from a subagent: its call counts, though the session's own calls are older
        self.transcript(sid("d"), call("Agent", day="2026-09-27"))
        self.transcript(sid("d"), call("Bash"), sub="agent-1")
        self.assertEqual(self.report(), [])

    def test_no_projects_dir_is_an_error(self):
        with self.assertRaisesRegex(SystemExit, "projects not found"):
            self.run_cli()

    def test_a_registry_without_session_ids_is_an_error(self):
        # the key was renamed, or the file is no longer an object
        (self.dir / "sessions" / "1.json").write_text(json.dumps({"id": sid("a")}))
        (self.dir / "sessions" / "2.json").write_text("[]")
        self.transcript(sid("a"), *work(40))
        with self.assertRaisesRegex(SystemExit, "no sessionId in"):
            self.run_cli()
        # --digest doesn't need it: it finds a session by its id
        self.assertIn("latest note: none", self.run_cli("--digest", "aaaaaaaa"))
        # one that isn't a session, beside ones that are, is skipped
        self.session(0, "s", sid("a"))
        (self.dir / "sessions" / "3.json").write_text(json.dumps({"pid": 3}))
        self.assertEqual(self.verdicts(), [("s", "none")])

    def renamed_timestamps(self):
        # a format change: every line is skipped, this session's own included
        c = {"time" if k == "timestamp" else k: v for k, v in call("Bash").items()}
        self.transcript(sid("d"), c)
        self.transcript(sid("a"), *[c] * 40)

    def test_unreadable_transcripts_are_an_error_not_an_empty_report(self):
        self.renamed_timestamps()
        self.transcript(sid("b"), *work(40))  # started before an update: the old format
        with self.assertRaisesRegex(SystemExit, "no tool call could be read"):
            self.run_cli()

    def test_moved_transcripts_are_an_error_not_an_empty_report(self):
        # a layout change: each transcript one folder down, this session's own included
        for c in "ad":
            self.transcript("main", *work(40), project=f"-proj/{sid(c)}")
        self.transcript(sid("b"), *work(40))  # started before an update: the old layout
        with self.assertRaisesRegex(SystemExit, "this session's transcript isn't in"):
            self.run_cli()

    def test_run_from_a_terminal_a_window_without_a_tool_call_is_an_error(self):
        # without a session of its own to look at, a renamed tool call in lines that still read
        # looks like a day of chats alone: the error names both
        c = call("Bash")
        c["message"]["content"][0]["type"] = "tool_call"
        self.transcript(sid("a"), *[c] * 40)
        self.transcript(sid("b"), say("user", "hi", 9), say("assistant", "hello", 9))
        with mock.patch.dict(os.environ, CLAUDE_CODE_SESSION_ID=""):
            with self.assertRaisesRegex(
                SystemExit, "format may have changed, or no session used a tool"
            ):
                self.run_cli()

    def test_an_empty_digest_is_an_error_not_an_empty_snapshot(self):
        self.renamed_timestamps()
        with self.assertRaisesRegex(SystemExit, "nothing since .* could be read"):
            self.run_cli("--digest", "aaaaaaaa")

    def test_digest_puts_the_snapshot_in_the_notes_dir(self):
        self.transcript(sid("a"), *work(3))
        (self.dir / "vault" / "handoffs").mkdir(parents=True)
        (self.dir / "memory").mkdir()
        run = ("--digest", "aaaaaaaa", "--notes-dir")
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.dir)  # a relative folder would land wherever the script runs
        with mock.patch.dict(os.environ, HOME=str(self.dir)):
            out = self.run_cli(*run, "~/vault/handoffs")
            # never created, and never where the check can't find it
            for bad in ("~/missing", "~/memory", "", "vault/handoffs"):
                with self.assertRaisesRegex(SystemExit, "--notes-dir", msg=bad):
                    self.run_cli(*run, bad)
        snapshot = (
            self.dir / "vault" / "handoffs" / f"handoff_{DAY}_snapshot-aaaaaaaa.md"
        )
        self.assertIn(f"snapshot: {snapshot}\n", out)

    def test_digest_by_sid8_keeps_the_most_recent_part(self):
        self.transcript(
            sid("a"),
            *[say("assistant", f"step {i:03} " + "x" * 80, 12) for i in range(400)],
        )
        out = self.run_cli(
            "--digest", "aaaaaaaa"
        )  # a closed session, by the first 8 characters of its id
        self.assertIn(f"latest note: none since {DAY}", out)
        self.assertIn("earlier lines omitted]", out)
        self.assertIn("step 399", out)
        self.assertNotIn("step 000", out)


if __name__ == "__main__":
    unittest.main()
