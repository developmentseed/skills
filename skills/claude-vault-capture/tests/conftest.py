import os
import sys
import pathlib
import tempfile

# Ensure hooks/ is always on the path for all test modules
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))

# Redirect scrub failure logging away from the real eval/state/scrub-failures.md
# for the entire test session. scrub.py compiles its rules at import time and
# logs any re.error to SCRUB_FAILURES_PATH (falling back to the real file when
# unset), so tests that inject a malformed rule and reload the module would
# otherwise pollute the live failures log. Set this at conftest import time so
# it is in place before any test module imports scrub.
_SESSION_FAILURES_PATH = str(
    pathlib.Path(tempfile.gettempdir()) / "cvc-test-scrub-failures.md"
)
os.environ.setdefault("SCRUB_FAILURES_PATH", _SESSION_FAILURES_PATH)

import json
from types import SimpleNamespace
import pytest


def parse_frontmatter(text: str) -> dict:
    """Read a flat-scalar YAML frontmatter block into a dict.

    Good enough for the scalar fields the artifacts emit (title, source, type,
    session_id, model, …). Shared by the e2e and live test modules.
    """
    assert text.startswith("---\n")
    block = text.split("---\n", 2)[1]
    fm = {}
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def pytest_configure(config):
    """Register the `live` marker so the opt-in live E2E test doesn't warn."""
    config.addinivalue_line(
        "markers",
        "live: opt-in test that makes real model calls (CAPTURE_LIVE_TESTS=1).",
    )


@pytest.fixture(autouse=True)
def _isolate_scrub_failures_path():
    """Re-establish the temp failures path before each test.

    Individual tests may override SCRUB_FAILURES_PATH (e.g. to assert on a
    tmp_path file) and some pop it in teardown; this guarantees the real
    eval/state/scrub-failures.md is never the target between tests.
    """
    os.environ["SCRUB_FAILURES_PATH"] = _SESSION_FAILURES_PATH
    yield


# ── shared E2E scaffolding ──────────────────────────────────────────────────────

_MOCK_RESPONSES_PATH = (
    pathlib.Path(__file__).parent.parent / "eval" / "fixtures" / "mock-responses.json"
)


@pytest.fixture
def mock_from_responses(monkeypatch):
    """Factory: given a mock-responses.json key, monkeypatch the curation call.

    Loads eval/fixtures/mock-responses.json[name] and patches curate._call_path_a
    to replay the recorded artifact (Path B was retired 2026-06-04, so only the
    path_a entry is used):

      - dict entry      → returned as-is (entries already carry tokens_in/out +
                          cost_usd — they are NOT backfilled).
      - null for path_a → returns None (run_capture maps to model_returned_null;
                          a null has no usage data, so none is synthesized).

    This is the fixture-driven sibling of the inline-mock pattern in
    tests/test_failure_isolation.py. Use this when replaying the recorded
    mock-responses.json artifacts; use the inline pattern when a test needs a
    bespoke mock (e.g. a secret in the body, or exc.usage assertions).
    """
    import curate

    responses = json.loads(_MOCK_RESPONSES_PATH.read_text())

    def _install(name: str):
        entry = responses[name]
        monkeypatch.setenv("CAPTURE_MOCK_SDK", "1")

        a = entry["path_a"]

        def _mock_a(*args, **kwargs):
            if a is None:
                return None
            return dict(a)

        monkeypatch.setattr(curate, "_call_path_a", _mock_a)
        return entry

    return _install


@pytest.fixture
def temp_vault(tmp_path):
    """Create an isolated vault layout under tmp_path; return its paths.

    Returns an object with .vault_dir, .log_path, .index_path attributes.
    """
    vault_dir = tmp_path / "vault"
    (vault_dir / "Inbox" / "auto").mkdir(parents=True)

    return SimpleNamespace(
        vault_dir=vault_dir,
        log_path=tmp_path / "log.md",
        index_path=tmp_path / "session-index.tsv",
    )


@pytest.fixture
def run_main(monkeypatch, temp_vault):
    """Invoke curate.main() against the temp vault, returning the parsed log entries.

    main() takes no vault/log/index arguments — its run_capture call uses the
    module-level defaults (VAULT_DIR resolves CAPTURE_VAULT_DIR, else ~/Obsidian).
    We therefore wrap run_capture (rather than patch the module constant) so the
    temp paths are injected: main() resolves run_capture as a module global at
    call time, so the wrapper is picked up.
    """
    import curate

    real_run_capture = curate.run_capture

    def _wrapped(**kwargs):
        kwargs.setdefault("vault_dir", str(temp_vault.vault_dir))
        kwargs.setdefault("log_path", temp_vault.log_path)
        kwargs.setdefault("index_path", temp_vault.index_path)
        return real_run_capture(**kwargs)

    monkeypatch.setattr(curate, "run_capture", _wrapped)

    def _run(transcript_path, session_id, cwd):
        monkeypatch.setattr(
            sys, "argv", ["curate.py", str(transcript_path), session_id, cwd]
        )
        curate.main()
        if not temp_vault.log_path.exists():
            return []
        return [
            json.loads(line)
            for line in temp_vault.log_path.read_text().splitlines()
            if line.strip()
        ]

    return _run
