"""Plugin-mode tests for session-end-capture.sh: no .venv, CLAUDE_PLUGIN_* config,
and the worker launched through a stub `uv` that records its argv and env.
"""

import json
import os
import pathlib
import shutil
import subprocess
import time

import pytest


HOOK = pathlib.Path(__file__).parent.parent / "hooks" / "session-end-capture.sh"


def _build_plugin(home: pathlib.Path) -> pathlib.Path:
    """Lay out a plugin install plus a stub uv; return the stub's record path.

    The hook self-locates via ${BASH_SOURCE[0]}, so a copy goes in the fake root.
    """
    plugin = home / "plugin-root"
    (plugin / "hooks").mkdir(parents=True)
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        '{\n  "name": "claude-vault-capture",\n  "version": "9.9.9"\n}\n'
    )
    (plugin / "hooks" / "curate.py").write_text("# stub — never executed\n")
    shutil.copy(HOOK, plugin / "hooks" / "session-end-capture.sh")

    invocation = home / "uv-invocation.txt"
    bindir = home / "bin"
    bindir.mkdir()
    stub = bindir / "uv"
    # Write to a temp file and rename last (atomic), so _wait_for never reads a
    # half-written record. ${x+x} probes keep unset distinct from set-but-empty.
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'INV="{invocation}"\n'
        'TMP="$INV.tmp"\n'
        'printf "ARGV:%s\\n" "$*" > "$TMP"\n'
        'printf "CAPTURE_VAULT_DIR=%s\\n" "${CAPTURE_VAULT_DIR:-}" >> "$TMP"\n'
        'printf "CAPTURE_STATE_DIR=%s\\n" "${CAPTURE_STATE_DIR:-}" >> "$TMP"\n'
        'printf "SCRUB_FAILURES_PATH=%s\\n" "${SCRUB_FAILURES_PATH:-}" >> "$TMP"\n'
        'printf "CAPTURE_USE_SUBSCRIPTION=%s\\n" "${CAPTURE_USE_SUBSCRIPTION:-}" >> "$TMP"\n'
        'printf "CAPTURE_EXCLUDED_COMMANDS=%s\\n" "${CAPTURE_EXCLUDED_COMMANDS:-}" >> "$TMP"\n'
        'if [ -z "${CAPTURE_MAX_EST_TOKENS+x}" ]; then\n'
        '  printf "CAPTURE_MAX_EST_TOKENS=UNSET\\n" >> "$TMP"\n'
        "else\n"
        '  printf "CAPTURE_MAX_EST_TOKENS=SET[%s]\\n" "$CAPTURE_MAX_EST_TOKENS" >> "$TMP"\n'
        "fi\n"
        'if [ -z "${CAPTURE_TIMEOUT_SECONDS+x}" ]; then\n'
        '  printf "CAPTURE_TIMEOUT_SECONDS=UNSET\\n" >> "$TMP"\n'
        "else\n"
        '  printf "CAPTURE_TIMEOUT_SECONDS=SET[%s]\\n" "$CAPTURE_TIMEOUT_SECONDS" >> "$TMP"\n'
        "fi\n"
        'printf "ANTHROPIC_API_KEY=%s\\n" "${ANTHROPIC_API_KEY:-}" >> "$TMP"\n'
        'printf "CLAUDE_CODE_OAUTH_TOKEN=%s\\n" "${CLAUDE_CODE_OAUTH_TOKEN:-}" >> "$TMP"\n'
        'mv "$TMP" "$INV"\n'
        "exit 0\n"
    )
    stub.chmod(0o755)
    return invocation


def _run_hook(
    home: pathlib.Path, extra_env: dict | None = None, payload: dict | None = None
):
    """Run under /bin/bash: macOS bash 3.2 dies on empty arrays under `set -u`."""
    if payload is None:
        payload = {
            "session_id": "plugin-sess-1",
            "transcript_path": "/tmp/transcript.jsonl",
            "cwd": "/tmp/project",
        }
    env = {
        "HOME": str(home),
        # stub uv shadows any real one; system dirs keep python3/date/stat working
        "PATH": f"{home / 'bin'}:{os.environ.get('PATH', '')}",
        "CLAUDE_PLUGIN_ROOT": str(home / "plugin-root"),
        "CLAUDE_PLUGIN_DATA": str(home / "plugin-data"),
        "CLAUDE_PLUGIN_OPTION_VAULT_DIR": str(home / "vault"),
    }
    if extra_env:
        env.update(extra_env)
    hook_copy = home / "plugin-root" / "hooks" / "session-end-capture.sh"
    proc = subprocess.run(
        ["/bin/bash", str(hook_copy)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    return proc


def _wait_for(path: pathlib.Path, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return False


class TestUvRunBranch:
    def test_no_venv_launches_uv_run_under_system_bash(self, tmp_path):
        """Empty-array expansion must not abort this branch on bash 3.2."""
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_plugin(home)

        proc = _run_hook(home)

        assert proc.returncode == 0, proc.stderr
        assert "unbound variable" not in proc.stderr
        assert _wait_for(invocation), "stub uv never ran — worker was not launched"
        argv = invocation.read_text().splitlines()[0]
        assert argv.startswith("ARGV:run --quiet")
        assert (
            "/hooks/curate.py /tmp/transcript.jsonl plugin-sess-1 /tmp/project" in argv
        )
        assert "--with" not in argv, "non-subscription mode must not pull the SDK"

    def test_subscription_mode_adds_sdk_with_flag(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_plugin(home)

        proc = _run_hook(home, extra_env={"CLAUDE_PLUGIN_OPTION_USE_SUBSCRIPTION": "1"})

        assert proc.returncode == 0, proc.stderr
        assert _wait_for(invocation)
        argv = invocation.read_text().splitlines()[0]
        assert "--with claude-agent-sdk==0.2.89" in argv


class TestPluginConfigMapping:
    def test_plugin_option_vault_dir_reaches_worker(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_plugin(home)

        proc = _run_hook(home)

        assert proc.returncode == 0, proc.stderr
        assert _wait_for(invocation)
        record = invocation.read_text()
        assert f"CAPTURE_VAULT_DIR={home / 'vault'}" in record

    def test_plugin_data_state_dir_created_and_exported(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_plugin(home)

        proc = _run_hook(home)

        assert proc.returncode == 0, proc.stderr
        state = home / "plugin-data" / "state"
        assert state.is_dir(), "hook must create ${CLAUDE_PLUGIN_DATA}/state"
        assert _wait_for(invocation)
        record = invocation.read_text()
        assert f"CAPTURE_STATE_DIR={state}" in record
        assert f"SCRUB_FAILURES_PATH={state / 'scrub-failures.md'}" in record

    def test_explicit_env_wins_over_plugin_option(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_plugin(home)

        proc = _run_hook(home, extra_env={"CAPTURE_VAULT_DIR": str(home / "other")})

        assert proc.returncode == 0, proc.stderr
        assert _wait_for(invocation)
        assert f"CAPTURE_VAULT_DIR={home / 'other'}" in invocation.read_text()


class TestTimeoutOption:
    """curate.py int()s this at import, so an empty or junk export would crash it."""

    def test_option_maps_to_env(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_plugin(home)

        proc = _run_hook(
            home, extra_env={"CLAUDE_PLUGIN_OPTION_TIMEOUT_SECONDS": "120"}
        )

        assert proc.returncode == 0, proc.stderr
        assert _wait_for(invocation)
        assert "CAPTURE_TIMEOUT_SECONDS=SET[120]" in invocation.read_text()

    def test_unset_option_leaves_env_unset_not_empty(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_plugin(home)

        proc = _run_hook(home)

        assert proc.returncode == 0, proc.stderr
        assert _wait_for(invocation)
        assert "CAPTURE_TIMEOUT_SECONDS=UNSET" in invocation.read_text()

    @pytest.mark.parametrize("value", ["2 minutes", "0"])
    def test_invalid_option_is_rejected_and_logged(self, tmp_path, value):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_plugin(home)

        proc = _run_hook(
            home, extra_env={"CLAUDE_PLUGIN_OPTION_TIMEOUT_SECONDS": value}
        )

        assert proc.returncode == 0, proc.stderr
        assert _wait_for(invocation), "junk config must not stop the capture"
        assert "CAPTURE_TIMEOUT_SECONDS=UNSET" in invocation.read_text()
        assert "CAPTURE_BAD_SETTING" in (home / ".claude" / "hooks.log").read_text()


class TestMigratedSettings:
    """capture.env settings that need a userConfig mapping to survive in plugin mode."""

    def test_excluded_commands_maps_through(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_plugin(home)

        proc = _run_hook(
            home,
            extra_env={
                "CLAUDE_PLUGIN_OPTION_EXCLUDED_COMMANDS": "/daily-devlog,/weekly-recap"
            },
        )

        assert proc.returncode == 0, proc.stderr
        assert _wait_for(invocation)
        assert (
            "CAPTURE_EXCLUDED_COMMANDS=/daily-devlog,/weekly-recap"
            in invocation.read_text()
        )

    def test_max_est_tokens_maps_through(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_plugin(home)

        proc = _run_hook(
            home, extra_env={"CLAUDE_PLUGIN_OPTION_MAX_EST_TOKENS": "120000"}
        )

        assert proc.returncode == 0, proc.stderr
        assert _wait_for(invocation)
        assert "CAPTURE_MAX_EST_TOKENS=SET[120000]" in invocation.read_text()

    def test_non_numeric_max_est_tokens_is_rejected(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_plugin(home)

        proc = _run_hook(
            home, extra_env={"CLAUDE_PLUGIN_OPTION_MAX_EST_TOKENS": "120k"}
        )

        assert proc.returncode == 0, proc.stderr
        assert _wait_for(invocation), "junk config must not stop the capture"
        assert "CAPTURE_MAX_EST_TOKENS=UNSET" in invocation.read_text()
        assert "CAPTURE_BAD_SETTING" in (home / ".claude" / "hooks.log").read_text()


class TestDeployIdentity:
    def test_plugin_mode_logs_version_not_git_sha(self, tmp_path):
        """git would describe the enclosing repo, so log the plugin version instead."""
        home = tmp_path / "home"
        home.mkdir()
        _build_plugin(home)

        proc = _run_hook(home)

        assert proc.returncode == 0, proc.stderr
        lines = [
            ln
            for ln in (home / ".claude" / "hooks.log").read_text().splitlines()
            if ln.startswith("CAPTURE_DEPLOY")
        ]
        assert len(lines) == 1, lines
        assert "v9.9.9" in lines[0]
        assert "plugin" in lines[0]


class TestTokenFilePermissions:
    def test_world_readable_token_file_is_refused(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_plugin(home)
        token = home / ".claude_vault_token"
        token.write_text("DUMMY-API-KEY\n")
        token.chmod(0o644)

        proc = _run_hook(home)

        assert proc.returncode == 0, proc.stderr
        assert _wait_for(invocation)
        assert "ANTHROPIC_API_KEY=\n" in invocation.read_text()
        hooks_log = (home / ".claude" / "hooks.log").read_text()
        assert "CAPTURE_TOKEN_FILE_PERMS" in hooks_log

    def test_owner_only_token_file_is_used(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        invocation = _build_plugin(home)
        token = home / ".claude_vault_token"
        token.write_text("DUMMY-API-KEY\n")
        token.chmod(0o600)

        proc = _run_hook(home)

        assert proc.returncode == 0, proc.stderr
        assert _wait_for(invocation)
        assert "ANTHROPIC_API_KEY=DUMMY-API-KEY" in invocation.read_text()
