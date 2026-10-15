"""uses_excluded_path, and the excluded_path skip through run_capture and main().

EXCLUDED_PATHS defaults to empty, so the unit tests pass the folder list explicitly.
"""

import json
import pathlib
import subprocess

import pytest

import curate
from conftest import read_log
from curate import EXCLUDED_PATHS, uses_excluded_path

ADR = (
    pathlib.Path(__file__).parent.parent
    / "eval"
    / "fixtures"
    / "transcripts"
    / "adr-worthy.jsonl"
)


def _tool(name: str, **inp) -> dict:
    """An assistant message carrying one tool_use block."""
    return {
        "role": "assistant",
        "content": "",
        "blocks": [{"type": "tool_use", "id": "t", "name": name, "input": inp}],
    }


@pytest.fixture
def dirs(tmp_path):
    """<tmp>/client (excluded), <tmp>/client-two and <tmp>/outside (not)."""
    for d in ("client/sub", "client-two", "outside"):
        (tmp_path / d).mkdir(parents=True)
    return tmp_path


class TestUsesExcludedPath:
    def test_empty_list_excludes_nothing(self, dirs):
        assert EXCLUDED_PATHS == []
        assert uses_excluded_path([], str(dirs / "client"), []) is False
        assert uses_excluded_path([], str(dirs / "client")) is False

    @pytest.mark.parametrize("cwd", ["client", "client/sub"])
    def test_cwd_in_or_below_entry(self, dirs, cwd):
        assert uses_excluded_path([], str(dirs / cwd), [str(dirs / "client")]) is True

    def test_sibling_with_shared_prefix_is_not_excluded(self, dirs):
        cwd = str(dirs / "client-two")
        assert uses_excluded_path([], cwd, [str(dirs / "client")]) is False

    def test_trailing_slash_entry(self, dirs):
        entry = str(dirs / "client") + "/"
        assert uses_excluded_path([], str(dirs / "client/sub"), [entry]) is True

    def test_tilde_entry(self, dirs, monkeypatch):
        monkeypatch.setenv("HOME", str(dirs))
        assert uses_excluded_path([], str(dirs / "client"), ["~/client"]) is True

    def test_symlinked_entry_and_symlinked_cwd(self, dirs):
        link = dirs / "link-to-client"
        link.symlink_to(dirs / "client")
        assert uses_excluded_path([], str(dirs / "client/sub"), [str(link)]) is True
        assert uses_excluded_path([], str(link / "sub"), [str(dirs / "client")]) is True

    def test_symlink_inside_entry_pointing_out(self, dirs):
        """Read through <entry>/notes -> <outside>: the literal path is inside."""
        (dirs / "client" / "notes").symlink_to(dirs / "outside")
        msgs = [_tool("Read", file_path=str(dirs / "client" / "notes" / "a.md"))]
        cwd = str(dirs / "outside")
        assert uses_excluded_path(msgs, cwd, [str(dirs / "client")]) is True

    def test_case_is_ignored(self, dirs):
        entry = str(dirs / "client").upper()
        assert uses_excluded_path([], str(dirs / "client"), [entry]) is True

    def test_any_message_cwd_counts(self, dirs):
        msgs = [{"role": "user", "content": "hi", "cwd": str(dirs / "client/sub")}]
        cwd = str(dirs / "outside")
        assert uses_excluded_path(msgs, cwd, [str(dirs / "client")]) is True

    def test_file_tool_paths(self, dirs):
        entry = [str(dirs / "client")]
        outside = str(dirs / "outside")
        read = [_tool("Read", file_path=str(dirs / "client" / "a.md"))]
        assert uses_excluded_path(read, outside, entry) is True
        # relative path, resolved against the message's cwd
        grep = _tool("Grep", pattern="x", path="client")
        grep["cwd"] = str(dirs)
        assert uses_excluded_path([grep], outside, entry) is True
        parent = [_tool("Grep", pattern="x", path=str(dirs))]
        assert uses_excluded_path(parent, outside, entry) is False

    def test_shell_commands(self, dirs):
        entry = [str(dirs / "client")]
        outside = str(dirs / "outside")
        inside = [_tool("Bash", command=f"cat {dirs / 'client'}/a.md | head")]
        assert uses_excluded_path(inside, outside, entry) is True
        assert (
            uses_excluded_path([_tool("Bash", command=f"ls {dirs}")], outside, entry)
            is False
        )
        two = [_tool("Bash", command=f"cat {dirs / 'client-two'}/a")]
        assert uses_excluded_path(two, outside, entry) is False

    def test_glob_pattern_without_path(self, dirs):
        msgs = [_tool("Glob", pattern=f"{dirs / 'client'}/**/*.md")]
        cwd = str(dirs / "outside")
        assert uses_excluded_path(msgs, cwd, [str(dirs / "client")]) is True

    def test_nested_mcp_input(self, dirs):
        msgs = [_tool("mcp__x__read", args={"target": f"{dirs / 'client'}/n.md"})]
        cwd = str(dirs / "outside")
        assert uses_excluded_path(msgs, cwd, [str(dirs / "client")]) is True

    def test_relative_entry_fails_closed(self, dirs, capsys):
        assert uses_excluded_path([], str(dirs / "outside"), ["client-x"]) is True
        assert "CAPTURE_BAD_SETTING\t" in capsys.readouterr().err

    def test_worktree_outside_its_main_checkout(self, tmp_path, monkeypatch):
        for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
            monkeypatch.delenv(var, raising=False)
        repo = tmp_path / "repo"
        repo.mkdir()
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            [
                *git,
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "i",
            ],
            check=True,
        )
        wt = tmp_path / "repo-wt"
        subprocess.run([*git, "worktree", "add", "-q", str(wt)], check=True)
        assert uses_excluded_path([], str(wt), [str(repo)]) is True


class TestExcludedPathSkip:
    def test_subagent_read_skips_the_session(self, dirs, temp_vault, monkeypatch):
        calls = []
        monkeypatch.setattr(curate, "_call_path_a", lambda *a, **k: calls.append(a))
        monkeypatch.setattr(curate, "EXCLUDED_PATHS", [str(dirs / "client")])
        transcript = curate._load_transcript(str(ADR))
        assert not uses_excluded_path(transcript, str(dirs / "outside"))

        curate.run_capture(
            transcript=transcript,
            session_id="5ub0011223344556",
            cwd=str(dirs / "outside"),
            vault_dir=temp_vault.vault_dir,
            log_path=temp_vault.log_path,
            index_path=temp_vault.index_path,
            subagent_messages=[_tool("Read", file_path=str(dirs / "client" / "a.md"))],
        )

        assert calls == []
        assert read_log(temp_vault.log_path)[-1]["skip_reason_a"] == "excluded_path"

    def test_main_skips_before_any_model_call(
        self, run_main, monkeypatch, temp_vault, tmp_path
    ):
        monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")
        monkeypatch.setattr(curate, "EXCLUDED_PATHS", [str(tmp_path / "secret")])
        calls = []
        monkeypatch.setattr(curate, "_call_path_a", lambda *a, **k: calls.append(a))
        sid = "5ec7e70011223344"

        entries = run_main(ADR, sid, str(tmp_path / "secret" / "repo"))

        assert calls == []
        assert list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md")) == []
        assert entries[-1]["skip_reason_a"] == "excluded_path"
        assert entries[-1]["redactions"] == {}
        index = temp_vault.index_path
        assert not index.exists() or sid not in index.read_text()

    def test_main_reads_subagent_transcripts(
        self, run_main, monkeypatch, temp_vault, tmp_path
    ):
        monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")
        secret = tmp_path / "secret"
        monkeypatch.setattr(curate, "EXCLUDED_PATHS", [str(secret)])
        calls = []
        monkeypatch.setattr(curate, "_call_path_a", lambda *a, **k: calls.append(a))
        main_path = tmp_path / "sess.jsonl"
        main_path.write_bytes(ADR.read_bytes())
        (tmp_path / "sess" / "subagents").mkdir(parents=True)
        read = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t",
                        "name": "Read",
                        "input": {"file_path": str(secret / "n.md")},
                    }
                ]
            },
        }
        (tmp_path / "sess" / "subagents" / "agent-x.jsonl").write_text(
            json.dumps(read) + "\n"
        )

        entries = run_main(main_path, "5ab0011223344556", str(tmp_path / "outside"))

        assert calls == []
        assert entries[-1]["skip_reason_a"] == "excluded_path"
