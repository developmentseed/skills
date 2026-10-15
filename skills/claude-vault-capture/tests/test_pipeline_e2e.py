"""End-to-end tests through curate.main(): argv → transcript → run_capture → vault
files → log → index, with model calls replayed from mocks. No network.
"""

import json
import pathlib
import re

import pytest

from conftest import parse_frontmatter, read_log

TRANSCRIPTS = pathlib.Path(__file__).parent.parent / "eval" / "fixtures" / "transcripts"

FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9\-]+-[0-9a-f]{8}\.md$")


def _transcript(name: str) -> pathlib.Path:
    return TRANSCRIPTS / f"{name}.jsonl"


class TestFullPipeline:
    def test_adr_worthy_writes_artifact(
        self, run_main, mock_from_responses, temp_vault
    ):
        """A curated artifact produces a file with correct filename + frontmatter."""
        mock_from_responses("adr-worthy")
        sid = "a1d2c3e4deadbeef0000"
        entries = run_main(_transcript("adr-worthy"), sid, "/tmp")

        auto = list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))
        assert len(auto) == 1
        assert FILENAME_RE.match(auto[0].name), auto[0].name
        assert auto[0].name.endswith(f"-{sid[:8]}.md")

        fm_a = parse_frontmatter(auto[0].read_text())
        assert fm_a["source"] == "claude-code-curated"
        assert fm_a["type"] == "decision"
        assert fm_a["session_id"] == sid
        assert fm_a["model"] == "claude-sonnet-5-5"

        assert len(entries) == 1
        e = entries[0]
        assert e["path_a"] == f"Inbox/auto/{auto[0].name}"
        assert e["skip_reason_a"] is None

    def test_debugging_only_skips(self, run_main, mock_from_responses, temp_vault):
        """path_a: null → no auto file, model_returned_null."""
        mock_from_responses("debugging-only")
        entries = run_main(_transcript("debugging-only"), "dbb5678abcd00000111", "/tmp")

        auto = list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))
        assert auto == []

        e = entries[0]
        assert e["skip_reason_a"] == "model_returned_null"
        assert e["path_a"] is None

    def test_malformed_title_is_sanitized(
        self, run_main, mock_from_responses, temp_vault
    ):
        """Title with | [[ ]] # is sanitized in filename and frontmatter end-to-end."""
        mock_from_responses("malformed-title")
        run_main(_transcript("malformed-title"), "ac901234567abcde0001", "/tmp")

        auto = list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))
        assert len(auto) == 1
        # filename slug carries none of the unsafe characters
        assert FILENAME_RE.match(auto[0].name), auto[0].name

        text = auto[0].read_text()
        fm = parse_frontmatter(text)
        title = fm["title"]
        for bad in ("|", "[[", "]]", "#", "`"):
            assert bad not in title, f"{bad!r} survived in title {title!r}"
        # the H1 heading is also the sanitized title
        assert "[[" not in text.split("---\n", 2)[2]


class TestScrubbingStages:
    def test_input_scrub_records_redactions(
        self, run_main, mock_from_responses, temp_vault
    ):
        """Pre-API scrub runs regardless of mocking — planted secrets are counted."""
        mock_from_responses("with-secrets")
        entries = run_main(_transcript("with-secrets"), "5ec0011223344ff00003", "/tmp")

        redactions = entries[0]["redactions"]
        total = sum(redactions.values())
        assert total > 0, redactions
        # the env-var, bearer, token-prefix, and basic-auth-url rules all fire here
        assert redactions["env_var"] > 0
        assert redactions["bearer"] > 0

    def test_output_scrub_redacts_secret_in_written_file(
        self, run_main, monkeypatch, temp_vault
    ):
        """Inline mock: the with-secrets fixture's returned body is already clean."""
        import curate

        monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")
        secret = "Bearer abc123SECRETtoken456value"
        monkeypatch.setattr(
            curate,
            "_call_path_a",
            lambda *a, **kw: {
                "title": "Decision: leaked Authorization: " + secret,
                "type": "decision",
                "body": "We hardcoded Authorization: " + secret + " — bad idea.",
                "source_links": [],
                "tags": ["security"],
                "tokens_in": 100,
                "tokens_out": 40,
                "cost_usd": 0.001,
            },
        )

        run_main(_transcript("adr-worthy"), "1eaf778899aabbcc0004", "/tmp")

        auto = list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))
        assert len(auto) == 1
        written = auto[0].read_text()
        assert secret not in written
        assert "abc123SECRETtoken456value" not in written
        assert "<redacted:bearer>" in written

    def test_output_scrub_redacts_an_unknown_random_token(
        self, run_main, monkeypatch, temp_vault
    ):
        """No rule knows the shape; the note-only random-token pass catches it."""
        import curate

        monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")
        token = "Kq8vN2xR7mW4pL9sT3yB6cF1hJ5dG0aZ"
        sha = "5251002" + "a" * 33
        monkeypatch.setattr(
            curate,
            "_call_path_a",
            lambda *a, **kw: {
                "title": "Runbook: rotate the vendor key",
                "type": "runbook",
                "body": f"Set VENDOR={token} then deploy {sha}.",
                "source_links": [],
                "tags": [],
            },
        )

        run_main(_transcript("adr-worthy"), "1eaf778899aabbcc0005", "/tmp")

        written = next((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))
        text = written.read_text()
        assert token not in text
        assert "<redacted:high_entropy>" in text
        assert sha in text


def _write_jsonl(path: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def _no_files(temp_vault) -> bool:
    return list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md")) == []


class TestEdgeCaseSkips:
    """Each guard writes exactly one log entry, no files, and never calls a model."""

    def test_empty_transcript_threshold(
        self, run_main, monkeypatch, temp_vault, tmp_path
    ):
        monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")
        tp = tmp_path / "empty.jsonl"
        tp.write_text("")
        entries = run_main(tp, "empty00112233aabb0005", "/tmp")
        assert _no_files(temp_vault)
        assert len(entries) == 1
        assert entries[0]["skip_reason_a"] == "threshold"

    def test_assistant_only_threshold(
        self, run_main, monkeypatch, temp_vault, tmp_path
    ):
        monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")
        tp = _write_jsonl(
            tmp_path / "asst.jsonl",
            [
                {"type": "assistant", "message": {"content": "a" * 2000}}
                for _ in range(3)
            ],
        )
        entries = run_main(tp, "asst00112233aabb0006", "/tmp")
        assert _no_files(temp_vault)
        assert entries[0]["skip_reason_a"] == "threshold"

    def test_excluded_command(self, run_main, monkeypatch, temp_vault, tmp_path):
        monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")
        # EXCLUDED_COMMANDS is resolved at import: patch the constant, not the env var.
        import curate

        monkeypatch.setattr(curate, "EXCLUDED_COMMANDS", ["/my-journal"])
        tp = _write_jsonl(
            tmp_path / "excluded.jsonl",
            [
                {"type": "user", "message": {"content": "/my-journal wrap up today"}},
                {"type": "user", "message": {"content": "more " + "x" * 800}},
                {"type": "user", "message": {"content": "and " + "y" * 800}},
            ],
        )
        entries = run_main(tp, "excl00112233aabb0007", "/tmp")
        assert _no_files(temp_vault)
        assert entries[0]["skip_reason_a"] == "excluded_command"

    def test_token_limit(self, run_main, monkeypatch, temp_vault):
        """Above-threshold transcript + tiny ceiling → token_limit (not threshold)."""
        monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")
        monkeypatch.setenv("CAPTURE_MAX_EST_TOKENS", "10")
        entries = run_main(_transcript("adr-worthy"), "tok00112233aabb0008", "/tmp")
        assert _no_files(temp_vault)
        assert entries[0]["skip_reason_a"] == "token_limit"

    def test_duplicate_session(
        self, run_main, mock_from_responses, temp_vault, monkeypatch
    ):
        """Second capture of the same session_id writes nothing new and logs duplicate."""
        mock_from_responses("adr-worthy")
        calls = _record(monkeypatch)
        sid = "dup00112233aabbccdd09"
        run_main(_transcript("adr-worthy"), sid, "/tmp")
        auto_after_first = list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))
        assert len(auto_after_first) == 1

        entries = run_main(_transcript("adr-worthy"), sid, "/tmp")
        # still exactly one file per path — no second artifact
        assert len(list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))) == 1
        assert entries[-1]["skip_reason_a"] == "duplicate"
        assert len(calls) == 1


def _record(monkeypatch, calls: list[str] | None = None) -> list[str]:
    """Wrap the installed _call_path_a so each call's input text is recorded."""
    import curate

    calls = [] if calls is None else calls
    inner = curate._call_path_a

    def _wrapped(text, *args, **kwargs):
        calls.append(text)
        return inner(text, *args, **kwargs)

    monkeypatch.setattr(curate, "_call_path_a", _wrapped)
    return calls


def _notes(temp_vault) -> list[pathlib.Path]:
    return sorted((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))


def _index_rows(temp_vault, sid: str) -> list[list[str]]:
    lines = temp_vault.index_path.read_text().splitlines()
    return [ln.split("\t") for ln in lines if ln.startswith(sid + "\t")]


class TestResumedSessions:
    """A resumed session keeps its id; only what it added since is curated."""

    SID = "ae5e0011223344556677"

    @pytest.fixture
    def session(self, tmp_path) -> pathlib.Path:
        copy = tmp_path / "resumed.jsonl"
        copy.write_bytes(_transcript("adr-worthy").read_bytes())
        return copy

    @staticmethod
    def _resume(path: pathlib.Path) -> None:
        """Append the fixture again: a resume that adds a whole session's worth."""
        with open(path, "ab") as fh:
            fh.write(_transcript("adr-worthy").read_bytes())

    def test_resumed_session_curates_only_new_part(
        self, run_main, mock_from_responses, temp_vault, monkeypatch, session
    ):
        import curate

        mock_from_responses("adr-worthy")
        run_main(session, self.SID, "/tmp")
        (first,) = _notes(temp_vault)
        self._resume(session)
        mock_from_responses("malformed-title")
        calls = _record(monkeypatch)

        entries = run_main(session, self.SID, "/tmp")

        assert entries[-1]["skip_reason_a"] is None
        notes = _notes(temp_vault)
        assert len(notes) == 2
        second = next(n for n in notes if n != first)
        assert f"[[{first.stem}]]" in second.read_text().split("## Source", 1)[1]
        (text,) = calls
        assert text.startswith("This transcript continues a session")
        assert first.stem in text.split("\n", 1)[0]
        full = curate.render_transcript(curate._load_transcript(str(session)))
        assert len(text) < len(full)
        rows = _index_rows(temp_vault, self.SID)
        assert len(rows) == 2
        assert rows[1][3] == str(session.stat().st_size)

    def test_small_resume_is_duplicate(
        self, run_main, mock_from_responses, temp_vault, monkeypatch, session
    ):
        mock_from_responses("adr-worthy")
        calls = _record(monkeypatch)
        run_main(session, self.SID, "/tmp")
        with open(session, "a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": "thanks"}}))
            fh.write(
                "\n" + json.dumps({"type": "assistant", "message": {"content": "ok"}})
            )
            fh.write("\n")

        entries = run_main(session, self.SID, "/tmp")

        assert entries[-1]["skip_reason_a"] == "duplicate"
        assert len(calls) == 1
        assert len(_index_rows(temp_vault, self.SID)) == 1

    @pytest.mark.parametrize(
        "row",
        ["{sid}\tInbox/auto/f.md\t2026-09-01", "{sid}\tnull\tnull\t2026-04-23"],
        ids=["v2", "v1"],
    )
    def test_legacy_index_rows_stay_duplicate(
        self, run_main, mock_from_responses, temp_vault, monkeypatch, row
    ):
        """Sessions indexed before byte offsets are never re-curated."""
        temp_vault.index_path.write_text(
            "# schema_version: 2\n" + row.format(sid=self.SID) + "\n"
        )
        mock_from_responses("adr-worthy")
        calls = _record(monkeypatch)

        entries = run_main(_transcript("adr-worthy"), self.SID, "/tmp")

        assert entries[-1]["skip_reason_a"] == "duplicate"
        assert calls == []

    def test_continuation_after_null(
        self, run_main, mock_from_responses, temp_vault, monkeypatch, session
    ):
        mock_from_responses("debugging-only")
        run_main(session, self.SID, "/tmp")
        assert _notes(temp_vault) == []
        self._resume(session)
        mock_from_responses("adr-worthy")
        calls = _record(monkeypatch)

        run_main(session, self.SID, "/tmp")

        assert ", with no artifact" in calls[0].split("\n", 1)[0]
        (note,) = _notes(temp_vault)
        assert "[[" not in note.read_text().partition("## Source")[2]

    def test_continuation_timeout_retries(
        self, run_main, mock_from_responses, temp_vault, monkeypatch, session
    ):
        import curate

        mock_from_responses("adr-worthy")
        run_main(session, self.SID, "/tmp")
        self._resume(session)
        calls: list[str] = []

        def _slow(*a, **kw):
            raise TimeoutError("slow")

        monkeypatch.setattr(curate, "_call_path_a", _slow)
        _record(monkeypatch, calls)
        entries = run_main(session, self.SID, "/tmp")
        assert entries[-1]["skip_reason_a"] == "timeout"
        assert len(_index_rows(temp_vault, self.SID)) == 1

        mock_from_responses("malformed-title")
        _record(monkeypatch, calls)
        entries = run_main(session, self.SID, "/tmp")

        assert entries[-1]["skip_reason_a"] is None
        assert len(calls) == 2 and calls[1] == calls[0]

    def test_ceiling_applies_to_new_part(
        self, run_main, mock_from_responses, temp_vault, monkeypatch, session
    ):
        """A long resumed session isn't blocked by its own already-captured history."""
        import curate

        mock_from_responses("adr-worthy")
        run_main(session, self.SID, "/tmp")
        part = len(curate.render_transcript(curate._load_transcript(str(session))))
        self._resume(session)
        full = len(curate.render_transcript(curate._load_transcript(str(session))))
        monkeypatch.setenv("CAPTURE_MAX_EST_TOKENS", str((part + full) // 8))
        mock_from_responses("malformed-title")

        entries = run_main(session, self.SID, "/tmp")

        assert entries[-1]["skip_reason_a"] is None
        assert len(_notes(temp_vault)) == 2

    def test_same_day_same_slug_does_not_overwrite(
        self, run_main, mock_from_responses, temp_vault, session
    ):
        mock_from_responses("adr-worthy")
        run_main(session, self.SID, "/tmp")
        (first,) = _notes(temp_vault)
        first_bytes = first.read_bytes()
        self._resume(session)

        run_main(session, self.SID, "/tmp")

        notes = _notes(temp_vault)
        assert len(notes) == 2
        assert first.read_bytes() == first_bytes
        sid8 = self.SID[:8]
        expected = first.name.replace(f"-{sid8}.md", f"-2-{sid8}.md")
        assert {n.name for n in notes} == {first.name, expected}
        assert all(FILENAME_RE.match(n.name) for n in notes)


class TestCredentialGuards:
    """main() must exit 0 (no capture, no files) when the required credential is absent."""

    def test_api_mode_missing_key_exits(self, run_main, monkeypatch, temp_vault):
        monkeypatch.delenv("CAPTURE_MOCK_SDK", raising=False)
        monkeypatch.delenv("CAPTURE_USE_SUBSCRIPTION", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(SystemExit) as exc:
            run_main(_transcript("adr-worthy"), "nokey00112233aabb0010", "/tmp")
        assert exc.value.code == 0
        assert _no_files(temp_vault)
        assert not temp_vault.log_path.exists()

    def test_subscription_mode_missing_token_exits(
        self, run_main, monkeypatch, temp_vault
    ):
        monkeypatch.delenv("CAPTURE_MOCK_SDK", raising=False)
        monkeypatch.setenv("CAPTURE_USE_SUBSCRIPTION", "1")
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        with pytest.raises(SystemExit) as exc:
            run_main(_transcript("adr-worthy"), "notok00112233aabb0011", "/tmp")
        assert exc.value.code == 0
        assert _no_files(temp_vault)

    def test_missing_transcript_exits_gracefully(
        self, run_main, monkeypatch, temp_vault, tmp_path
    ):
        monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")
        missing = tmp_path / "does-not-exist.jsonl"
        with pytest.raises(SystemExit) as exc:
            run_main(missing, "gone00112233aabb0012", "/tmp")
        assert exc.value.code == 0
        assert _no_files(temp_vault)
        # The miss must still be logged (to the temp log, never the real one).
        entries = read_log(temp_vault.log_path)
        assert len(entries) == 1
        assert entries[0]["skip_reason_a"] == "transcript_missing"
        assert entries[0]["path_a"] is None
