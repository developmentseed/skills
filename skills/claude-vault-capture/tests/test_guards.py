"""Unit tests for project derivation from cwd + token-count ceiling."""

import subprocess

import pytest


from curate import derive_project, is_above_token_limit, CAPTURE_MAX_EST_TOKENS


class TestProjectDerivation:
    @pytest.fixture(autouse=True)
    def _scrub_git_env(self, monkeypatch):
        """Under a git hook (pre-push runs pytest) GIT_DIR et al. would point
        derive_project's `git rev-parse` at the outer repo, not tmp_path."""
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

    def test_linked_worktree_reports_the_main_repo(self, tmp_path):
        repo = tmp_path / "my-project"
        repo.mkdir()
        git = [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "-c",
            "commit.gpgsign=false",
        ]
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            [*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True
        )
        wt = tmp_path / "pr5-fixes"
        subprocess.run([*git, "worktree", "add", "-q", str(wt)], check=True)
        assert derive_project(str(wt)) == "my-project"

    def test_removed_cwd_falls_back_to_an_existing_ancestor(self, tmp_path):
        repo = tmp_path / "my-project"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        assert derive_project(str(repo / "gone" / "deeper")) == "my-project"

    def test_outside_git_repo_returns_home(self, tmp_path):
        no_git = tmp_path / "no-git-dir"
        no_git.mkdir()
        assert derive_project(str(no_git)) == "home"


class TestTokenCeiling:
    @pytest.fixture(autouse=True)
    def _clear_env_override(self, monkeypatch):
        """Inputs are sized from the default; an exported override would break them."""
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
