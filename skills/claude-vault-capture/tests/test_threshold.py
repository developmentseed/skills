"""Unit tests for the small-signal threshold check.

Threshold: < 3 user turns OR < 1500 chars of user content → skip (OR logic).
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))

from curate import is_below_threshold


def make_transcript(n_turns: int, chars_per_turn: int) -> list[dict]:
    """Return a minimal JSONL-style list of message dicts."""
    messages = []
    for i in range(n_turns):
        messages.append({"role": "user", "content": "a" * chars_per_turn})
        messages.append({"role": "assistant", "content": "reply"})
    return messages


class TestThreshold:
    def test_low_turns_normal_chars_skip(self):
        # < 3 turns, chars well above 1500
        msgs = make_transcript(2, 1000)  # 2 turns, 2000 chars total
        assert is_below_threshold(msgs) is True

    def test_normal_turns_low_chars_skip(self):
        # turns >= 3, but < 1500 chars
        msgs = make_transcript(3, 100)  # 3 turns, 300 chars total
        assert is_below_threshold(msgs) is True

    def test_both_low_skip(self):
        msgs = make_transcript(1, 10)
        assert is_below_threshold(msgs) is True

    def test_both_above_threshold_passes(self):
        # >= 3 turns AND >= 1500 chars
        msgs = make_transcript(3, 600)  # 3 turns, 1800 chars total
        assert is_below_threshold(msgs) is False

    def test_exact_boundary_turns(self):
        # exactly 3 turns, enough chars
        msgs = make_transcript(3, 600)
        assert is_below_threshold(msgs) is False

    def test_exact_boundary_chars(self):
        # enough turns, exactly 1500 chars (not < 1500)
        msgs = make_transcript(3, 500)  # 3 × 500 = 1500
        assert is_below_threshold(msgs) is False

    def test_one_char_below_chars(self):
        # enough turns, 1499 chars → skip
        msgs = make_transcript(3, 499)  # 3 × 499 = 1497
        assert is_below_threshold(msgs) is True

    def test_only_user_turns_counted(self):
        # assistant turns should not count
        msgs = [
            {"role": "user", "content": "a" * 600},
            {"role": "assistant", "content": "b" * 600},
            {"role": "user", "content": "a" * 600},
            {"role": "assistant", "content": "b" * 600},
            {"role": "user", "content": "a" * 600},
        ]
        assert is_below_threshold(msgs) is False
