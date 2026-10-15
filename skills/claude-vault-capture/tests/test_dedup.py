"""Unit tests for last_capture — session lookup against session-index.tsv."""

from curate import last_capture


def _index(tmp_path, *rows: str):
    index = tmp_path / "session-index.tsv"
    index.write_text("# schema_version: 3\n" + "".join(r + "\n" for r in rows))
    return index


class TestLastCapture:
    def test_v1_row_has_no_offset(self, tmp_path):
        index = _index(tmp_path, "abc-123\tInbox/auto/f.md\tInbox/raw/f.md\t2026-04-23")
        assert last_capture("abc-123", index_path=index) == (None, "Inbox/auto/f.md")

    def test_v2_row_has_no_offset(self, tmp_path):
        index = _index(tmp_path, "abc-123\tInbox/auto/f.md\t2026-09-01")
        assert last_capture("abc-123", index_path=index) == (None, "Inbox/auto/f.md")

    def test_v3_row_carries_the_offset(self, tmp_path):
        index = _index(tmp_path, "abc-123\tInbox/auto/f.md\t2026-10-15\t1234")
        assert last_capture("abc-123", index_path=index) == (1234, "Inbox/auto/f.md")

    def test_later_null_row_keeps_the_earlier_note(self, tmp_path):
        index = _index(
            tmp_path,
            "abc-123\tInbox/auto/f.md\t2026-10-15\t1234",
            "abc-123\tnull\t2026-10-16\t2000",
        )
        assert last_capture("abc-123", index_path=index) == (2000, "Inbox/auto/f.md")

    def test_out_of_order_rows_take_the_furthest_offset(self, tmp_path):
        index = _index(
            tmp_path,
            "abc-123\tnull\t2026-10-15\t2000",
            "abc-123\tnull\t2026-10-15\t1234",
        )
        assert last_capture("abc-123", index_path=index) == (2000, None)

    def test_any_legacy_row_means_no_offset(self, tmp_path):
        index = _index(
            tmp_path,
            "abc-123\tInbox/auto/f.md\t2026-09-01",
            "abc-123\tnull\t2026-10-15\t2000",
        )
        assert last_capture("abc-123", index_path=index) == (None, "Inbox/auto/f.md")

    def test_unknown_session_returns_none(self, tmp_path):
        index = _index(tmp_path, "other-id\tInbox/auto/f.md\t2026-10-15\t10")
        assert last_capture("new-id", index_path=index) is None

    def test_absent_index_returns_none(self, tmp_path):
        assert last_capture("any-id", index_path=tmp_path / "nonexistent.tsv") is None

    def test_comment_lines_skipped(self, tmp_path):
        index = tmp_path / "session-index.tsv"
        index.write_text("# schema_version: 1\n# another comment\n")
        assert last_capture("any-id", index_path=index) is None

    def test_exact_match_only(self, tmp_path):
        index = _index(tmp_path, "abc-1234\tnull\tnull\t2026-04-23")
        assert last_capture("abc-123", index_path=index) is None
        assert last_capture("abc-1234", index_path=index) == (None, None)
