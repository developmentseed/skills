"""Tests for _load_transcript and _extract_text — covers list content blocks."""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))

from curate import _extract_text, _load_transcript


class TestExtractText:
    def test_string_passthrough(self):
        assert _extract_text("hello") == "hello"

    def test_empty_string(self):
        assert _extract_text("") == ""

    def test_list_of_text_blocks(self):
        content = [
            {"type": "text", "text": "first"},
            {"type": "text", "text": "second"},
        ]
        assert _extract_text(content) == "first\nsecond"

    def test_list_skips_non_text_blocks(self):
        content = [
            {"type": "text", "text": "hello"},
            {"type": "tool_use", "id": "tu_123", "name": "Bash", "input": {}},
            {"type": "tool_result", "content": "output"},
        ]
        assert _extract_text(content) == "hello"

    def test_list_with_raw_strings(self):
        assert _extract_text(["a", "b"]) == "a\nb"

    def test_list_filters_empty_parts(self):
        content = [
            {"type": "text", "text": ""},
            {"type": "text", "text": "keep"},
        ]
        assert _extract_text(content) == "keep"

    def test_non_string_non_list_returns_empty(self):
        assert _extract_text(None) == ""
        assert _extract_text(42) == ""


class TestLoadTranscript:
    def _write_jsonl(self, tmp_path, lines):
        p = tmp_path / "transcript.jsonl"
        p.write_text("\n".join(json.dumps(entry) for entry in lines) + "\n")
        return str(p)

    def test_plain_string_content(self, tmp_path):
        path = self._write_jsonl(
            tmp_path,
            [
                {"type": "user", "message": {"content": "hello"}},
                {"type": "assistant", "message": {"content": "world"}},
            ],
        )
        msgs = _load_transcript(path)
        assert msgs == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]

    def test_list_content_blocks(self, tmp_path):
        # This is the real-world case that was causing "sequence item 3: expected str"
        path = self._write_jsonl(
            tmp_path,
            [
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {"type": "text", "text": "run a command"},
                        ]
                    },
                },
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "sure"},
                            {
                                "type": "tool_use",
                                "id": "t1",
                                "name": "Bash",
                                "input": {"command": "ls"},
                            },
                        ]
                    },
                },
            ],
        )
        msgs = _load_transcript(path)
        assert msgs[0] == {"role": "user", "content": "run a command"}
        assert msgs[1] == {"role": "assistant", "content": "sure"}

    def test_skips_blank_lines_and_invalid_json(self, tmp_path):
        p = tmp_path / "transcript.jsonl"
        p.write_text(
            json.dumps({"type": "user", "message": {"content": "hi"}})
            + "\n"
            + "\n"
            + "not json\n"
            + json.dumps({"type": "assistant", "message": {"content": "hey"}})
            + "\n"
        )
        msgs = _load_transcript(str(p))
        assert len(msgs) == 2

    def test_role_field_fallback(self, tmp_path):
        path = self._write_jsonl(
            tmp_path,
            [
                {"role": "user", "content": "direct role"},
                {"role": "assistant", "content": "response"},
            ],
        )
        msgs = _load_transcript(path)
        assert msgs[0]["content"] == "direct role"
        assert msgs[1]["content"] == "response"

    def test_mixed_string_and_list_sessions(self, tmp_path):
        path = self._write_jsonl(
            tmp_path,
            [
                {"type": "user", "message": {"content": "plain string"}},
                {
                    "type": "user",
                    "message": {"content": [{"type": "text", "text": "list block"}]},
                },
            ],
        )
        msgs = _load_transcript(path)
        assert msgs[0]["content"] == "plain string"
        assert msgs[1]["content"] == "list block"
