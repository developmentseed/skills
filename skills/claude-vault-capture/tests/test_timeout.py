"""Timeout handling for the API-key transport: anthropic.APITimeoutError is not a
builtin TimeoutError, so _invoke_via_api_key must normalize it to the `timeout` skip.
"""

import importlib
from types import SimpleNamespace

import anthropic
import httpx
import pytest

import curate
from conftest import read_log


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


def test_timeout_seconds_defaults_to_30(monkeypatch):
    monkeypatch.delenv("CAPTURE_TIMEOUT_SECONDS", raising=False)
    try:
        importlib.reload(curate)
        assert curate.TIMEOUT_SECONDS == 30
    finally:
        importlib.reload(curate)


def test_timeout_seconds_env_override(monkeypatch):
    monkeypatch.setenv("CAPTURE_TIMEOUT_SECONDS", "90")
    try:
        importlib.reload(curate)
        assert curate.TIMEOUT_SECONDS == 90
    finally:
        # Restore the module to default-env state for the rest of the session.
        monkeypatch.delenv("CAPTURE_TIMEOUT_SECONDS", raising=False)
        importlib.reload(curate)


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

    entries = read_log(temp_vault.log_path)
    assert len(entries) == 1
    assert entries[0]["skip_reason_a"] == "timeout"


class TestSonnet55RequestShape:
    """Sonnet 5.5 rejects disabled thinking; adaptive thinking would share max_tokens
    with the reply and truncate the JSON into malformed_json."""

    def _capture_kwargs(self, monkeypatch):
        seen = {}

        class _Messages:
            def create(self, **kwargs):
                seen.update(kwargs)
                raise RuntimeError("stop after capturing kwargs")

        class _Client:
            def __init__(self, *a, **kw):
                self.messages = _Messages()

        monkeypatch.setattr(anthropic, "Anthropic", _Client)
        try:
            curate._invoke_via_api_key(
                curate.MODEL_A, curate.MAX_TOKENS_A, "sys", "text"
            )
        except RuntimeError:
            pass
        return seen

    def test_up_front_thinking_is_off(self, monkeypatch):
        kwargs = self._capture_kwargs(monkeypatch)
        assert kwargs.get("thinking") == {"type": "between_tools"}

    def test_effort_is_low(self, monkeypatch):
        # between_tools is only accepted at effort low/medium/high.
        kwargs = self._capture_kwargs(monkeypatch)
        assert kwargs.get("output_config") == {"effort": "low"}

    def test_no_removed_sampling_params(self, monkeypatch):
        # temperature / top_p / top_k are rejected with a 400 on Sonnet 5.5.
        kwargs = self._capture_kwargs(monkeypatch)
        assert not {"temperature", "top_p", "top_k"} & set(kwargs)

    def test_output_budget_has_headroom_for_the_new_tokenizer(self, monkeypatch):
        assert curate.MAX_TOKENS_A >= 2600  # ~30% above the Sonnet 4.6 budget of 2000

    def test_cost_estimate_uses_sonnet55_list_price(self):
        assert curate._estimate_cost_a(1_000_000, 1_000_000) == 12.0  # $2 in + $10 out


def _api_reply(monkeypatch, stop_reason, content):
    class _Messages:
        def create(self, **kwargs):
            usage = SimpleNamespace(input_tokens=100, output_tokens=7)
            return SimpleNamespace(
                stop_reason=stop_reason, content=content, usage=usage
            )

    class _Client:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    monkeypatch.setattr(anthropic, "Anthropic", _Client)


@pytest.mark.parametrize(
    "stop_reason, reason", [("refusal", "refusal"), ("max_tokens", "truncated")]
)
def test_unusable_stop_reason_raises_reply_error(monkeypatch, stop_reason, reason):
    _api_reply(monkeypatch, stop_reason, [])
    with pytest.raises(curate.ReplyError) as exc:
        curate._invoke_via_api_key("m", 10, "sys", "text")
    assert exc.value.reason == reason
    assert exc.value.tokens_in == 100


def test_reply_text_is_joined_from_text_blocks(monkeypatch):
    _api_reply(monkeypatch, "end_turn", [SimpleNamespace(type="text", text=" null ")])
    assert curate._invoke_via_api_key("m", 10, "sys", "text") == ("null", 100, 7)


def test_junk_timeout_setting_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CAPTURE_TIMEOUT_SECONDS", "2 minutes")
    try:
        importlib.reload(curate)
        assert curate.TIMEOUT_SECONDS == 30
    finally:
        monkeypatch.delenv("CAPTURE_TIMEOUT_SECONDS", raising=False)
        importlib.reload(curate)


def test_api_client_keeps_the_sdk_retries(monkeypatch):
    """Retries rescue a transient 529 that would otherwise lose the capture."""
    seen = {}

    class _Client:
        def __init__(self, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop after construction")

    monkeypatch.setattr(anthropic, "Anthropic", _Client)
    with pytest.raises(RuntimeError):
        curate._invoke_via_api_key("m", 10, "sys", "text")
    assert seen["max_retries"] == 2
