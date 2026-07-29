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


def test_malformed_json_is_retried_once_then_raises(monkeypatch):
    """Prose-instead-of-JSON is a non-deterministic generation failure, so it
    gets the same single retry a null gets. Before 2026-07-28 it raised on the
    first failure; 20 of 259 replies had been lost that way, several of which
    a re-sample would plausibly have recovered."""
    fake, calls = _seq(("not json", 100, 3), ("also not json", 90, 2))
    monkeypatch.setattr(curate, "_invoke_model", fake)

    with pytest.raises(json.JSONDecodeError) as exc:
        curate._call_path_a("scrubbed", PROMPTS)

    assert calls["n"] == 2  # retried exactly once, then gave up
    assert exc.value.usage["tokens_in"] == 190  # both attempts billed


def test_malformed_then_artifact_recovers(monkeypatch):
    """The point of the retry: a reply that continued the conversation on the
    first sample can come back as a clean artifact on the second."""
    artifact = json.dumps({"title": "T", "type": "gotcha", "body": "B"})
    fake, calls = _seq(("Sure — here's what I'd do next…", 100, 3), (artifact, 120, 40))
    monkeypatch.setattr(curate, "_invoke_model", fake)

    result = curate._call_path_a("scrubbed", PROMPTS)

    assert calls["n"] == 2
    assert result["title"] == "T"
    assert result["tokens_in"] == 220  # both attempts counted


def test_malformed_then_null_is_logged_as_malformed_not_null(monkeypatch):
    """A trailing null must not erase an unparseable reply from log.md: the
    malformed_json rate is the instrument this failure class is tracked by, and
    the resample budget is shared between the two classes."""
    fake, calls = _seq(("continuing the conversation…", 100, 3), ("null", 90, 2))
    monkeypatch.setattr(curate, "_invoke_model", fake)

    with pytest.raises(json.JSONDecodeError) as exc:
        curate._call_path_a("scrubbed", PROMPTS)

    assert calls["n"] == 2
    assert exc.value.usage["tokens_in"] == 190  # both attempts billed


def test_null_then_artifact_still_recovers_after_the_shared_budget_rename(monkeypatch):
    """The null contract is unchanged by sharing the budget with malformed."""
    artifact = json.dumps({"title": "T", "type": "gotcha", "body": "B"})
    fake, calls = _seq(("null", 100, 3), (artifact, 120, 40))
    monkeypatch.setattr(curate, "_invoke_model", fake)

    result = curate._call_path_a("scrubbed", PROMPTS)

    assert calls["n"] == 2
    assert result["title"] == "T"
    assert curate.PATH_A_RESAMPLES == 1


@pytest.mark.parametrize(
    "raw",
    ['"null"', "[1, 2]", "42"],
    ids=["quoted-null-string", "list", "number"],
)
def test_valid_but_non_object_json_is_malformed_with_usage(monkeypatch, raw):
    """Valid JSON of the wrong type parses fine, so it never reaches the
    JSONDecodeError branch — it once fell through to data.update() and died as
    an AttributeError, losing the token accounting with it. It now takes the
    same route as an unparseable reply: salvage, one resample, then
    malformed_json with both attempts billed."""
    fake, calls = _seq((raw, 100, 3), (raw, 90, 2))
    monkeypatch.setattr(curate, "_invoke_model", fake)

    with pytest.raises(json.JSONDecodeError) as exc:
        curate._call_path_a("scrubbed", PROMPTS)

    assert calls["n"] == 2
    assert exc.value.usage["tokens_in"] == 190
    assert exc.value.usage["tokens_out"] == 5


def test_non_object_then_artifact_recovers(monkeypatch):
    """The wrong-type reply gets the same second chance an unparseable one does."""
    artifact = json.dumps({"title": "T", "type": "spec", "body": "B"})
    fake, calls = _seq(("[1, 2]", 100, 3), (artifact, 120, 40))
    monkeypatch.setattr(curate, "_invoke_model", fake)

    result = curate._call_path_a("scrubbed", PROMPTS)

    assert calls["n"] == 2
    assert result["title"] == "T"
