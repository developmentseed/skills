"""_invoke_via_subscription against a fake claude_agent_sdk: tools disabled, turn
headroom, salvage of text streamed before an error, and None usage when none arrived.
"""

import sys
import types
from dataclasses import dataclass, field

import pytest

import curate


@dataclass
class _TextBlock:
    text: str


@dataclass
class _AssistantMessage:
    content: list = field(default_factory=list)
    error: str | None = None


@dataclass
class _ResultMessage:
    usage: dict | None = None
    is_error: bool = False
    subtype: str = "success"
    result: str | None = None


class _CapturedOptions:
    """Records the last constructor kwargs; reset per test so none passes vacuously."""

    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        _CapturedOptions.last_kwargs = kwargs
        self.__dict__.update(kwargs)


def _install_fake_sdk(monkeypatch, messages, error=None):
    """Inject a claude_agent_sdk whose query() yields `messages`, then optionally raises."""
    monkeypatch.setattr(_CapturedOptions, "last_kwargs", {})

    async def query(*, prompt, options):
        for m in messages:
            yield m
        if error is not None:
            raise error

    fake = types.ModuleType("claude_agent_sdk")
    fake.query = query
    fake.ClaudeAgentOptions = _CapturedOptions
    fake.AssistantMessage = _AssistantMessage
    fake.TextBlock = _TextBlock
    fake.ResultMessage = _ResultMessage
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake)


def test_clean_run_returns_text_and_tokens(monkeypatch):
    _install_fake_sdk(
        monkeypatch,
        [
            _AssistantMessage(content=[_TextBlock('{"title": "x"}')]),
            _ResultMessage(
                usage={
                    "input_tokens": 10,
                    "cache_creation_input_tokens": 20,
                    "cache_read_input_tokens": 30,
                    "output_tokens": 7,
                }
            ),
        ],
    )
    text, tokens_in, tokens_out = curate._invoke_via_subscription(
        "claude-sonnet-5", "system", "transcript"
    )
    assert text == '{"title": "x"}'
    assert tokens_in == 60
    assert tokens_out == 7


def test_options_disable_tools_and_leave_turn_headroom(monkeypatch):
    """allowed_tools=[] only skips prompting; tools=[] is what removes the toolset."""
    _install_fake_sdk(monkeypatch, [_AssistantMessage(content=[_TextBlock("null")])])
    curate._invoke_via_subscription("claude-sonnet-5", "system", "transcript")
    assert _CapturedOptions.last_kwargs["tools"] == []
    assert _CapturedOptions.last_kwargs["allowed_tools"] == []
    assert _CapturedOptions.last_kwargs["max_turns"] > 1


def test_multi_turn_preamble_is_not_prepended_to_reply(monkeypatch):
    """Only the final message is the reply; a preamble would break exact `null`."""
    _install_fake_sdk(
        monkeypatch,
        [
            _AssistantMessage(content=[_TextBlock("Let me examine the transcript.")]),
            _AssistantMessage(content=[_TextBlock("null")]),
            _ResultMessage(usage={"input_tokens": 5, "output_tokens": 2}),
        ],
    )
    text, _, _ = curate._invoke_via_subscription(
        "claude-sonnet-5", "system", "transcript"
    )
    assert text == "null"


def test_error_after_streamed_reply_is_salvaged_with_unknown_usage(monkeypatch):
    _install_fake_sdk(
        monkeypatch,
        [
            _AssistantMessage(content=[_TextBlock("Looking at the session. ")]),
            _AssistantMessage(content=[_TextBlock('{"title": "kept"}')]),
        ],
        error=Exception(
            "Claude Code returned an error result: Reached maximum number of turns (4)"
        ),
    )
    text, tokens_in, tokens_out = curate._invoke_via_subscription(
        "claude-sonnet-5", "system", "transcript"
    )
    # On error the whole stream is kept (_salvage_artifact finds the JSON later);
    # usage that never arrived is None, not a fake 0.
    assert text == 'Looking at the session. {"title": "kept"}'
    assert tokens_in is None
    assert tokens_out is None


def test_error_before_any_reply_still_raises(monkeypatch):
    _install_fake_sdk(
        monkeypatch,
        [],
        error=Exception("Claude Code returned an error result: success"),
    )
    with pytest.raises(Exception, match="error result"):
        curate._invoke_via_subscription("claude-sonnet-5", "system", "transcript")


def test_run_is_isolated_like_api_mode(monkeypatch):
    """No user settings (else this plugin's own SessionEnd hook fires on the
    curation session), no thinking, and output capped like API mode."""
    _install_fake_sdk(monkeypatch, [_AssistantMessage(content=[_TextBlock("null")])])
    curate._invoke_via_subscription("claude-sonnet-5", "system", "transcript")
    kw = _CapturedOptions.last_kwargs
    assert kw["setting_sources"] == []
    assert kw["thinking"] == {"type": "disabled"}
    assert kw["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == str(curate.MAX_TOKENS_A)


def test_assistant_error_is_raised_not_parsed_as_a_reply(monkeypatch):
    login = _TextBlock("Invalid API key · Please run /login")
    _install_fake_sdk(
        monkeypatch,
        [_AssistantMessage(content=[login], error="authentication_failed")],
    )
    with pytest.raises(RuntimeError, match="authentication_failed"):
        curate._invoke_via_subscription("claude-sonnet-5", "system", "transcript")


def test_error_result_without_a_reply_raises(monkeypatch):
    failed = _ResultMessage(
        usage={}, is_error=True, subtype="error_during_execution", result="boom"
    )
    _install_fake_sdk(monkeypatch, [failed])
    with pytest.raises(RuntimeError, match="error_during_execution"):
        curate._invoke_via_subscription("claude-sonnet-5", "system", "transcript")


def test_returns_at_the_result_without_waiting_for_teardown(monkeypatch):
    _install_fake_sdk(
        monkeypatch,
        [
            _AssistantMessage(content=[_TextBlock("null")]),
            _ResultMessage(usage={"input_tokens": 5, "output_tokens": 2}),
            _AssistantMessage(content=[_TextBlock("late junk")]),
        ],
        error=Exception("teardown failure"),
    )
    text, tokens_in, tokens_out = curate._invoke_via_subscription(
        "claude-sonnet-5", "system", "transcript"
    )
    assert (text, tokens_in, tokens_out) == ("null", 5, 2)
