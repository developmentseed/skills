"""Salvage the artifact from decorated model output before declaring it malformed.

The runtime sometimes wraps otherwise-valid JSON in prose or transcript echoes
(observed in hooks.log 2026-06-16 → 2026-07-28: `----- END TRANSCRIPT -----`
echoes and `Human: ```json {…` fence lines that defeat _CODE_FENCE_RE's
line-start anchor). That JSON was already paid for, so _call_path_a scans every
`{` offset and keeps the LAST object carrying title/type/body as strings.

Anything else raises malformed_json — including a syntactically valid but
unshaped object, because the write path defaults every missing field and would
turn a mined `{"file_path": …}` into an empty "untitled" note in Inbox/.
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
    # Outermost {...} span exists but is not valid JSON — must not false-salvage.
    text = "I updated {the config} and then reran {the failing tests."
    monkeypatch.setattr(curate, "_invoke_model", _single(text))

    with pytest.raises(json.JSONDecodeError):
        curate._call_path_a("scrubbed", PROMPTS)


def test_salvaged_usage_none_propagates_as_unknown(monkeypatch):
    """A salvaged subscription reply carries usage=None; the artifact must log
    null (unknown), never an understated 0-token / $0 row."""
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
    """The directive must state the reply contract explicitly: a single JSON
    object or the word null, and never an echo of the transcript/delimiters —
    the observed W29 failure shapes."""
    d = curate._SUBSCRIPTION_DIRECTIVE
    assert "null" in d.lower()
    assert "{" in d
    assert "echo" in d.lower() or "repeat" in d.lower()


class TestProductionFailureShapes:
    """Regression tests built from the two replies that failed in production on
    2026-07-28 (sessions e4cf3de6…, eddf176a…). Both were the model continuing
    the captured conversation instead of curating it — see _TRANSCRIPT_TAIL.
    """

    def test_artifact_after_fabricated_tool_call_is_recovered(self, monkeypatch):
        """The reply opened with a fabricated `[TOOL] Read: {...}` line and
        ended with a complete artifact. The old find('{')..rfind('}') window
        started inside the tool-call brace and destroyed a valid, paid-for
        artifact; the raw_decode scan recovers it."""
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
        """A JSON-shaped object that isn't an artifact must NOT be salvaged: the
        write path defaults every missing field, so this used to land in Inbox/
        as an empty 'untitled' note."""
        text = '[ASSISTANT]: [TOOL] Read: {"file_path": "/x", "limit": 10}'
        monkeypatch.setattr(curate, "_invoke_model", _single(text))

        with pytest.raises(json.JSONDecodeError):
            curate._call_path_a("scrubbed", PROMPTS)

    def test_continuation_prose_with_invalid_json_still_raises(self, monkeypatch):
        """Failure 2's shape: next-turn prose, an invented END TRANSCRIPT
        delimiter, then JSON whose body contains unescaped quotes. Genuinely
        unparseable — it must fail rather than be silently repaired."""
        text = (
            "**Loïc, you're done for today.** The session log is safe.\n\n"
            "----- END TRANSCRIPT -----\n\n"
            '{"title": "T", "type": "gotcha", '
            '"body": "counted "54 attempts against a budget of 8" — decomposed"}'
        )
        monkeypatch.setattr(curate, "_invoke_model", _single(text))

        with pytest.raises(json.JSONDecodeError):
            curate._call_path_a("scrubbed", PROMPTS)

    def test_transcript_tail_terminates_and_restates_the_contract(self):
        """The tail is the root-cause fix: without a closing delimiter and a
        trailing instruction, the prompt reads as an unfinished conversation."""
        tail = curate._TRANSCRIPT_TAIL
        assert "END OF TRANSCRIPT" in tail
        assert "not a conversation to continue" in tail
        assert "null" in tail and "{" in tail

    def test_every_transport_gets_a_terminated_transcript(self, monkeypatch):
        """Layer 4: the API-key path had the same unterminated-transcript gap,
        masked only because subscription mode is what runs in production.
        _invoke_model appends the tail before dispatch, so neither transport can
        ship an unterminated transcript — enforced by construction, not by each
        transport remembering to do it."""
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
        """Key presence isn't enough: the write path assumes strings for the
        fields that are present, so a mined object with a null title would raise
        mid-write and take the log append down with it."""
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
