"""Unit tests for dedup — session_id lookup against session-index.tsv."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))

from curate import is_duplicate_session


class TestDedupLookup:
    def test_known_session_returns_true(self, tmp_path):
        index = tmp_path / "session-index.tsv"
        index.write_text(
            "# schema_version: 1\n"
            "abc-123\tInbox/auto/f.md\tInbox/raw/f.md\t2026-04-23\n"
        )
        assert is_duplicate_session("abc-123", index_path=index) is True

    def test_unknown_session_returns_false(self, tmp_path):
        index = tmp_path / "session-index.tsv"
        index.write_text(
            "# schema_version: 1\n"
            "other-id\tInbox/auto/f.md\tInbox/raw/f.md\t2026-04-23\n"
        )
        assert is_duplicate_session("new-id", index_path=index) is False

    def test_absent_index_returns_false(self, tmp_path):
        index = tmp_path / "nonexistent.tsv"
        assert is_duplicate_session("any-id", index_path=index) is False

    def test_comment_lines_skipped(self, tmp_path):
        index = tmp_path / "session-index.tsv"
        index.write_text("# schema_version: 1\n# another comment\n")
        assert is_duplicate_session("any-id", index_path=index) is False

    def test_exact_match_only(self, tmp_path):
        index = tmp_path / "session-index.tsv"
        index.write_text("# schema_version: 1\nabc-1234\tnull\tnull\t2026-04-23\n")
        assert is_duplicate_session("abc-123", index_path=index) is False
        assert is_duplicate_session("abc-1234", index_path=index) is True
