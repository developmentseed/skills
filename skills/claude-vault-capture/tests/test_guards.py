"""Unit tests for project derivation from cwd + token-count ceiling."""

import sys
import pathlib
import subprocess

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))

from curate import derive_project, is_above_token_limit, CAPTURE_MAX_EST_TOKENS


class TestProjectDerivation:
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
