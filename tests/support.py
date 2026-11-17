"""Every test owns its home, store and agent roots; no real login is needed."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ellie.store import FileStore


class IsolatedTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ellie-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        environment = {key: str(self.root / part) for key, part in {
            "HOME": "home", "CODEX_HOME": "codex", "ELLIE_HOME": "store",
            "CLAUDE_CONFIG_DIR": "claude", "XDG_CONFIG_HOME": "config",
            "XDG_CACHE_HOME": "cache", "XDG_DATA_HOME": "data",
        }.items()}
        for path in environment.values():
            Path(path).mkdir()
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CODEX_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
            environment[key] = ""
        self.environment = patch.dict(os.environ, environment)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.store = FileStore()
        self.project = "github.com/example/app"

    def memory(self, name="work"):
        return self.store.create_memory(self.project, name, "Example work")

    def git(self, path, *args):
        result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()
