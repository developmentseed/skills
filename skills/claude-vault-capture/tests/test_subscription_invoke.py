"""Regression tests for _invoke_via_subscription against a fake claude_agent_sdk.

W30 lost 4 paid responses to the SDK surfacing the CLI's error result as an
exception: 3x "Reached maximum number of turns (1)" and 1x a non-zero exit
whose result text was literally "success". These pin the mitigations:
tools=[] (allowed_tools=[] only skips permission prompting — it does not
remove the built-in toolset, and tool attempts are what burned the turns),
a max_turns buffer > 1, salvaging reply text that streamed before the error,
and None (not 0) token counts when usage never arrived.
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


@dataclass
class _ResultMessage:
    usage: dict | None = None


class _CapturedOptions:
    """Records the most recent construction's kwargs in `last_kwargs`.

    _install_fake_sdk resets it so a test can never read a previous test's
    capture and pass vacuously.
    """

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
        "claude-sonnet-4-6", "system", "transcript"
    )
    assert text == '{"title": "x"}'
    assert tokens_in == 60
    assert tokens_out == 7


def test_options_disable_tools_and_leave_turn_headroom(monkeypatch):
    """tools=[] removes the built-in toolset (the root cause: tool attempts
    burned the only turn); max_turns > 1 keeps headroom if one is burned anyway."""
    _install_fake_sdk(monkeypatch, [_AssistantMessage(content=[_TextBlock("null")])])
    curate._invoke_via_subscription("claude-sonnet-4-6", "system", "transcript")
    assert _CapturedOptions.last_kwargs["tools"] == []
    assert _CapturedOptions.last_kwargs["allowed_tools"] == []
    assert _CapturedOptions.last_kwargs["max_turns"] > 1


def test_multi_turn_preamble_is_not_prepended_to_reply(monkeypatch):
    """Only the final assistant message is the reply: concatenating an early
    turn's preamble would turn an exact-match `null` into malformed_json."""
    _install_fake_sdk(
        monkeypatch,
        [
            _AssistantMessage(content=[_TextBlock("Let me examine the transcript.")]),
            _AssistantMessage(content=[_TextBlock("null")]),
            _ResultMessage(usage={"input_tokens": 5, "output_tokens": 2}),
        ],
    )
    text, _, _ = curate._invoke_via_subscription(
        "claude-sonnet-4-6", "system", "transcript"
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
        "claude-sonnet-4-6", "system", "transcript"
    )
    # Salvage keeps the whole stream (the downstream outermost-brace salvage
    # extracts the JSON), and usage that never arrived is None, not a fake 0.
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
        curate._invoke_via_subscription("claude-sonnet-4-6", "system", "transcript")
