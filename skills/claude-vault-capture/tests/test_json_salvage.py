"""_call_path_a salvages the last artifact-shaped object (string title/type/body)
from decorated output; anything else, including valid but unshaped JSON, is
malformed_json, since the write path would turn it into an empty "untitled" note.
"""

import json
import pathlib

import curate
import pytest

PROMPTS = pathlib.Path(__file__).parent.parent / "prompts"


def _single(text):
    """Fake _invoke_model returning *text* once with fixed usage."""

    def _fake(model, max_tokens, system_prompt, user_text):
        return (text, 100, 50)

    return _fake


def test_delimiter_echo_around_json_is_salvaged(monkeypatch):
    artifact = {"title": "T", "type": "gotcha", "body": "B"}
    text = "----- END TRANSCRIPT -----\n\n" + json.dumps(artifact)
    monkeypatch.setattr(curate, "_invoke_model", _single(text))

    result = curate._call_path_a("scrubbed", PROMPTS)

    assert result["title"] == "T"
    assert result["tokens_in"] == 100  # usage still accounted


def test_prose_on_fence_line_is_salvaged(monkeypatch):
    # Fence not at line start ("Human: ```json") defeats _CODE_FENCE_RE.
    artifact = {"title": "T2", "type": "spec", "body": "B"}
    text = "Human: ```json\n" + json.dumps(artifact) + "\n```"
    monkeypatch.setattr(curate, "_invoke_model", _single(text))

    result = curate._call_path_a("scrubbed", PROMPTS)

    assert result["title"] == "T2"


def test_pure_prose_still_malformed(monkeypatch):
    text = "Reviewed the session and wrote the fix as requested."
    monkeypatch.setattr(curate, "_invoke_model", _single(text))

    with pytest.raises(json.JSONDecodeError) as exc:
        curate._call_path_a("scrubbed", PROMPTS)

    # 2 x 100: unsalvageable output is retried once before giving up.
    assert exc.value.usage["tokens_in"] == 200  # cost still logged on failure


def test_prose_with_stray_braces_still_malformed(monkeypatch):
    # Braces present but no valid JSON — must not false-salvage.
    text = "I updated {the config} and then reran {the failing tests."
    monkeypatch.setattr(curate, "_invoke_model", _single(text))

    with pytest.raises(json.JSONDecodeError):
        curate._call_path_a("scrubbed", PROMPTS)


def test_salvaged_usage_none_propagates_as_unknown(monkeypatch):
    """usage=None must log as null, never an understated 0-token / $0 row."""
    artifact = {"title": "T", "type": "gotcha", "body": "B"}

    def _fake(model, max_tokens, system_prompt, user_text):
        return (json.dumps(artifact), None, None)

    monkeypatch.setattr(curate, "_invoke_model", _fake)

    result = curate._call_path_a("scrubbed", PROMPTS)

    assert result["title"] == "T"
    assert result["tokens_in"] is None
    assert result["tokens_out"] is None
    assert result["cost_usd"] is None


def test_subscription_directive_pins_output_contract():
    """Reply contract: one JSON object or `null`, never an echo of the transcript."""
    d = curate._SUBSCRIPTION_DIRECTIVE
    assert "null" in d.lower()
    assert "{" in d
    assert "echo" in d.lower() or "repeat" in d.lower()


class TestProductionFailureShapes:
    """Replies where the model continued the conversation instead of curating it."""

    def test_artifact_after_fabricated_tool_call_is_recovered(self, monkeypatch):
        artifact = {"title": "Recovered", "type": "runbook", "body": "steps"}
        text = (
            "[ASSISTANT]: \n"
            "[ASSISTANT]: I notice the session ended without my confirming it landed. "
            "Let me verify:\n"
            '[ASSISTANT]: [TOOL] Read: {"file_path": "/Users/x/.claude/projects", '
            '"limit": 10}\n'
            "[USER]: [OUT] ok\n\n" + json.dumps(artifact)
        )
        monkeypatch.setattr(curate, "_invoke_model", _single(text))

        result = curate._call_path_a("scrubbed", PROMPTS)

        assert result["title"] == "Recovered"
        assert result["type"] == "runbook"

    def test_fabricated_tool_call_alone_is_not_written_as_an_artifact(
        self, monkeypatch
    ):
        text = '[ASSISTANT]: [TOOL] Read: {"file_path": "/x", "limit": 10}'
        monkeypatch.setattr(curate, "_invoke_model", _single(text))

        with pytest.raises(json.JSONDecodeError):
            curate._call_path_a("scrubbed", PROMPTS)

    def test_continuation_prose_with_invalid_json_still_raises(self, monkeypatch):
        """Unescaped quotes in the body: must fail, not be silently repaired."""
        text = (
            "**You're done for today.** The session log is safe.\n\n"
            "----- END TRANSCRIPT -----\n\n"
            '{"title": "T", "type": "gotcha", '
            '"body": "counted "54 attempts against a budget of 8" — decomposed"}'
        )
        monkeypatch.setattr(curate, "_invoke_model", _single(text))

        with pytest.raises(json.JSONDecodeError):
            curate._call_path_a("scrubbed", PROMPTS)

    def test_transcript_tail_terminates_and_restates_the_contract(self):
        """Unterminated, the prompt reads as an unfinished conversation."""
        tail = curate._TRANSCRIPT_TAIL
        assert "END OF TRANSCRIPT" in tail
        assert "not a conversation to continue" in tail
        assert "null" in tail and "{" in tail

    def test_every_transport_gets_a_terminated_transcript(self, monkeypatch):
        """_invoke_model appends the tail before dispatch, covering both transports."""
        seen = {}

        def _capture(model, system_prompt, user_text):
            seen["text"] = user_text
            return ("null", 1, 1)

        monkeypatch.setattr(curate, "_invoke_via_subscription", _capture)
        monkeypatch.setattr(
            curate, "_invoke_via_api_key", lambda m, mt, sp, ut: _capture(m, sp, ut)
        )

        for subscription in ("1", "0"):
            seen.clear()
            monkeypatch.setenv("CAPTURE_USE_SUBSCRIPTION", subscription)
            curate._invoke_model("m", 100, "sys", "TRANSCRIPT BODY")
            assert seen["text"].endswith(curate._TRANSCRIPT_TAIL)
            assert seen["text"].startswith("TRANSCRIPT BODY")

    def test_unshaped_values_are_not_salvaged(self):
        """Key presence isn't enough: a non-string field would crash the write."""
        assert (
            curate._salvage_artifact('{"title": null, "type": "x", "body": "b"}')
            is None
        )
        assert (
            curate._salvage_artifact('{"title": 7, "type": "x", "body": "b"}') is None
        )
        assert (
            curate._salvage_artifact('prose {"title": "T", "type": "x", "body": "b"}')
            is not None
        )
