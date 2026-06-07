"""Tests for _strip_fences and token capture on failure paths."""

import sys
import pathlib
import json

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))

from curate import _strip_fences


BT = "```"


class TestStripFences:
    def test_bare_json(self):
        assert json.loads(_strip_fences('{"k": "v"}')) == {"k": "v"}

    def test_fenced_json_lowercase(self):
        text = BT + 'json\n{"k": "v"}\n' + BT
        assert json.loads(_strip_fences(text)) == {"k": "v"}

    def test_fenced_json_uppercase(self):
        text = BT + 'JSON\n{"k": "v"}\n' + BT
        assert json.loads(_strip_fences(text)) == {"k": "v"}

    def test_fenced_no_language_tag(self):
        text = BT + '\n{"k": "v"}\n' + BT
        assert json.loads(_strip_fences(text)) == {"k": "v"}

    def test_text_before_fence(self):
        text = "Here is the result:\n" + BT + 'json\n{"k": "v"}\n' + BT
        assert json.loads(_strip_fences(text)) == {"k": "v"}

    def test_text_after_fence(self):
        text = BT + 'json\n{"k": "v"}\n' + BT + "\nHope this helps!"
        assert json.loads(_strip_fences(text)) == {"k": "v"}

    def test_text_both_sides(self):
        text = "Output:\n" + BT + 'json\n{"k": "v"}\n' + BT + "\nDone."
        assert json.loads(_strip_fences(text)) == {"k": "v"}

    def test_four_backticks(self):
        text = '````json\n{"k": "v"}\n````'
        assert json.loads(_strip_fences(text)) == {"k": "v"}

    def test_trailing_newline(self):
        text = BT + 'json\n{"k": "v"}\n' + BT + "\n"
        assert json.loads(_strip_fences(text)) == {"k": "v"}

    def test_multiline_json_in_fences(self):
        text = BT + 'json\n{\n  "title": "test",\n  "body": "hello"\n}\n' + BT
        data = json.loads(_strip_fences(text))
        assert data["title"] == "test"

    def test_no_fences_returns_input_unchanged(self):
        text = "not json at all"
        assert _strip_fences(text) == "not json at all"
