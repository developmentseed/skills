"""Unit tests for Path A failure handling and token capture on error paths.

Single-path capture (Path B retired 2026-06-04): a Path A failure must be
caught, leave no file written, and log the skip_reason. Token/cost data must be
preserved even when JSON parsing fails or the model returns null.
Uses CAPTURE_MOCK_SDK=1 with a mock entry that raises.
"""

import sys
import pathlib
import json

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))


def _make_transcript(n_turns=3, chars=600) -> list[dict]:
    msgs = []
    for _ in range(n_turns):
        msgs.append({"role": "user", "content": "a" * chars})
        msgs.append({"role": "assistant", "content": "reply"})
    return msgs


def _run_with_mock_a(tmp_path, monkeypatch, mock_a, sid="test-session"):
    inbox_auto = tmp_path / "Inbox" / "auto"
    inbox_auto.mkdir(parents=True, exist_ok=True)
    log_file = tmp_path / "log.md"
    index_file = tmp_path / "session-index.tsv"

    monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")
    import curate

    monkeypatch.setattr(curate, "_call_path_a", mock_a)

    curate.run_capture(
        transcript=_make_transcript(),
        session_id=sid,
        cwd=str(tmp_path),
        vault_dir=str(tmp_path),
        log_path=log_file,
        index_path=index_file,
        date_str="2026-05-10",
    )
    log_lines = [line for line in log_file.read_text().splitlines() if line.strip()]
    return json.loads(log_lines[-1]), inbox_auto


class TestFailureHandling:
    def test_path_a_error_writes_no_file_and_logs(self, tmp_path, monkeypatch):
        """When Path A raises, no artifact is written and the error is logged."""
        entry, inbox_auto = _run_with_mock_a(
            tmp_path,
            monkeypatch,
            mock_a=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
            sid="test-a-error",
        )
        assert list(inbox_auto.glob("*.md")) == []
        assert entry["path_a"] is None
        assert entry["skip_reason_a"].startswith("error:")

    def test_path_a_success_writes_file(self, tmp_path, monkeypatch):
        """When Path A returns an artifact, it is written and logged clean."""
        entry, inbox_auto = _run_with_mock_a(
            tmp_path,
            monkeypatch,
            mock_a=lambda *a, **kw: {
                "title": "Decision: Use PostgreSQL",
                "type": "decision",
                "body": "We decided to use PostgreSQL because...",
                "source_links": [],
                "tags": ["backend"],
                "tokens_in": 200,
                "tokens_out": 100,
                "cost_usd": 0.01,
            },
            sid="test-a-success",
        )
        assert len(list(inbox_auto.glob("*.md"))) == 1
        assert entry["path_a"] is not None
        assert entry["skip_reason_a"] is None


class TestTokenCaptureOnFailure:
    """Tokens and cost must be logged even when JSON parsing fails or model returns null."""

    def test_model_returned_null_preserves_tokens(self, tmp_path, monkeypatch):
        """Path A returning null should still log token usage."""
        entry, _ = _run_with_mock_a(
            tmp_path,
            monkeypatch,
            mock_a=lambda *a, **kw: {
                "_null": True,
                "tokens_in": 1200,
                "tokens_out": 5,
                "cost_usd": 0.0036,
            },
            sid="test-null-tokens",
        )
        assert entry["skip_reason_a"] == "model_returned_null"
        assert entry["tokens_in_a"] == 1200
        assert entry["tokens_out_a"] == 5
        assert entry["cost_usd_a"] == 0.0036

    def test_malformed_json_preserves_tokens(self, tmp_path, monkeypatch):
        """Path A malformed_json should still log token usage via exc.usage."""

        def mock_a_malformed(*a, **kw):
            exc = json.JSONDecodeError("bad", "", 0)
            exc.usage = {"tokens_in": 800, "tokens_out": 60, "cost_usd": 0.0003}
            raise exc

        entry, _ = _run_with_mock_a(
            tmp_path, monkeypatch, mock_a=mock_a_malformed, sid="test-malformed-tokens"
        )
        assert entry["skip_reason_a"] == "malformed_json"
        assert entry["tokens_in_a"] == 800
        assert entry["tokens_out_a"] == 60
        assert entry["cost_usd_a"] == 0.0003

    def test_malformed_json_without_usage_attr(self, tmp_path, monkeypatch):
        """Graceful fallback when exc.usage is absent."""

        def mock_a_plain_error(*a, **kw):
            raise json.JSONDecodeError("bad", "", 0)

        entry, _ = _run_with_mock_a(
            tmp_path,
            monkeypatch,
            mock_a=mock_a_plain_error,
            sid="test-malformed-no-usage",
        )
        assert entry["skip_reason_a"] == "malformed_json"
        assert entry["tokens_in_a"] is None
        assert entry["cost_usd_a"] is None
