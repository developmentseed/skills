"""Subprocess tests for hooks/session-end-capture.sh.

Hermetic: a temp HOME holds a stub curate.py and an executable python3 shim that
the hook backgrounds. The shim records its argv and a fixed whitelist of env vars
to an invocation file, so we can assert what the hook passed without ever running
the real worker or touching a real credential.

Security: the shim records only CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY /
CAPTURE_USE_SUBSCRIPTION, and every token file written here holds a DUMMY value,
so no ambient real key is ever persisted. temp HOME is cleaned up by tmp_path.
"""

import json
import os
import pathlib
import shutil
import subprocess
import time


HOOK = pathlib.Path(__file__).parent.parent / "hooks" / "session-end-capture.sh"


def _build_home(home: pathlib.Path, *, configure_vault: bool = True) -> pathlib.Path:
    """Lay out a fake repo + temp HOME for the hook; return the invocation-record path.

    The hook self-locates via ${BASH_SOURCE[0]}, so the test runs a *copy* of the
    real hook placed inside the temp repo. That makes CURATE / VENV_PYTHON resolve
    to the stub curate.py and python3 shim laid down here. A capture.env supplying
    CAPTURE_VAULT_DIR is written by default so the hook's config guard passes;
    configure_vault=False exercises the unconfigured path.
    """
    repo = home / "DevDS" / "claude-vault-capture"
    (repo / "hooks").mkdir(parents=True)
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / "hooks" / "curate.py").write_text("# stub — never executed by the shim\n")
    shutil.copy(HOOK, repo / "hooks" / "session-end-capture.sh")

    if configure_vault:
        (repo / "capture.env").write_text(f'CAPTURE_VAULT_DIR="{home / "vault"}"\n')

    invocation = home / "curate-invocation.txt"
    shim = repo / ".venv" / "bin" / "python3"
    # The shim stands in for the venv interpreter. It records argv + a fixed
    # whitelist of env vars, then exits 0. Invocation path is baked in here.
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'INV="{invocation}"\n'
        'printf "ARGV:%s\\n" "$*" > "$INV"\n'
        'printf "CLAUDE_CODE_OAUTH_TOKEN=%s\\n" "${CLAUDE_CODE_OAUTH_TOKEN:-}" >> "$INV"\n'
        'printf "ANTHROPIC_API_KEY=%s\\n" "${ANTHROPIC_API_KEY:-}" >> "$INV"\n'
        'printf "CAPTURE_USE_SUBSCRIPTION=%s\\n" "${CAPTURE_USE_SUBSCRIPTION:-}" >> "$INV"\n'
        "exit 0\n"
    )
    shim.chmod(0o755)
    return invocation


def _run_hook(home: pathlib.Path, stdin: str, extra_env: dict | None = None):
    """Run the hook with a clean env + temp HOME; return (CompletedProcess, seconds)."""
    env = {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", ""),
    }
    if extra_env:
        env.update(extra_env)
    hook_copy = (
        home / "DevDS" / "claude-vault-capture" / "hooks" / "session-end-capture.sh"
    )
    start = time.monotonic()
    proc = subprocess.run(
        ["bash", str(hook_copy)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    return proc, time.monotonic() - start


def _wait_for(path: pathlib.Path, timeout: float = 3.0) -> bool:
    """Poll for the backgrounded shim to write its invocation record."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return False


class TestHappyPath:
    def test_marker_and_backgrounded_args(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_home(home)

        sid = "sess-abc123"
        payload = json.dumps(
            {
                "session_id": sid,
                "transcript_path": "/tmp/transcript.jsonl",
                "cwd": "/tmp/project",
            }
        )
        proc, elapsed = _run_hook(home, payload)

        assert proc.returncode == 0
        # backgrounds rather than blocks — generous CI bound, not a literal 200ms
        assert elapsed < 2.0, f"hook took {elapsed:.2f}s"

        hooks_log = (home / ".claude" / "hooks.log").read_text()
        assert f"SESSION_END_RECEIVED\t{sid}\t" in hooks_log

        assert _wait_for(invocation), "shim never recorded its invocation"
        record = invocation.read_text()
        assert "/tmp/transcript.jsonl" in record
        assert sid in record
        assert "/tmp/project" in record


class TestGuards:
    def test_missing_session_id_no_marker(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_home(home)

        payload = json.dumps({"transcript_path": "/tmp/t.jsonl", "cwd": "/tmp"})
        proc, _ = _run_hook(home, payload)

        assert proc.returncode == 0
        hooks_log = home / ".claude" / "hooks.log"
        if hooks_log.exists():
            assert "SESSION_END_RECEIVED" not in hooks_log.read_text()
        # nothing backgrounded
        assert not _wait_for(invocation, timeout=0.5)

    def test_missing_transcript_path_no_marker(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_home(home)

        payload = json.dumps({"session_id": "x", "cwd": "/tmp"})
        proc, _ = _run_hook(home, payload)

        assert proc.returncode == 0
        assert not _wait_for(invocation, timeout=0.5)

    def test_unconfigured_vault_no_background(self, tmp_path):
        """No capture.env / CAPTURE_VAULT_DIR → log a marker, never background curate."""
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_home(home, configure_vault=False)

        payload = json.dumps(
            {"session_id": "s", "transcript_path": "/tmp/t.jsonl", "cwd": "/tmp"}
        )
        proc, _ = _run_hook(home, payload)

        assert proc.returncode == 0
        assert not _wait_for(invocation, timeout=0.5), (
            "curate must not run unconfigured"
        )
        hooks_log = (home / ".claude" / "hooks.log").read_text()
        assert "CAPTURE_NOT_CONFIGURED" in hooks_log


class TestCredentialFallback:
    def test_subscription_token_file_exported(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_home(home)
        (home / ".claude_vault_oauth_token").write_text("DUMMY-OAUTH-TOKEN\n")

        payload = json.dumps(
            {"session_id": "s1", "transcript_path": "/tmp/t.jsonl", "cwd": "/tmp"}
        )
        proc, _ = _run_hook(home, payload, extra_env={"CAPTURE_USE_SUBSCRIPTION": "1"})

        assert proc.returncode == 0
        assert _wait_for(invocation)
        record = invocation.read_text()
        assert "CLAUDE_CODE_OAUTH_TOKEN=DUMMY-OAUTH-TOKEN" in record

    def test_api_key_token_file_exported(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_home(home)
        (home / ".claude_vault_token").write_text("DUMMY-API-KEY\n")

        payload = json.dumps(
            {"session_id": "s2", "transcript_path": "/tmp/t.jsonl", "cwd": "/tmp"}
        )
        proc, _ = _run_hook(home, payload)

        assert proc.returncode == 0
        assert _wait_for(invocation)
        record = invocation.read_text()
        assert "ANTHROPIC_API_KEY=DUMMY-API-KEY" in record
