"""Tests for handoff_status.py. Run: python3 -m unittest discover -s skills/session-handoffs/scripts"""

import contextlib
import io
import json
import os
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

    def note(self, rel, body="# note"):
        path = self.dir / "notes" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        return str(path)

    def session(self, pid, name, session_id, updated=1):
        entry = {
            "name": name,
            "sessionId": session_id,
            "kind": "interactive",
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
        header, *rows = [line.split("\t") for line in self.run_cli().splitlines()]
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
        ]
        not_listed = [
            self.note("memory/project-handoff.md"),  # memory pointer
            self.note("handoff_2026-09-25_old.md"),  # older note, edited that day
            self.note("handoff_s2_purge_20260903.md"),  # older, compact date
            self.note(
                "handoff_aria-due-2026-10-09.md"
            ),  # a deadline, not the day it's for
            self.note("handoff_status.py"),  # not a note
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
                ]
            ),
        )

    def test_a_snapshot_counts_for_the_session_it_describes(self):
        snapshot = self.note(f"handoff_{DAY}_snapshot-bbbbbbbb.md", "# Snapshot")
        self.session(1, "writer", sid("a"))
        self.transcript(sid("a"), *work(3, 9), call("Write", snapshot, 10))
        self.transcript(sid("b"), *work(40, 9))  # closed, no note of its own
        rows = [(r["session"], r["verdict"], r["path"]) for r in self.report()]
        self.assertEqual(rows, [("bbbbbbbb", "closed", snapshot)])

    def test_a_snapshot_written_by_this_session_counts_for_its_source(self):
        snapshot = self.note(f"handoff_{DAY}_snapshot-bbbbbbbb.md", "# Snapshot")
        self.transcript(
            sid("d"), call("Write", snapshot, 10)
        )  # "me", running the report
        self.transcript(sid("b"), *work(40, 9))
        rows = [(r["session"], r["verdict"], r["path"]) for r in self.report()]
        self.assertEqual(rows, [("bbbbbbbb", "closed", snapshot)])

    def test_two_running_sessions_with_the_same_name(self):
        self.session(1, "s", sid("a"))
        self.session(2, "s", sid("b"))
        self.transcript(sid("a"), call("Write", self.note(f"handoff_{DAY}_a.md")))
        self.transcript(sid("b"), call("Write", self.note(f"handoff_{DAY}_b.md")))
        self.assertEqual(self.verdicts(), [("s", "fresh"), ("s", "fresh")])

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
        ):
            self.assertNotIn(text, out)

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
