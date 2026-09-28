"""Opt-in live E2E (CAPTURE_LIVE_TESTS=1): real subscription calls that SPEND MAX
QUOTA and need a logged-in `claude` CLI (CLAUDE_CODE_OAUTH_TOKEN or
~/.claude_vault_oauth_token).
"""

import os
import pathlib

import pytest

from conftest import parse_frontmatter, read_log

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
    (vault_dir / "Inbox" / "auto").mkdir(parents=True, exist_ok=True)
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

    entry = read_log(log_path)[-1]
    assert entry["skip_reason_a"] is None
    # cache-token summation guard: subscription usage must be populated, non-trivial
    assert entry["tokens_in_a"] and entry["tokens_in_a"] > 100
    assert entry["tokens_out_a"] and entry["tokens_out_a"] > 0
