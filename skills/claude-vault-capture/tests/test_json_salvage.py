"""Salvage valid JSON from decorated model output (subscription agentic leaks).

The subscription runtime sometimes echoes transcript delimiters or prefixes
prose around otherwise-valid JSON (observed in hooks.log 2026-06-16 → 2026-07-15:
`----- END TRANSCRIPT -----` echoes and `Human: ```json {…` fence lines that
defeat _CODE_FENCE_RE's line-start anchor). _call_path_a must extract the
outermost {...} object before declaring malformed_json — that JSON was already
paid for. Genuinely non-JSON output must still raise with usage attached.
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

    assert exc.value.usage["tokens_in"] == 100  # cost still logged on failure


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
