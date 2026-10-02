"""Tests for kickoff.py. Run: python3 -m unittest discover -s skills/session-kickoff/scripts"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import kickoff

ME = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
HOME = Path.home()


def tool(name, path):
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": name, "input": {"file_path": str(path)}}
            ]
        },
    }


def said(text, **extra):
    return {"type": "user", "message": {"content": text}, **extra}


def reply(text, stop="end_turn"):
    return {
        "type": "assistant",
        "message": {"stop_reason": stop, "content": [{"type": "text", "text": text}]},
    }


TURN = {"type": "system", "subtype": "turn_duration"}


def sid(x):
    return x * 4 + "-0000-0000-0000-000000000000"


def tmp(test):
    d = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, d)
    return d


def workdays_ago(n):
    """The date n working days before today, as carried() counts them."""
    d = date.today()
    while n:
        n -= d.weekday() < 5
        d -= timedelta(1)
    return d


def transcript(claude, sid, entries, sub=None):
    t = claude / "projects" / "-p" / f"{sid}.jsonl"
    if sub:
        t = t.parent / sid / "subagents" / f"{sub}.jsonl"
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


class Parsing(unittest.TestCase):
    def focus(self, text, heading="Today's Focus"):
        return list(kickoff.items(kickoff.section(text, heading)))

    def test_section_stops_at_next_heading_and_skips_done_and_nested_items(self):
        text = (
            "# Day\n## 🎯 Today's Focus\n<!-- hint -->\n- [ ] one\n  - [ ] nested\n"
            "- [x] done\n- [-] cancelled\n- [/] started\n- plain\n#tag line\n## Next\n- [ ] later\n"
        )
        self.assertEqual(
            self.focus(text),
            [
                (False, "one"),
                (True, "done"),
                (True, "cancelled"),
                (False, "started"),
                (False, "plain"),
            ],
        )

    def test_subheadings_stay_in_the_section_and_code_blocks_are_skipped(self):
        text = (
            "## 🎯 Today's Focus\n### Morning\n- [ ] a\n```bash\n# run this first\n- [ ] no\n```\n"
            "### Afternoon\n- [ ] b\n---\n- [ ] backlog\n"
        )
        self.assertEqual(self.focus(text), [(False, "a"), (False, "b")])
        self.assertEqual(
            self.focus("# Day\n## Focus\n- [ ] a\n# Other\n- [ ] b\n", "Focus"),
            [(False, "a")],
        )

    def test_numbered_items_count_but_not_nested_ones(self):
        # the template's "ONE main thing" line is numbered: on 2026-10-01 it got no session
        text = "## 🎯 Today's Focus\n1. **a** `~/p/handoff.md`\n3. [x] c\n   1. d\n- [ ] e\n"
        self.assertEqual(
            self.focus(text),
            [(False, "**a** `~/p/handoff.md`"), (True, "c"), (False, "e")],
        )

    def test_heading_matches_with_its_hashes_and_emoji_aside(self):
        text = "## 🎯 Today's Focus\n- [ ] a\n"
        self.assertEqual(self.focus(text, "## Today's Focus"), [(False, "a")])
        self.assertEqual(self.focus(text, "## 🎯 Today's Focus"), [(False, "a")])

    def test_missing_heading_fails(self):
        with self.assertRaises(SystemExit):
            kickoff.section("## Other\n", "Today's Focus")

    def test_title_prefers_bold_then_text_without_links(self):
        self.assertEqual(
            kickoff.title("**openEO follow-through:** check #128 `~/a/handoff.md`"),
            "openEO follow-through",
        )
        self.assertEqual(
            kickoff.title("S2 drain [[x-handoff]] `~/a/handoff.md`"), "S2 drain"
        )

    def test_slug_is_short_and_unique(self):
        taken = {"s2-drain"}
        self.assertEqual(kickoff.slug("S2 drain", taken), "s2-drain-2")
        self.assertEqual(
            kickoff.slug("Morning runbook: close out HP→STANDARD", taken),
            "morning-runbook-close-out-hp-standard",
        )
        self.assertLessEqual(len(kickoff.slug("x " * 60, taken)), 40)
        self.assertEqual(kickoff.slug("→", taken), "kickoff")


class Carried(unittest.TestCase):
    def test_working_days_since_the_date_in_the_notes_name(self):
        thu, mon = date(2026, 10, 1), date(2026, 10, 5)
        self.assertEqual(kickoff.carried(Path("handoff_2026-09-28_s2.md"), thu), 3)
        self.assertEqual(kickoff.carried(Path("handoff_2026-10-02_fri.md"), mon), 1)
        self.assertEqual(kickoff.carried(Path("20260928-handoff.md"), thu), 3)
        self.assertEqual(kickoff.carried(Path("handoff_2026-10-05_ahead.md"), thu), 0)
        self.assertIsNone(kickoff.carried(Path("x-handoff.md"), thu))
        self.assertIsNone(kickoff.carried(Path("handoff_2026-19-40.md"), thu))
        # an ID that looks like a date is years off: no note is carried that long
        self.assertIsNone(kickoff.carried(Path("handoff_pr2015-01-02.md"), thu))
        self.assertIsNone(kickoff.carried(Path("handoff_ticket-20190312345.md"), thu))
        self.assertEqual(kickoff.carried(Path("handoff_2026-07-01.md"), thu), 66)


class Links(unittest.TestCase):
    def setUp(self):
        self.vault = tmp(self)
        (self.vault / ".obsidian").mkdir()
        for folder in ("docs", "projA", "projB", ".trash"):
            (self.vault / folder).mkdir()
        (self.vault / "docs" / "2026-09-29-handoff-restart.md").write_text("x")
        (self.vault / "docs" / "Handoff-Wiki.md").write_text("x")
        for folder in ("projA", "projB", ".trash"):
            (self.vault / folder / "x-handoff.md").write_text("x")
        kickoff.vault_notes.cache_clear()

    def note(self, text):
        return kickoff.note_of(text, self.vault)

    def test_paths_backticked_bare_or_ending_a_sentence(self):
        self.assertEqual(self.note("**a** `~/p/handoff_x.md`"), HOME / "p/handoff_x.md")
        self.assertEqual(
            self.note("a ~/p/handoffs/2026-09-29-x.md"),
            HOME / "p/handoffs/2026-09-29-x.md",
        )
        self.assertEqual(
            self.note("resume from ~/p/handoff_s2.md."), HOME / "p/handoff_s2.md"
        )
        self.assertIsNone(self.note("old copy ~/p/handoff_s2.md.bak"))

    def test_first_handoff_link_wins_and_others_are_ignored(self):
        text = (
            "see `~/p/plan.md` https://x.org/a/handoff.md https://x/v?path=/d/handoff.md "
            "then `/abs/b-handoff.md`"
        )
        self.assertEqual(self.note(text), Path("/abs/b-handoff.md"))
        self.assertIsNone(self.note("review https://github.com/o/r/pull/415"))
        self.assertIsNone(self.note("[[guide_daily_note]]"))

    def test_handoffs_folder_needs_a_dated_note_and_memory_is_left_out(self):
        text = (
            "index `~/p/handoffs/README.md`, pointer `~/p/memory/project_s2_handoff.md`, "
            "then `~/p/handoffs/2026-09-29-deploy.md`"
        )
        self.assertEqual(self.note(text), HOME / "p/handoffs/2026-09-29-deploy.md")

    def test_wikilink_found_by_folder_and_any_case_or_reported_missing(self):
        docs = self.vault / "docs"
        self.assertEqual(
            self.note("post it [[2026-09-29-handoff-restart|alias]]"),
            docs / "2026-09-29-handoff-restart.md",
        )
        self.assertEqual(
            self.note("[[projB/x-handoff]]"), self.vault / "projB" / "x-handoff.md"
        )
        self.assertEqual(self.note("[[handoff-wiki]]"), docs / "Handoff-Wiki.md")
        self.assertFalse(self.note("[[old-handoff]]").exists())


class Notes(unittest.TestCase):
    def setUp(self):
        self.dir = tmp(self)

    def write(self, name, text):
        (self.dir / name).write_text(text)
        return self.dir / name

    def test_superseded_banner_after_frontmatter(self):
        banner = self.write(
            "a.md", "---\ntitle: x\n---\n\n> ⏭️ **SUPERSEDED by b.md**\n# Old\n"
        )
        prose = self.write("b.md", "# Plan\nThe old approach was superseded in part.\n")
        self.assertEqual(kickoff.unusable(banner), "superseded")
        self.assertIsNone(kickoff.unusable(prose))

    def test_missing_or_unreadable_note(self):
        self.assertEqual(kickoff.unusable(self.dir / "gone.md"), "missing")
        locked = self.dir / "locked"
        locked.mkdir()
        (locked / "handoff.md").write_text("x")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        self.assertEqual(kickoff.unusable(locked / "handoff.md"), "missing")


class ProjectDir(unittest.TestCase):
    def setUp(self):
        self.root = tmp(self)
        self.claude = self.root / ".claude"

    def project(self, *parts):
        real = self.root.joinpath(*parts)
        real.mkdir(parents=True)
        encoded = (
            self.claude / "projects" / kickoff.re.sub(r"[^A-Za-z0-9]", "-", str(real))
        )
        encoded.mkdir(parents=True)
        return real, encoded

    def test_maps_encoded_dir_to_the_existing_path(self):
        real, encoded = self.project("ds", "skills")
        known = [
            str(self.root / "ds-skills"),
            str(real),
        ]  # same encoding, only one exists
        note = encoded / "tasks" / "pr5-handoff.md"
        self.assertEqual(kickoff.project_dir(note, self.claude, known), str(real))
        self.assertIsNone(
            kickoff.project_dir(self.root / "v" / "handoff.md", self.claude, known)
        )

    def test_snapshot_starts_in_the_project_of_the_session_it_describes(self):
        wrapup, wrapup_dir = self.project("work")
        work, work_dir = self.project("work", "org", "app")
        (work_dir / "bbbbbbbb-0000-0000-0000-000000000000.jsonl").write_text("")
        note = wrapup_dir / "handoff_2026-09-29_snapshot-bbbbbbbb.md"
        known = [str(wrapup), str(work)]
        self.assertEqual(kickoff.project_dir(note, self.claude, known), str(work))


def agents(*sessions):
    out = json.dumps(
        [
            s if isinstance(s, dict) else {"sessionId": s, "name": f"n-{s[:2]}"}
            for s in sessions
        ]
    )
    return mock.Mock(stdout=out, returncode=0)


def outside_sandbox(test):
    env = mock.patch.dict(os.environ)
    env.start()
    test.addCleanup(env.stop)
    os.environ.pop("SANDBOX_RUNTIME", None)


class Sessions(unittest.TestCase):
    def setUp(self):
        outside_sandbox(self)
        self.claude = tmp(self)

    def listed(self, reply):
        with mock.patch.object(kickoff.subprocess, "run", return_value=reply) as run:
            got = kickoff.sessions(ME, self.claude)
        self.assertEqual(run.call_args.args[0], ["claude", "agents", "--json", "--all"])
        return got

    def test_fails_when_it_cannot_see_itself(self):
        with self.assertRaises(SystemExit):
            self.listed(agents())

    def test_refuses_to_run_in_the_sandbox(self):
        # the sandbox lists running sessions as failed: they'd look free and get a second session
        os.environ["SANDBOX_RUNTIME"] = "1"
        with (
            mock.patch.object(kickoff.subprocess, "run") as run,
            self.assertRaisesRegex(SystemExit, "sandbox"),
        ):
            kickoff.sessions(ME, self.claude)
        run.assert_not_called()

    def test_a_resumed_session_keeps_its_place_by_when_its_transcript_began(self):
        # resuming yesterday's session, background or not, moves its startedAt to now
        old, new = "33" * 16, "44" * 16
        transcript(
            self.claude,
            old,
            [{"type": "mode"}, said("x", timestamp="2026-09-30T08:00:00Z")],
        )
        transcript(self.claude, new, [said("y", timestamp="2026-10-01T08:18:36.994Z")])
        got = self.listed(
            agents(
                {"sessionId": ME, "name": "me", "startedAt": 1},
                {"sessionId": old, "name": "yesterday", "startedAt": 9e12},
                {"sessionId": new, "name": "today", "startedAt": 2},
            )
        )
        self.assertEqual(
            [name for name, _ in got.values()], ["me", "yesterday", "today"]
        )

    def test_reports_the_cli_error(self):
        with self.assertRaisesRegex(SystemExit, "daemon not running"):
            self.listed(mock.Mock(returncode=1, stderr="daemon not running\n"))

    def test_lists_itself_and_others_oldest_first_but_not_failed_background_sessions(
        self,
    ):
        failed = {
            "sessionId": "33" * 16,
            "name": "broke",
            "kind": "background",
            "state": "failed",
        }
        done = {
            "sessionId": "44" * 16,
            "name": "idle",
            "kind": "background",
            "state": "done",
            "startedAt": 1,
        }
        got = self.listed(
            agents(
                {"sessionId": ME, "name": "me", "startedAt": 3},
                failed,
                done,
                {"sessionId": OTHER, "name": "n-22", "startedAt": 2},
            )
        )
        self.assertEqual(
            list(got.items()),
            [("44" * 16, ("idle", "done")), (OTHER, ("n-22", "-")), (ME, ("me", "-"))],
        )


class Claims(unittest.TestCase):
    def setUp(self):
        self.claude = tmp(self)

    def test_first_prompt_or_an_edit_claims_a_note_but_a_read_or_later_message_does_not(
        self,
    ):
        opened, edited, read, mentioned = (
            HOME / "p" / f"handoff_{n}.md" for n in "abcd"
        )
        transcript(
            self.claude,
            OTHER,
            [
                said(f"skill text {mentioned}", isMeta=True),
                said("Can you open ~/p/handoff_a.md and …"),
                tool("Edit", edited),
                tool("Read", read),
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {"type": "tool_result", "content": f"- [ ] `{mentioned}`"}
                        ]
                    },
                },
                said(f"<task-notification> {mentioned}"),
            ],
        )
        held = kickoff.claims(
            {OTHER: "n-22"}, {opened, edited, read, mentioned}, self.claude
        )
        self.assertEqual(held, {opened: OTHER, edited: OTHER})

    def test_a_local_command_or_shell_line_before_the_first_prompt_does_not_hide_it(
        self,
    ):
        a, b = HOME / "p" / "handoff_a.md", HOME / "p" / "handoff_b.md"
        transcript(
            self.claude,
            OTHER,
            [
                said(
                    "<command-name>/model</command-name>\n<command-message>model</command-message>"
                    "\n<command-args>opus</command-args>"
                ),
                said("<local-command-stdout>Set model to opus</local-command-stdout>"),
                said("<bash-input>git status</bash-input>"),
                said("<bash-stdout>clean</bash-stdout><bash-stderr></bash-stderr>"),
                said("Can you open ~/p/handoff_a.md and …"),
            ],
        )
        self.assertEqual(
            kickoff.claims({OTHER: "n-22"}, {a, b}, self.claude), {a: OTHER}
        )

    def test_odd_lines_and_unreadable_transcripts_are_skipped(self):
        note = HOME / "p" / "handoff_a.md"
        (self.claude / "projects" / "-q" / f"{OTHER}.jsonl").mkdir(parents=True)
        t = self.claude / "projects" / "-p" / f"{OTHER}.jsonl"
        t.parent.mkdir(parents=True)
        t.write_text(
            '[1, 2]\nnull\n{"type": "user", "message": "hi ~/p/handoff_a.md"}\n'
            + json.dumps(said("Can you open ~/p/handoff_a.md and …"))
            + "\n"
        )
        self.assertEqual(
            kickoff.claims({OTHER: "n-22"}, {note}, self.claude), {note: OTHER}
        )

    def test_a_subagent_edit_claims_for_its_session(self):
        note = HOME / "p" / "handoff_x.md"
        transcript(self.claude, OTHER, [said("Fix the flaky retry test")])
        transcript(
            self.claude,
            OTHER,
            [said(f"write {note}"), tool("Write", note)],
            sub="agent-1",
        )
        self.assertEqual(
            kickoff.claims({OTHER: "n-22"}, {note}, self.claude), {note: OTHER}
        )

    def test_the_newest_session_wins_a_note(self):
        note = HOME / "p" / "handoff_x.md"
        old, new = "33" * 16, "44" * 16
        for sid in (old, new):
            transcript(self.claude, sid, [said("Can you open ~/p/handoff_x.md and …")])
        # sessions() lists oldest first; claims() answers with session ids
        self.assertEqual(
            kickoff.claims({old: "yesterday", new: "today"}, {note}, self.claude),
            {note: new},
        )

    def test_a_snapshot_belongs_to_the_session_it_describes_not_its_writer(self):
        wrapup, work = "33" * 16, "bbbbbbbb-0000-0000-0000-000000000000"
        snap = HOME / "p" / "handoff_2026-09-29_snapshot-bbbbbbbb.md"
        transcript(
            self.claude, wrapup, [said("/session-handoffs"), tool("Write", snap)]
        )
        others = {wrapup: "wrap-up"}
        self.assertEqual(kickoff.claims(others, {snap}, self.claude), {})
        others[work] = "s2-drain"
        self.assertEqual(kickoff.claims(others, {snap}, self.claude), {snap: work})


class Main(unittest.TestCase):
    def setUp(self):
        self.root = tmp(self)
        self.claude = self.root / ".claude"
        self.proj = self.root / "work" / "repo"
        self.proj.mkdir(parents=True)
        pdir = (
            self.claude
            / "projects"
            / kickoff.re.sub(r"[^A-Za-z0-9]", "-", str(self.proj))
        )
        pdir.mkdir(parents=True)
        self.free = pdir / "handoff_free.md"
        self.other = pdir / "handoff_other.md"
        self.held = pdir / "handoff_held.md"
        old = pdir / "handoff_old.md"
        for n in (self.free, self.other, self.held):
            n.write_text("# note\n")
        old.write_text("> SUPERSEDED by handoff_free.md\n")
        (self.claude / ".claude.json").write_text(
            json.dumps({"projects": {str(self.proj): {}}})
        )
        # a running session that already edited the held note
        (pdir / f"{OTHER}.jsonl").write_text(json.dumps(tool("Edit", self.held)) + "\n")
        self.daily = self.root / "daily.md"
        self.daily.write_text(
            "## 🎯 Today's Focus\n"
            f"- [ ] **Free work** `{self.free}`\n"
            f"- [x] **Done** `{self.free}`\n"
            f"- [ ] **Held work** `{self.held}`\n"
            "- [ ] review https://github.com/o/r/pull/415\n"
            f"- [ ] **Gone** `{self.proj}/handoff_gone.md`\n"
            f"- [ ] **Other work** `{self.other}`\n"
            f"- [ ] **Old** `{old}`\n"
            f"- [ ] **Free again** `{self.free}`\n"
            "## Next\n"
        )
        outside_sandbox(self)
        os.environ.update(CLAUDE_CONFIG_DIR=str(self.claude), CLAUDE_CODE_SESSION_ID=ME)
        self.pdir = pdir

    def run_main(self, *args, launch=lambda cmd: mock.Mock()):
        calls = []

        def fake_run(cmd, **kw):
            if cmd[:2] == ["claude", "agents"]:
                return agents(ME, OTHER)
            calls.append((cmd, kw.get("cwd")))
            return launch(cmd)

        out = io.StringIO()
        with (
            mock.patch.object(kickoff.subprocess, "run", side_effect=fake_run),
            contextlib.redirect_stdout(out),
        ):
            kickoff.main([str(self.daily), "--claude-dir", str(self.claude), *args])
        rows = [line.split("\t") for line in out.getvalue().splitlines()[1:]]
        return {r[0]: r for r in rows}, calls

    def prompt(self, note):
        return (
            f"Can you open {kickoff.tilde(note)} and tell me what I should do next? End with "
            "one plain line, no formatting: Next: <one step> · Needs me: yes/no · Time: "
            "<estimate>"
        )

    def test_the_question_names_the_note(self):
        # a session claims its note by its first prompt
        self.assertIn(str(self.free), kickoff.PROMPT.format(note=self.free))

    def test_dry_run_reports_each_open_item_and_opens_nothing(self):
        rows, calls = self.run_main("--dry-run")
        self.assertEqual(
            {k: r[1] for k, r in rows.items()},
            {
                "1": "would open",
                "3": "open in n-22",
                "4": "no note",
                "5": "missing",
                "6": "would open",
                "7": "superseded",
                "8": "open in free-work",
            },
        )
        self.assertEqual(rows["1"][2:4], ["free-work", kickoff.tilde(self.proj)])
        self.assertEqual(calls, [])

    def test_a_numbered_item_opens_like_a_bullet(self):
        self.daily.write_text(f"## 🎯 Today's Focus\n1. **Top thing** `{self.free}`\n")
        rows, _ = self.run_main("--dry-run")
        self.assertEqual(rows["1"][1:3], ["would open", "top-thing"])

    def test_an_item_whose_note_is_three_working_days_old_is_flagged_but_still_opens(
        self,
    ):
        stuck = self.pdir / f"handoff_{workdays_ago(3)}_stuck.md"
        fresh = self.pdir / f"handoff_{workdays_ago(1)}_fresh.md"
        for n in (stuck, fresh):
            n.write_text("# note\n")
        # counted to today, not to the daily note's date: the fallback reads yesterday's list
        self.daily = self.root / "2026-01-01.md"
        self.daily.write_text(
            f"## 🎯 Today's Focus\n- [ ] **Stuck** `{stuck}`\n"
            f"- [ ] **Fresh** `{fresh}`\n- [ ] **Stuck again** `{stuck}`\n"
        )
        rows, calls = self.run_main()
        self.assertEqual(
            [rows[k][1] for k in "123"],
            ["opened · carried 3d", "opened", "open in stuck · carried 3d"],
        )
        self.assertEqual(
            len(calls), 2
        )  # the flag doesn't make the shared note open twice

    def test_the_calling_session_counts_as_working_from_its_note(self):
        # re-run from a session kickoff started: its own note gets no second session
        transcript(self.claude, ME, [said(self.prompt(self.other))])
        rows, _ = self.run_main("--dry-run")
        self.assertEqual(rows["6"][1], "open in n-11")

    def test_the_calling_session_does_not_claim_what_it_only_touched(self):
        # a morning session that wrote a note, or ran a subagent that did, doesn't work from it
        transcript(
            self.claude,
            ME,
            [
                said(
                    "<command-message>session-kickoff</command-message>\n"
                    "<command-name>/session-kickoff</command-name>"
                ),
                tool("Write", self.other),
            ],
        )
        transcript(
            self.claude,
            ME,
            [said(f"tidy {self.free}"), tool("Edit", self.free)],
            sub="agent-1",
        )
        rows, _ = self.run_main("--dry-run")
        self.assertEqual((rows["1"][1], rows["6"][1]), ("would open", "would open"))

    def test_default_starts_background_sessions_in_the_project(self):
        rows, calls = self.run_main()
        self.assertEqual((rows["1"][1], rows["6"][1]), ("opened", "opened"))
        self.assertEqual(rows["8"][1], "open in free-work")
        self.assertEqual(
            calls,
            [
                (
                    ["claude", "--bg", "-n", "free-work", self.prompt(self.free)],
                    str(self.proj),
                ),
                (
                    ["claude", "--bg", "-n", "other-work", self.prompt(self.other)],
                    str(self.proj),
                ),
            ],
        )

    def refuse(self, cmd):
        raise kickoff.subprocess.CalledProcessError(1, cmd, stderr="no such\nproject")

    def test_a_failure_is_reported_and_does_not_stop_the_rest(self):
        rows, calls = self.run_main(launch=self.refuse)
        self.assertEqual(rows["1"][1], "failed: no such project")
        self.assertEqual(rows["6"][1], "failed: no such project")
        self.assertEqual(len(calls), 3)  # item 8 retries the note item 1 failed to open


class Digest(unittest.TestCase):
    def setUp(self):
        outside_sandbox(self)
        os.environ["CLAUDE_CODE_SESSION_ID"] = ME
        self.root = tmp(self)
        self.claude = self.root / ".claude"
        self.notes = [self.root / f"handoff_{x}.md" for x in "abc"]
        for n in self.notes:
            n.write_text("# note\n")
        self.daily = self.root / "daily.md"
        self.daily.write_text(
            "## 🎯 Today's Focus\n"
            + "".join(f"- [ ] **{n.stem}** `{n}`\n" for n in self.notes)
            + f"- [ ] no note here\n- [ ] **Gone** `{self.root}/handoff_gone.md`\n"
        )
        self.listing = [{"sessionId": ME, "name": "morning", "kind": "interactive"}]

    def started(
        self, sid, first, *entries, state="done", name=None, when="2026-10-01T08:00Z"
    ):
        """A session listed by `claude agents`, whose first prompt is `first`."""
        transcript(self.claude, sid, [said(first, timestamp=when), *entries])
        self.listing.append({"sessionId": sid, "name": name or sid[:8], "state": state})

    def ask(self, note):
        return kickoff.PROMPT.format(note=note)

    def digest(self):
        out, launched = io.StringIO(), []

        def fake_run(cmd, **kw):
            if cmd[:2] == ["claude", "agents"]:
                return agents(*self.listing)
            launched.append(cmd)

        with (
            mock.patch.object(kickoff.subprocess, "run", side_effect=fake_run),
            contextlib.redirect_stdout(out),
        ):
            kickoff.main(
                [str(self.daily), "--claude-dir", str(self.claude), "--digest"]
            )
        self.assertEqual(launched, [])  # starts nothing and never waits on a session
        rows = [line.split("\t") for line in out.getvalue().splitlines()]
        self.assertEqual(rows[0], ["item", "state", "name", "answer"])
        return {r[0]: r[1:] for r in rows[1:]}

    def test_each_item_gets_the_session_kickoff_would_name_and_its_answer(self):
        a, b, c = self.notes
        self.started(
            sid("a1"),
            self.ask(a),
            reply("Next: yesterday's · Needs me: no"),
            TURN,
            name="yesterday",
            when="2026-09-30T08:00Z",
        )
        self.started(
            sid("a2"),
            self.ask(a),
            reply("Reading the note first.", stop="tool_use"),
            reply(
                "It's waiting on the port-forwards.\n\n**Next:** run\tthe  checks · "
                "Needs me: yes · Time: 10 min"
            ),
            TURN,
            state="blocked",
            name="s2-drain",
        )
        # started on other work, then wrote note b: kickoff counts that, so does the digest
        self.started(
            sid("b1"),
            "Fix the flaky retry test",
            tool("Write", b),
            reply("x" * 200 + "\nmore"),
            TURN,
            name="flaky-test",
        )
        # on c: one session that has since closed, one that crashed (listed as failed)
        transcript(
            self.claude,
            sid("c1"),
            [said(f"Is {c} still accurate?"), reply("Yes."), TURN],
        )
        self.started(
            sid("c2"), self.ask(c), reply("Next: go · Needs me: no"), state="failed"
        )
        self.assertEqual(
            self.digest(),
            {
                "1": [
                    "blocked",
                    "s2-drain",
                    "run the checks · Needs me: yes · Time: 10 min",
                ],
                "2": ["done", "flaky-test", "x" * 120],
                "3": ["no session", "-", "-"],
                "4": ["no note", "-", "-"],
                "5": ["missing", "-", "-"],
            },
        )

    def test_an_interactive_session_counts_and_one_whose_note_was_replaced_still_shows(
        self,
    ):
        a, b, _ = self.notes
        self.listing.append(
            {"sessionId": sid("a1"), "name": "free-work", "kind": "interactive"}
        )
        transcript(
            self.claude,
            sid("a1"),
            [said(self.ask(a)), reply("Next: go · Needs me: no")],
        )
        self.started(
            sid("b1"), self.ask(b), reply("Next: point the item at the new note"), TURN
        )
        b.write_text("> SUPERSEDED by handoff_d.md\n")
        rows = self.digest()
        self.assertEqual(rows["1"], ["-", "free-work", "go · Needs me: no"])
        self.assertEqual(
            rows["2"], ["done", sid("b1")[:8], "point the item at the new note"]
        )

    def test_the_answer_to_the_latest_request_counts_and_an_unanswered_session_says_so(
        self,
    ):
        a, b, c = self.notes
        # a background agent's notification is no request: the answer runs on past it
        self.started(
            sid("a1"),
            self.ask(a),
            reply("Next: rerun checks · Needs me: yes"),
            TURN,
            said("<task-notification>agent done</task-notification>"),
            reply("The agent finished; waiting on the other one."),
            TURN,
            state="blocked",
        )
        # a follow-up you typed is: its answer replaces the first
        self.started(
            sid("b1"),
            self.ask(b),
            reply("Next: merge · Needs me: yes"),
            TURN,
            said("merged, thanks"),
            reply("Great, closing the note."),
            TURN,
        )
        self.started(
            sid("c1"),
            self.ask(c),
            reply("Reading the note first.", stop="tool_use"),
            state="working",
        )
        rows = self.digest()
        self.assertEqual(rows["1"][2], "rerun checks · Needs me: yes")
        self.assertEqual(rows["2"][2], "Great, closing the note.")
        self.assertEqual(rows["3"][::2], ["working", "(no reply yet)"])

    def test_the_next_line_is_the_answers_own_and_whole(self):
        for reply_text, want in [
            (
                "Plan.\n\nNext: run `pytest tests/**/*.py` · Needs me: no",
                "run `pytest tests/**/*.py` · Needs me: no",
            ),
            ("**Next step:** ship it", "ship it"),
            (
                "Done.\nNext: a · Needs me: no\n\nNext week: the review",
                "a · Needs me: no",
            ),
            ("Next: a · Needs me: no\nNext: b", "a · Needs me: no"),
            ("**Next steps:**\n1. Run the checks", "**Next steps:**"),
            ("Ready.\nNext:\n```bash", "Ready."),
            ("The note says:\n> Next: deploy v2", "The note says:"),
            ("Bump it.\nNext.js: 15", "Bump it."),
            (None, "(no reply yet)"),
        ]:
            self.assertEqual(kickoff.answer(reply_text), want, reply_text)


if __name__ == "__main__":
    unittest.main()
