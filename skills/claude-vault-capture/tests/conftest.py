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
import yaml


def parse_frontmatter(text: str) -> dict:
    """Parse the frontmatter block with a real YAML parser.

    A hand-rolled partition-on-colon parser once masked a bug where rendered
    frontmatter was invalid YAML for any title containing ': ' — Obsidian
    rejected what the tests accepted. Parsing with yaml.safe_load means the
    suite fails exactly when Obsidian would. Values are coerced to str so
    existing string-equality assertions keep working; dates render ISO.
    """
    assert text.startswith("---\n")
    block = text.split("---\n", 2)[1]
    data = yaml.safe_load(block)
    assert isinstance(data, dict), f"frontmatter is not a YAML mapping: {block!r}"
    return {
        k: v if isinstance(v, (dict, list)) else ("null" if v is None else str(v))
        for k, v in data.items()
    }


def pytest_configure(config):
    """Register the `live` marker so the opt-in live E2E test doesn't warn."""
    config.addinivalue_line(
        "markers",
        "live: opt-in test that makes real model calls (CAPTURE_LIVE_TESTS=1).",
    )


def read_log(path) -> list[dict]:
    """Parse a JSON-lines log file into entry dicts; [] when the file is missing."""
    path = pathlib.Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


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


@pytest.fixture(autouse=True)
def temp_vault(tmp_path, monkeypatch):
    """Isolated vault layout + curate state paths for every test.

    Path defaults in curate.py resolve module globals at call time, so patching
    them here catches any call site that doesn't thread an explicit path — the
    transcript_missing logging in main() wrote 6 rows into the live W30
    eval/state/log.md exactly that way (session id gone00112233aabb0012).

    The globals are pointed at a default-state subtree DISTINCT from the
    returned explicit paths: a call site that silently drops an explicit path
    writes where no test assertion will accidentally find it, so the drop
    fails loudly instead of passing by coincidence. run_main re-points the
    globals at the explicit paths, because main() threads no path arguments
    and legitimately resolves the defaults.

    Returns .vault_dir/.log_path/.index_path for tests that assert on state.
    """
    import curate

    vault_dir = tmp_path / "vault"
    (vault_dir / "Inbox" / "auto").mkdir(parents=True)
    default_state = tmp_path / "default-state"
    monkeypatch.setattr(curate, "LOG_PATH", default_state / "log.md")
    monkeypatch.setattr(curate, "INDEX_PATH", default_state / "session-index.tsv")
    monkeypatch.setattr(curate, "VAULT_DIR", default_state / "vault")
    return SimpleNamespace(
        vault_dir=vault_dir,
        log_path=tmp_path / "log.md",
        index_path=tmp_path / "session-index.tsv",
    )


@pytest.fixture
def run_main(monkeypatch, temp_vault):
    """Invoke curate.main() against the temp vault, returning the parsed log entries.

    main() threads no path arguments — every write resolves the module
    globals — so point them at the temp_vault paths the tests assert on.
    """
    import curate

    monkeypatch.setattr(curate, "LOG_PATH", temp_vault.log_path)
    monkeypatch.setattr(curate, "INDEX_PATH", temp_vault.index_path)
    monkeypatch.setattr(curate, "VAULT_DIR", temp_vault.vault_dir)

    def _run(transcript_path, session_id, cwd):
        monkeypatch.setattr(
            sys, "argv", ["curate.py", str(transcript_path), session_id, cwd]
        )
        curate.main()
        return read_log(temp_vault.log_path)

    return _run
