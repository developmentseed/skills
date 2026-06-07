"""Opt-in live E2E test for the real subscription pipeline.

SKIPPED BY DEFAULT. Enable with CAPTURE_LIVE_TESTS=1. This makes real model
calls through the Claude Code runtime (CAPTURE_USE_SUBSCRIPTION=1), so it SPENDS
MAX SUBSCRIPTION QUOTA and requires the `claude` CLI to be logged in
(`claude setup-token` → CLAUDE_CODE_OAUTH_TOKEN, or ~/.claude_vault_oauth_token).

It runs a decision-worthy transcript through the full pipeline into a temp vault
and verifies the artifact lands under tmp_path (never ~/Obsidian), carries valid
frontmatter, skips cleanly (skip_reason_a is null), and reports non-trivial token
usage — a regression guard for the cache-token summation in
_invoke_via_subscription.
"""

import json
import os
import pathlib

import pytest

from conftest import parse_frontmatter

TRANSCRIPTS = pathlib.Path(__file__).parent.parent / "eval" / "fixtures" / "transcripts"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("CAPTURE_LIVE_TESTS") != "1",
        reason="live test — set CAPTURE_LIVE_TESTS=1 to run (spends Max quota)",
    ),
]


def test_subscription_pipeline_writes_artifact(tmp_path, monkeypatch):
    import curate

    monkeypatch.setenv("CAPTURE_USE_SUBSCRIPTION", "1")
    monkeypatch.delenv("CAPTURE_MOCK_SDK", raising=False)

    vault_dir = tmp_path / "vault"
    (vault_dir / "Inbox" / "auto").mkdir(parents=True)
    log_path = tmp_path / "log.md"
    index_path = tmp_path / "session-index.tsv"

    transcript = curate._load_transcript(str(TRANSCRIPTS / "adr-worthy.jsonl"))
    curate.run_capture(
        transcript=transcript,
        session_id="live-e2e-deadbeef0001",
        cwd=str(tmp_path),
        vault_dir=str(vault_dir),
        log_path=log_path,
        index_path=index_path,
    )

    auto = list((vault_dir / "Inbox" / "auto").glob("*.md"))
    assert len(auto) == 1, "Path A (decision) should have written one artifact"

    # never escaped into the real vault
    assert (
        not (pathlib.Path.home() / "Obsidian")
        .joinpath("loics_vault", "Inbox", "auto", auto[0].name)
        .exists()
    )

    fm_a = parse_frontmatter(auto[0].read_text())
    assert fm_a["source"] == "claude-code-curated"

    entry = json.loads(
        [line for line in log_path.read_text().splitlines() if line.strip()][-1]
    )
    assert entry["skip_reason_a"] is None
    # cache-token summation guard: subscription usage must be populated, non-trivial
    assert entry["tokens_in_a"] and entry["tokens_in_a"] > 100
    assert entry["tokens_out_a"] and entry["tokens_out_a"] > 0
