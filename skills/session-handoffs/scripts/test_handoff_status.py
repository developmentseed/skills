"""Tests for handoff_status.py. Run: python3 -m unittest discover -s skills/session-handoffs/scripts"""

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
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
        (self.dir / "projects" / "-proj").mkdir(parents=True)
        (self.dir / "sessions" / "9.abc.key").write_text("not json, never read")
        # fixtures use UTC timestamps (the script compares local dates), live in a temp dir, and
        # are compared as full paths (no ~ shortening, even if the temp dir is under $HOME)
        self.addCleanup(time.tzset)
        for patcher in (
            mock.patch.dict(os.environ, TZ="UTC"),
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
        (self.dir / "sessions" / f"{pid}.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "sessionId": session_id,
                    "status": "idle",
                    "updatedAt": updated,
                }
            )
        )

    def transcript(self, session_id, *entries, sub=None):
        path = self.dir / "projects" / "-proj" / f"{session_id}.jsonl"
        if sub:
            path = (
                self.dir
                / "projects"
                / "-proj"
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

    def run_report(self, *args):
        header, *rows = [line.split("\t") for line in self.run_cli(*args).splitlines()]
        return [dict(zip(header, r)) for r in rows]

    def test_verdicts(self):
        note = self.note(f"handoff_{DAY}_a.md")
        self.session(1, "fresh-one", sid("a"))
        self.transcript(
            sid("a"),
            call("Write", note, 10),
            call("Bash", hour=11),
            call("Bash", hour=12),
        )
        self.session(2, "stale-one", sid("b"))
        self.transcript(
            sid("b"), call("Write", note, 10), *[call("Bash", hour=11)] * 11
        )
        self.session(3, "quiet-one", sid("c"))
        self.transcript(sid("c"), call("Bash"))
        self.session(4, "me", sid("d"))
        self.transcript(sid("d"), call("Write", note))
        self.transcript(sid("e"), call("Edit", note))  # closed, left a handoff
        self.transcript(sid("f"), call("Bash"))  # closed, worked, no handoff
        self.transcript(
            sid("1"), call("Bash", day="2026-09-27")
        )  # closed, nothing in the window
        self.transcript(
            "hp_residual_20260925", call("Write", note)
        )  # a data file, not a transcript

        rows = self.run_report(
            "--self",
            "me",
            "--live",
            "fresh-one",
            "stale-one",
            "stale-one",
            "quiet-one",
            "ghost",
            "me",
        )
        self.assertCountEqual(
            [(r["session"], r["verdict"]) for r in rows],
            [
                ("fresh-one", "fresh"),
                ("stale-one", "stale"),
                ("quiet-one", "none"),
                ("ghost", "unknown"),
                ("eeeeeeee", "closed"),
                ("ffffffff", "closed-none"),
            ],
        )
        fresh = next(r for r in rows if r["session"] == "fresh-one")
        self.assertEqual((fresh["calls_after"], fresh["path"]), ("2", note))

    def test_only_usable_notes_from_the_window_count(self):
        self.session(1, "s", sid("a"))
        undated = self.note("HANDOFF-cache.md")
        ahead = self.note(
            "handoff_2026-09-30_wednesday.md"
        )  # written ahead for a later day
        self.note(
            "wt/.git", "gitdir: /repo/.git/worktrees/wt"
        )  # a `git worktree add` checkout
        skipped = [
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
        self.transcript(
            sid("a"),
            *[call("Write", p) for p in skipped],
            call(
                "Write", self.note(f"handoff_{DAY}_b.md"), day="2026-09-27"
            ),  # before the window
            call("Edit", undated),
            call("Write", ahead),
        )
        self.assertEqual(
            {r["path"] for r in self.run_report("--live", "s")}, {undated, ahead}
        )

    def test_the_window_runs_past_midnight(self):
        self.session(1, "s", sid("a"))
        note = self.note(f"handoff_{DAY}_late.md")
        self.transcript(
            sid("a"),
            call("Write", note, 22),
            *[call("Bash", hour=0, day="2026-09-29")] * 11,
        )
        rows = self.run_report("--live", "s")
        self.assertEqual(
            [(r["verdict"], r["calls_after"]) for r in rows], [("stale", "11")]
        )

    def test_superseded_banner_and_titles(self):
        self.session(1, "s", sid("a"))
        new = self.note(
            f"handoff_{DAY}_part3.md", "# Handoff: part 3\n\nSupersedes the old one."
        )
        old = self.note(
            f"handoff_{DAY}_old.md", "# Handoff: old\n\n> ⏭️ **SUPERSEDED by part3**\n"
        )
        front = self.note(
            f"handoff_{DAY}_front.md",
            "---\ntitle: x\ntags: [a]\ncreated: 1\n---\n\n## Front\n\n> SUPERSEDED as entry point\n",
        )
        unclosed = self.note(
            f"handoff_{DAY}_meta.md", "---\nsuperseded: false\n" + "k: v\n" * 50
        )
        prose = self.note(
            f"handoff_{DAY}_prose.md",
            "﻿# Prose\n\nThe plan's scope table is superseded by §2.\n",
        )
        partly = self.note(
            f"handoff_{DAY}_partly.md", "PARTLY SUPERSEDED: see §3\n\nbody"
        )
        self.transcript(
            sid("a"),
            call("Write", new, 9),
            *[call("Edit", p, 10) for p in (old, front, unclosed, prose, partly)],
        )
        self.assertCountEqual(
            [(r["path"], r["title"]) for r in self.run_report("--live", "s")],
            [
                (new, "Handoff: part 3"),
                (unclosed, f"handoff_{DAY}_meta"),
                (prose, "Prose"),
                (partly, f"handoff_{DAY}_partly"),
            ],
        )

    def test_subagent_work_counts_towards_staleness(self):
        self.session(1, "s", sid("a"))
        self.transcript(
            sid("a"),
            call("Write", self.note(f"handoff_{DAY}.md"), 10),
            call("Agent", hour=11),
        )
        self.transcript(sid("a"), *[call("Edit", "/x/code.py", 11)] * 11, sub="agent-1")
        self.assertEqual(
            [r["verdict"] for r in self.run_report("--live", "s")], ["stale"]
        )

    def test_newest_registry_entry_wins(self):
        self.session(1, "s", sid("0"), updated=1)
        self.session(2, "s", sid("a"), updated=2)
        self.transcript(sid("a"), call("Write", self.note(f"handoff_{DAY}.md")))
        rows = self.run_report("--live", "s")
        self.assertEqual([(r["session"], r["verdict"]) for r in rows], [("s", "fresh")])

    def test_digest_covers_the_day_without_tool_output_or_secrets(self):
        self.session(1, "busy", sid("a"))
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
            say("assistant", "Fixed it, tests pass.", 10),
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
            tool_output("SECRET_TOKEN=abc123", 11),
        )
        out = self.run_cli("--digest", "busy")
        self.assertIn(f"latest note: {note} (Handoff: x), last written 09:00", out)
        self.assertIn(f"write to: {self.dir / 'notes'}", out)  # next to the note
        for present in (
            "USER: morning prompt",
            "PEER: <cross-session-message",
            "CLAUDE: Fixed it, tests pass.",
            "→ Bash: Run the tests",
            "Bearer ***",
        ):
            self.assertIn(present, out)
        for absent in (
            "Base directory",
            "pytest -q",
            "second line",
            "ghp_abc",
            "SECRET_TOKEN",
        ):
            self.assertNotIn(absent, out)

    def test_digest_without_a_note_keeps_the_most_recent_part(self):
        self.session(1, "busy", sid("a"))
        self.transcript(
            sid("a"),
            *[say("assistant", f"step {i:03} " + "x" * 80, 12) for i in range(400)],
        )
        out = self.run_cli("--digest", "busy")
        self.assertIn(f"latest note: none since {DAY}", out)
        self.assertIn(f"write to: {self.dir / 'projects' / '-proj'}", out)
        self.assertIn("earlier lines omitted]", out)
        self.assertIn("step 399", out)
        self.assertNotIn("step 000", out)


if __name__ == "__main__":
    unittest.main()
