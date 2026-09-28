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


def call(name, path="", hour=12, day=DAY):
    return {
        "type": "assistant",
        "timestamp": f"{day}T{hour:02d}:00:00.000Z",
        "message": {
            "content": [
                {"type": "tool_use", "name": name, "input": {"file_path": path}}
            ]
        },
    }


class HandoffStatusTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "sessions").mkdir()
        (self.dir / "projects" / "-proj").mkdir(parents=True)
        (self.dir / "sessions" / "9.abc.key").write_text("not json, never read")
        # fixtures use UTC timestamps (the script compares local dates) and live in a temp dir
        self.addCleanup(time.tzset)
        for patcher in (
            mock.patch.dict(os.environ, TZ="UTC"),
            mock.patch.object(handoff_status, "TEMP_ROOTS", ()),
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

    def run_report(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            handoff_status.main(["--claude-dir", str(self.dir), "--date", DAY, *args])
        header, *rows = [line.split("\t") for line in out.getvalue().splitlines()]
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
        )  # closed, nothing that day
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
        got = [(r["session"], r["verdict"]) for r in rows]
        self.assertCountEqual(
            got,
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

    def test_only_usable_notes_from_that_day_count(self):
        self.session(1, "s", sid("a"))
        undated = self.note("HANDOFF-cache.md")
        ahead = self.note(
            "handoff_2026-09-30_wednesday.md"
        )  # written ahead for a later day
        skipped = [
            self.note("memory/project-handoff.md"),  # memory pointer
            self.note("handoff_2026-09-25_old.md"),  # older note, edited that day
            self.note("handoff_s2_purge_20260903.md"),  # older, compact date
            self.note("handoff_status.py"),  # not a note
            str(self.dir / f"handoff_{DAY}_denied.md"),  # write never landed
            self.note(f".claude/worktrees/x/handoff_{DAY}.md"),  # worktree
        ]
        self.transcript(
            sid("a"),
            *[call("Write", p) for p in skipped],
            call(
                "Write", self.note(f"handoff_{DAY}_b.md"), day="2026-09-27"
            ),  # other day
            call("Edit", undated),
            call("Write", ahead),
        )
        rows = self.run_report("--live", "s")
        self.assertEqual({r["path"] for r in rows}, {undated, ahead})

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
        prose = self.note(
            f"handoff_{DAY}_prose.md",
            "\ufeff# Prose\n\nThe plan's scope table is superseded by §2.\n",
        )
        partly = self.note(
            f"handoff_{DAY}_partly.md", "PARTLY SUPERSEDED: see §3\n\nbody"
        )
        self.transcript(
            sid("a"),
            call("Write", new, 9),
            *[call("Edit", p, 10) for p in (old, front, prose, partly)],
        )
        rows = self.run_report("--live", "s")
        self.assertCountEqual(
            [(r["path"], r["title"]) for r in rows],
            [
                (new, "Handoff: part 3"),
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


if __name__ == "__main__":
    unittest.main()
