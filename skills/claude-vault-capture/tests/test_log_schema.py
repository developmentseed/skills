"""Unit tests — each skip_reason variant produces a schema-valid JSON line.

Single-path schema (v2): Path B was retired 2026-06-04, so every entry has
exactly one path_a/skip_reason_a pair.
"""

import sys
import pathlib
import json

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))

from curate import build_log_entry, LOG_REQUIRED_KEYS


def _valid(entry: dict) -> bool:
    """Schema invariant: exactly one of path_a/skip_reason_a is non-null."""
    p = entry.get("path_a")
    s = entry.get("skip_reason_a")
    return (p is None) ^ (s is None)


class TestLogSchema:
    def test_happy_path(self):
        e = build_log_entry(
            session_id="s1",
            path_a="Inbox/auto/f.md",
            skip_reason_a=None,
            tokens_in_a=100,
            tokens_out_a=50,
            cost_usd_a=0.01,
            redactions={"env_var": 0},
        )
        assert e["schema_version"] == 2
        assert "timestamp" in e
        assert "date" in e
        assert _valid(e)
        assert all(k in e for k in LOG_REQUIRED_KEYS)

    def test_threshold_skip(self):
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a="threshold",
            tokens_in_a=None,
            tokens_out_a=None,
            cost_usd_a=None,
            redactions={},
        )
        assert _valid(e)
        assert e["skip_reason_a"] == "threshold"
        assert e["path_a"] is None

    def test_token_limit_skip(self):
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a="token_limit",
            tokens_in_a=None,
            tokens_out_a=None,
            cost_usd_a=None,
            redactions={},
        )
        assert _valid(e)
        assert e["skip_reason_a"] == "token_limit"

    def test_model_returned_null(self):
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a="model_returned_null",
            tokens_in_a=200,
            tokens_out_a=5,
            cost_usd_a=0.005,
            redactions={},
        )
        assert _valid(e)
        assert e["skip_reason_a"] == "model_returned_null"
        # token usage is preserved even on a null
        assert e["tokens_in_a"] == 200

    def test_timeout_skip(self):
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a="timeout",
            tokens_in_a=None,
            tokens_out_a=None,
            cost_usd_a=None,
            redactions={},
        )
        assert _valid(e)
        assert e["skip_reason_a"] == "timeout"

    def test_malformed_json_skip(self):
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a="malformed_json",
            tokens_in_a=200,
            tokens_out_a=0,
            cost_usd_a=0.0002,
            redactions={},
        )
        assert _valid(e)
        assert e["skip_reason_a"] == "malformed_json"

    def test_error_skip(self):
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a="error:RuntimeError",
            tokens_in_a=None,
            tokens_out_a=None,
            cost_usd_a=None,
            redactions={},
        )
        assert _valid(e)
        assert e["skip_reason_a"].startswith("error:")

    def test_duplicate_skip(self):
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a="duplicate",
            tokens_in_a=None,
            tokens_out_a=None,
            cost_usd_a=None,
            redactions={},
        )
        assert _valid(e)
        assert e["skip_reason_a"] == "duplicate"

    def test_invariant_never_both_null(self):
        """path_a and skip_reason_a cannot be null simultaneously."""
        e = build_log_entry(
            session_id="s1",
            path_a=None,
            skip_reason_a=None,  # INVALID — both null
            tokens_in_a=None,
            tokens_out_a=None,
            cost_usd_a=None,
            redactions={},
        )
        assert not _valid(e)

    def test_json_serializable(self):
        e = build_log_entry(
            session_id="s1",
            path_a="Inbox/auto/f.md",
            skip_reason_a=None,
            tokens_in_a=100,
            tokens_out_a=50,
            cost_usd_a=0.01,
            redactions={"env_var": 0},
        )
        line = json.dumps(e)
        parsed = json.loads(line)
        assert parsed["session_id"] == "s1"
