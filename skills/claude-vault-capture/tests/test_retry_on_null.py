"""Path A retry-on-null: the same transcript can null then yield an artifact.

These exercise the real curate._call_path_a (not the wholesale mock used by the
e2e suite) by monkeypatching the transport _invoke_model, so the retry loop and
its token accounting are covered directly.
"""

import json
import pathlib

import curate
import pytest

PROMPTS = pathlib.Path(__file__).parent.parent / "prompts"


def _seq(*returns):
    """Return a fake _invoke_model that yields the given (text, tin, tout) tuples."""
    calls = {"n": 0}

    def _fake(model, max_tokens, system_prompt, user_text):
        i = calls["n"]
        calls["n"] += 1
        return returns[i]

    return _fake, calls


def test_null_then_artifact_recovers_and_sums_tokens(monkeypatch):
    artifact = json.dumps({"title": "T", "type": "gotcha", "body": "B"})
    fake, calls = _seq(("null", 100, 3), (artifact, 120, 40))
    monkeypatch.setattr(curate, "_invoke_model", fake)

    result = curate._call_path_a("scrubbed", PROMPTS)

    assert calls["n"] == 2  # retried exactly once
    assert result.get("_null") is not True
    assert result["title"] == "T"
    assert result["tokens_in"] == 220  # 100 + 120, both attempts counted
    assert result["tokens_out"] == 43


def test_two_nulls_give_up_as_null_with_summed_tokens(monkeypatch):
    fake, calls = _seq(("null", 100, 3), ("null", 90, 2))
    monkeypatch.setattr(curate, "_invoke_model", fake)

    result = curate._call_path_a("scrubbed", PROMPTS)

    assert calls["n"] == 2  # one retry, then give up
    assert result["_null"] is True
    assert result["tokens_in"] == 190
    assert result["tokens_out"] == 5


def test_artifact_on_first_call_does_not_retry(monkeypatch):
    artifact = json.dumps({"title": "T", "type": "spec", "body": "B"})
    fake, calls = _seq((artifact, 120, 40))
    monkeypatch.setattr(curate, "_invoke_model", fake)

    result = curate._call_path_a("scrubbed", PROMPTS)

    assert calls["n"] == 1  # no retry when the first call already produced an artifact
    assert result["title"] == "T"


def test_malformed_json_is_not_retried(monkeypatch):
    fake, calls = _seq(("not json", 100, 3), ("also not json", 90, 2))
    monkeypatch.setattr(curate, "_invoke_model", fake)

    with pytest.raises(json.JSONDecodeError) as exc:
        curate._call_path_a("scrubbed", PROMPTS)

    assert calls["n"] == 1  # malformed raises immediately, no retry
    assert exc.value.usage["tokens_in"] == 100  # usage attached for cost logging
