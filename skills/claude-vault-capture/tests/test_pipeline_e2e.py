"""End-to-end tests for the full capture pipeline driven through curate.main().

These exercise the real argv → _load_transcript → run_capture → written vault
files → log → index flow with model calls replayed from mock-responses.json
(via the mock_from_responses fixture) or bespoke inline mocks. No network.

Companion to tests/test_failure_isolation.py, which owns the token-preservation
assertions on the error paths with inline mocks.
"""

import json
import pathlib
import re

import pytest

from conftest import parse_frontmatter

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
        assert fm_a["model"] == "claude-sonnet-4-6"

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
        """Post-API scrub: a secret in the model's returned body/title is redacted
        in the written file. The with-secrets mock body is already clean, so this
        needs a bespoke inline mock that returns a planted secret."""
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
        # EXCLUDED_COMMANDS is evaluated once at import (default empty), so setting
        # the env var here would not re-trigger it — patch the resolved constant.
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

    def test_duplicate_session(self, run_main, mock_from_responses, temp_vault):
        """Second capture of the same session_id writes nothing new and logs duplicate."""
        mock_from_responses("adr-worthy")
        sid = "dup00112233aabbccdd09"
        run_main(_transcript("adr-worthy"), sid, "/tmp")
        auto_after_first = list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))
        assert len(auto_after_first) == 1

        entries = run_main(_transcript("adr-worthy"), sid, "/tmp")
        # still exactly one file per path — no second artifact
        assert len(list((temp_vault.vault_dir / "Inbox" / "auto").glob("*.md"))) == 1
        assert entries[-1]["skip_reason_a"] == "duplicate"


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
        assert not temp_vault.log_path.exists()
