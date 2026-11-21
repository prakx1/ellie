from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess

from ellie.agents import adapter
from ellie.capture import discover_project, match_session
from tests.fake_agents import write_session
from tests.support import IsolatedTest


class SessionTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.git(self.checkout, "init")
        self.git(self.checkout, "remote", "add", "origin", "https://" + self.project + ".git")

    def test_codex_disabled_server_overrides_parse_without_user_configuration(self):
        executable = shutil.which("codex")
        if not executable:
            self.skipTest("Codex is not installed")
        directory = self.root / "extraction"
        directory.mkdir()
        names = {"sample", "hyphen-server", "quoted.server", 'quote"server'}
        command = adapter("codex").command(executable, None, directory, directory / "schema.json",
                                           directory / "out.json", sorted(names))
        overrides = []
        for index, value in enumerate(command[:-1]):
            if value == "-c" and command[index + 1].startswith(("mcp_servers.", "mcp_servers=")):
                overrides.extend([value, command[index + 1]])
        # An empty temporary profile reproduces exec --ignore-user-config's
        # missing transport definitions. This command never starts a model.
        result = subprocess.run([executable, *overrides, "mcp", "list", "--json"],
                                cwd=directory, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual({row["name"] for row in rows}, names)
        self.assertTrue(all(not row["enabled"] for row in rows))
        for row in rows:
            path = Path(row["transport"]["command"])
            self.assertEqual(path.parent, directory)
            self.assertFalse(path.exists())

    def test_both_codex_generations_and_claude_count_human_prompts(self):
        write_session(self, "codex")
        write_session(self, "codex", paginated=True)
        write_session(self, "claude")
        found = discover_project(self.store, self.project)
        self.assertEqual(found.problems, [])
        self.assertEqual(len(found.sessions), 3)
        self.assertEqual([s.user_messages for s in found.sessions], [2, 2, 2])
        self.assertTrue(all(s.first_user_message == "User prompt 0" for s in found.sessions))

    def test_subfolder_directory_and_other_clone_match_same_project(self):
        nested = self.checkout / "src"
        nested.mkdir()
        clone = self.root / "clone"
        clone.mkdir()
        self.git(clone, "init")
        self.git(clone, "remote", "add", "origin", "git@github.com:example/app.git")
        write_session(self, "claude", cwd=nested)
        write_session(self, "claude", cwd=clone)
        other = self.root / "unrelated"
        other.mkdir()
        write_session(self, "codex", cwd=other)
        self.assertEqual(len(discover_project(self.store, self.project).sessions), 2)

    def test_malformed_files_report_and_continue(self):
        session = write_session(self)
        broken = session.path.parent / "rollout-broken.jsonl"
        broken.write_text("{invalid")
        found = discover_project(self.store, self.project)
        self.assertEqual(len(found.sessions), 1)
        self.assertEqual(len(found.problems), 1)
        with session.path.open("a") as stream:
            stream.write("{unfinished")
        self.assertEqual(len(discover_project(self.store, self.project).problems), 2)

    def test_launcher_uses_changed_identity_and_rejects_ambiguity(self):
        old = write_session(self, start=datetime.now(timezone.utc) - timedelta(days=30))
        before = adapter("codex").snapshot()
        new = write_session(self, start=datetime.now(timezone.utc))
        job = {"agent": "codex", "cwd": str(self.checkout), "started": datetime.now(timezone.utc).isoformat(), "before_sessions": before}
        self.assertEqual(match_session(job, discover_project(self.store, self.project).sessions).id, new.id)
        newer = write_session(self, start=datetime.now(timezone.utc))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            match_session(job, discover_project(self.store, self.project).sessions)
        self.assertEqual(match_session(job, discover_project(self.store, self.project).sessions, newer.id).id, newer.id)

    def test_claude_duplicate_uuid_and_other_session_references(self):
        session = write_session(self, "claude")
        rows = [json.loads(line) for line in session.path.read_text().splitlines()]
        rows.extend([rows[1], {**rows[1], "sessionId": "00000000-0000-4000-8000-000000000000", "cwd": "/unrelated"}])
        session.path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        found = adapter("claude").discover()
        self.assertEqual(found.sessions[0].user_messages, 2)
        self.assertEqual(found.sessions[0].cwd, str(self.checkout))

    def test_claude_image_only_prompt_counts_as_human_input(self):
        session = write_session(self, "claude")
        rows = [json.loads(line) for line in session.path.read_text().splitlines()]
        rows[1]["message"]["content"] = [{"type": "image", "source": {"type": "base64", "data": "fixture"}}]
        session.path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        self.assertEqual(adapter("claude").read(session.path).user_messages, 2)
