import os
import sys
import pathlib
import tempfile
import time

# Ensure hooks/ is always on the path for all test modules
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))

# Keep scrub's malformed-rule logging off the real eval/state/scrub-failures.md;
# set at import so it is in place before any test module imports scrub.
_SESSION_FAILURES_PATH = str(
    pathlib.Path(tempfile.gettempdir()) / "cvc-test-scrub-failures.md"
)
os.environ.setdefault("SCRUB_FAILURES_PATH", _SESSION_FAILURES_PATH)

import json
from types import SimpleNamespace
import pytest
import yaml


def parse_frontmatter(text: str) -> dict:
    """Parse frontmatter via yaml.safe_load so tests fail when Obsidian would."""
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


def wait_for(path, timeout: float = 3.0) -> bool:
    """Poll until *path* exists (the hook backgrounds its worker)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture(autouse=True)
def _isolate_scrub_failures_path():
    """Reset SCRUB_FAILURES_PATH before each test; some tests override or pop it."""
    os.environ["SCRUB_FAILURES_PATH"] = _SESSION_FAILURES_PATH
    yield


# ── shared E2E scaffolding ──────────────────────────────────────────────────────

_MOCK_RESPONSES_PATH = (
    pathlib.Path(__file__).parent.parent / "eval" / "fixtures" / "mock-responses.json"
)


@pytest.fixture
def mock_from_responses(monkeypatch):
    """Factory: patch curate._call_path_a to replay mock-responses.json[name]["path_a"].

    A dict entry is returned as-is (usage included); null returns None.
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
    """Isolated vault + state paths (.vault_dir/.log_path/.index_path) for every test.

    curate's path globals point at a separate default-state dir, so a call site
    that drops an explicit path writes where no assertion looks and fails loudly.
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
    """Run curate.main() against temp_vault (main() only uses the path globals)."""
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
