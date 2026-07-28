"""Unit tests for project derivation from cwd + token-count ceiling."""

import subprocess

import pytest


from curate import derive_project, is_above_token_limit, CAPTURE_MAX_EST_TOKENS


class TestProjectDerivation:
    @pytest.fixture(autouse=True)
    def _scrub_git_env(self, monkeypatch):
        """Drop git's exported repo env so subprocess git calls see only cwd.

        When pytest itself runs inside a git hook (the pre-push hook does
        this), git exports GIT_DIR et al.; derive_project's `git rev-parse`
        then resolves against the exporting repo instead of the tmp_path repo
        these tests create, e.g. reporting `subdir` as the toplevel.
        """
        for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
            monkeypatch.delenv(var, raising=False)

    def test_inside_git_repo_returns_basename(self, tmp_path):
        repo = tmp_path / "my-project"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True)
        assert derive_project(str(repo)) == "my-project"

    def test_inside_git_repo_subdir(self, tmp_path):
        repo = tmp_path / "my-project"
        (repo / "subdir").mkdir(parents=True)
        subprocess.run(["git", "init", str(repo)], capture_output=True)
        assert derive_project(str(repo / "subdir")) == "my-project"

    def test_outside_git_repo_returns_home(self, tmp_path):
        no_git = tmp_path / "no-git-dir"
        no_git.mkdir()
        assert derive_project(str(no_git)) == "home"


class TestTokenCeiling:
    @pytest.fixture(autouse=True)
    def _clear_env_override(self, monkeypatch):
        """These tests size inputs from the imported literal default; an
        exported CAPTURE_MAX_EST_TOKENS (e.g. sourced from capture.env) would
        change the call-time limit out from under them."""
        monkeypatch.delenv("CAPTURE_MAX_EST_TOKENS", raising=False)

    def test_above_limit_returns_true(self):
        # Need +4 chars (+1 token) because // 4 truncates: 200001 // 4 = 50000 (not above)
        text = "a" * (CAPTURE_MAX_EST_TOKENS * 4 + 4)
        assert is_above_token_limit(text) is True

    def test_at_limit_returns_false(self):
        # Exactly at limit: 50000*4 // 4 = 50000, not > 50000
        text = "a" * (CAPTURE_MAX_EST_TOKENS * 4)
        assert is_above_token_limit(text) is False

    def test_below_limit_returns_false(self):
        text = "short text"
        assert is_above_token_limit(text) is False

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("CAPTURE_MAX_EST_TOKENS", "100")
        from curate import is_above_token_limit as f

        text = "a" * (100 * 4 + 4)  # +4 chars → one extra estimated token
        assert f(text) is True
