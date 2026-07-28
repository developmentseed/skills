"""Tests for render_transcript — the enriched curator input builder.

render_transcript turns the loaded message list (each carrying raw content
`blocks`) into the text the curation model sees. Unlike the filters, which read
only the text-only `content`, this renderer surfaces tool activity: commands run
([TOOL]), command output heads ([OUT]), and failures ([ERROR]). A char budget
caps tool volume so the enriched input never blows the token guard.
"""

import curate
from curate import render_transcript


def _msg(role, content, blocks=None):
    return {"role": role, "content": content, "blocks": blocks}


class TestPlainText:
    def test_plain_string_messages_keep_role_prefixes(self):
        msgs = [_msg("user", "hi"), _msg("assistant", "yo")]
        assert render_transcript(msgs) == "[USER]: hi\n[ASSISTANT]: yo"

    def test_text_blocks_are_rendered_without_tool_noise(self):
        blocks = [{"type": "text", "text": "let me look"}]
        msgs = [_msg("assistant", "let me look", blocks)]
        assert render_transcript(msgs) == "[ASSISTANT]: let me look"


class TestToolUse:
    def test_bash_command_is_surfaced(self):
        blocks = [
            {"type": "text", "text": "running it"},
            {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -k foo"}},
        ]
        out = render_transcript([_msg("assistant", "running it", blocks)])
        assert "[ASSISTANT]: running it" in out
        assert "[TOOL] Bash: pytest -k foo" in out

    def test_bash_command_is_truncated_to_cap(self, monkeypatch):
        long_cmd = "echo " + "x" * 1000
        blocks = [{"type": "tool_use", "name": "Bash", "input": {"command": long_cmd}}]
        out = render_transcript([_msg("assistant", "", blocks)])
        # 300-char command cap → the rendered command is shorter than the input
        assert "x" * 300 not in out or len(out) < len(long_cmd)
        assert out.count("x") <= 300

    def test_edit_shows_file_and_diff(self):
        blocks = [
            {
                "type": "tool_use",
                "name": "Edit",
                "input": {
                    "file_path": "pyproject.toml",
                    "old_string": "requires-python = >=3.11",
                    "new_string": "requires-python = >=3.12",
                },
            }
        ]
        out = render_transcript([_msg("assistant", "", blocks)])
        assert "pyproject.toml" in out
        assert ">=3.11" in out
        assert ">=3.12" in out

    def test_other_tool_names_are_shown(self):
        blocks = [{"type": "tool_use", "name": "Read", "input": {"file_path": "a.py"}}]
        out = render_transcript([_msg("assistant", "", blocks)])
        assert "[TOOL] Read" in out
        assert "a.py" in out


class TestToolResults:
    def test_error_results_are_kept_in_full(self):
        blocks = [
            {
                "type": "tool_result",
                "is_error": True,
                "content": "TypeError: setup() got unexpected keyword 'worker'",
            }
        ]
        out = render_transcript([_msg("user", "", blocks)])
        assert "[ERROR]" in out
        assert "got unexpected keyword 'worker'" in out

    def test_success_results_keep_only_a_head(self):
        body = "line\n" * 500  # ~2500 chars
        blocks = [{"type": "tool_result", "content": body}]
        out = render_transcript([_msg("user", "", blocks)])
        assert "[OUT]" in out
        # default head is 200 chars — far less than the full body
        assert out.count("line") < 100

    def test_success_results_dropped_when_head_is_zero(self, monkeypatch):
        monkeypatch.setenv("CAPTURE_SUCCESS_HEAD_CHARS", "0")
        blocks = [{"type": "tool_result", "content": "some stdout"}]
        out = render_transcript([_msg("user", "", blocks)])
        assert "[OUT]" not in out
        assert "some stdout" not in out

    def test_tool_result_content_as_block_list(self):
        blocks = [
            {
                "type": "tool_result",
                "is_error": True,
                "content": [{"type": "text", "text": "boom failed"}],
            }
        ]
        out = render_transcript([_msg("user", "", blocks)])
        assert "boom failed" in out

    def test_image_only_result_emits_no_out_line(self):
        # A screenshot/image tool_result has no text content — it must not
        # inject a blank "[OUT] " marker line into the prompt.
        blocks = [
            {
                "type": "tool_result",
                "content": [{"type": "image", "source": {"data": "..."}}],
            }
        ]
        out = render_transcript([_msg("user", "", blocks)])
        assert "[OUT]" not in out

    def test_empty_error_result_emits_no_line(self):
        blocks = [{"type": "tool_result", "is_error": True, "content": "   "}]
        out = render_transcript([_msg("user", "", blocks)])
        assert "[ERROR]" not in out


class TestBudget:
    def test_budget_stops_tool_use_but_keeps_text_and_errors(self, monkeypatch):
        # Tiny budget: only the first tool line fits; later tool_use is dropped,
        # but assistant text and error results survive regardless.
        monkeypatch.setenv("CAPTURE_TOOL_CHARS_BUDGET", "30")
        blocks = [
            {"type": "text", "text": "narration stays"},
            {"type": "tool_use", "name": "Bash", "input": {"command": "first-cmd"}},
            {
                "type": "tool_use",
                "name": "Bash",
                "input": {"command": "second-cmd-dropped"},
            },
            {"type": "tool_result", "is_error": True, "content": "fatal error kept"},
        ]
        out = render_transcript([_msg("assistant", "narration stays", blocks)])
        assert "narration stays" in out
        assert "first-cmd" in out
        assert "second-cmd-dropped" not in out
        assert "fatal error kept" in out  # errors bypass the budget


class TestReachesCuratorScrubbed:
    """run_capture must feed the enriched text to the model, scrubbed."""

    def _transcript_with_secret(self):
        # >= 3 user turns and >= 1500 chars of user content to clear the threshold.
        pad = "I need help debugging this pipeline failure in detail. " * 12
        return [
            _msg("user", pad),
            _msg("user", pad),
            _msg("user", pad),
            _msg(
                "assistant",
                "running it",
                [
                    {"type": "text", "text": "running it"},
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {
                            "command": "export TOKEN=ghp_abc123DEADBEEF && deploy"
                        },
                    },
                ],
            ),
            _msg(
                "user",
                "",
                [
                    {
                        "type": "tool_result",
                        "is_error": True,
                        "content": "Exit code 1: boom",
                    }
                ],
            ),
        ]

    def test_enriched_text_reaches_model_with_secret_redacted(
        self, monkeypatch, tmp_path
    ):
        captured = {}

        def _spy(scrubbed_text, prompts_dir):
            captured["text"] = scrubbed_text
            return None  # model_returned_null → no file write needed

        monkeypatch.setattr(curate, "_call_path_a", _spy)

        curate.run_capture(
            transcript=self._transcript_with_secret(),
            session_id="sid-enrich",
            cwd=str(tmp_path),
            vault_dir=tmp_path / "vault",
            log_path=tmp_path / "log.md",
            index_path=tmp_path / "index.tsv",
            date_str="2026-06-06",
        )

        text = captured["text"]
        assert "[TOOL] Bash:" in text  # command surfaced
        assert "[ERROR] Exit code 1: boom" in text  # failure surfaced
        assert "ghp_abc123DEADBEEF" not in text  # secret scrubbed
        assert "<redacted:token_prefix>" in text
