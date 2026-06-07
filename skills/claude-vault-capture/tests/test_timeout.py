"""Timeout handling for the metered API-key transport.

Regression coverage for a real bug: anthropic.APITimeoutError is not a subclass
of the builtin TimeoutError, so run_capture's `except TimeoutError` never caught
it and a timed-out call was mislabeled `error:APITimeoutError` instead of the
documented `timeout` skip reason. _invoke_via_api_key now normalizes it.
"""

import json

import anthropic
import httpx
import pytest

import curate


def _timeout_client(*args, **kwargs):
    """Stand-in anthropic.Anthropic whose .messages.create always times out."""

    class _Msgs:
        def create(self, **_):
            raise anthropic.APITimeoutError(
                request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            )

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Msgs()

    return _Client(*args, **kwargs)


def _above_threshold_transcript():
    """>= 3 user turns and >= 1500 chars of user content, to clear the guards."""
    return [
        {"role": "user", "content": "a" * 600},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "b" * 600},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "c" * 600},
    ]


def test_api_timeout_normalized_to_builtin(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", _timeout_client)
    with pytest.raises(TimeoutError):
        curate._invoke_via_api_key("claude-test", 100, "system", "user text")


def test_run_capture_maps_api_timeout_to_skip_reason(monkeypatch, temp_vault):
    monkeypatch.delenv("CAPTURE_MOCK_SDK", raising=False)
    monkeypatch.delenv("CAPTURE_USE_SUBSCRIPTION", raising=False)
    monkeypatch.setattr(anthropic, "Anthropic", _timeout_client)

    curate.run_capture(
        transcript=_above_threshold_transcript(),
        session_id="sess-timeout",
        cwd="/tmp/proj",
        vault_dir=str(temp_vault.vault_dir),
        log_path=temp_vault.log_path,
        index_path=temp_vault.index_path,
    )

    entries = [
        json.loads(line)
        for line in temp_vault.log_path.read_text().splitlines()
        if line.strip()
    ]
    assert len(entries) == 1
    assert entries[0]["skip_reason_a"] == "timeout"
