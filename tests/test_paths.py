from pathlib import Path
import os
from unittest.mock import patch

from ellie.paths import ellie_home, normalize_remote, project_id, validate_name, validate_project
from tests.support import IsolatedTest


class PathTests(IsolatedTest):
    def test_remote_normalization(self):
        cases = {
            "git@github.com:Me/App.git": "github.com/me/app",
            "https://username:fake-password@GitHub.com/Me/App.git": "github.com/me/app",
            "ssh://git@GitHub.com:2222/Me/App.git": "github.com/me/app",
            "https://github.com/Me/Space Repo.git/": "github.com/me/space-repo",
            "github.com/Me/App": "github.com/me/app",
        }
        for remote, expected in cases.items():
            self.assertEqual(normalize_remote(remote), expected)
        for remote in ("git@host:../escape.git", "https://host/owner/%2e%2e/app", ""):
            with self.assertRaises(ValueError):
                normalize_remote(remote)

    def test_project_subfolders_clones_and_worktrees(self):
        repo = self.root / "repo"
        repo.mkdir()
        self.git(repo, "init")
        self.git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "fixture")
        self.git(repo, "remote", "add", "origin", "git@github.com:Me/App.git")
        nested = repo / "src" / "nested"
        nested.mkdir(parents=True)
        self.assertEqual(project_id(nested), ("github.com/me/app", repo))
        clone = self.root / "other"
        clone.mkdir()
        self.git(clone, "init")
        self.git(clone, "remote", "add", "origin", "https://github.com/me/app.git")
        self.assertEqual(project_id(clone)[0], "github.com/me/app")
        worktree = self.root / "worktree"
        self.git(repo, "worktree", "add", "-b", "fixture", str(worktree))
        self.assertEqual(project_id(worktree)[0], "github.com/me/app")

    def test_fallback_and_manual_link(self):
        folder = self.root / "A Project"
        folder.mkdir()
        self.assertEqual(project_id(folder)[0], "local/a-project")
        self.memory()
        self.store.link(folder, self.project)
        self.assertEqual(self.store.resolve_project(folder), (self.project, folder))
        with self.assertRaises(ValueError):
            self.store.link(folder, "missing/project")

    def test_validation_and_isolated_default(self):
        self.assertEqual(ellie_home(), self.root / "store")
        for name in ("../bad", "..", "a/b", "", "UPPER", "a\nb"):
            with self.assertRaises(ValueError):
                validate_name(name)
        for project in ("../x", "/absolute", "a//b", "a/../b", "a\\b"):
            with self.assertRaises(ValueError):
                validate_project(project)

    def test_inherited_git_environment_does_not_redirect_identity(self):
        with patch.dict(os.environ, {"GIT_DIR": "/does/not/exist"}):
            self.assertEqual(project_id(self.root)[0], "local/" + self.root.name)
