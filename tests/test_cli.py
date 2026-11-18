import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from tests.support import IsolatedTest


class CLITests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.git(self.checkout, "init")
        self.git(self.checkout, "remote", "add", "origin", "https://" + self.project + ".git")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.agent_output = self.root / "agent.json"
        script = "#!" + sys.executable + "\nimport json, os, pathlib, sys\npathlib.Path(os.environ['TEST_AGENT_OUTPUT']).write_text(json.dumps({'argv':sys.argv[1:], 'agent':os.environ.get('ELLIE_AGENT'), 'run':os.environ.get('ELLIE_RUN_ID'), 'cwd':os.getcwd()}))\nraise SystemExit(int(os.environ.get('TEST_AGENT_EXIT','0')))\n"
        for agent in ("codex", "claude"):
            path = self.bin / agent
            path.write_text(script)
            path.chmod(0o755)
        self.env = {**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"], "TEST_AGENT_OUTPUT": str(self.agent_output)}

    def cli(self, *args, expected=0, input=None, env=None):
        result = subprocess.run([sys.executable, "-m", "ellie", *args], cwd=self.checkout,
                                env={**self.env, **(env or {})}, input=input,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def test_basic_commands_import_and_separation(self):
        self.assertIn(self.project, self.cli().stdout)
        self.cli("new", "auth", "--goal", "Ship", "--done-when", "Green")
        self.assertIn("**Done when:** Green", self.cli("show", "auth").stdout)
        self.cli("log", "auth", "Tests green", "-k", "progress")
        self.assertIn("you · progress: Tests green", self.cli("show", "auth").stdout)
        source = self.checkout / "HANDOFF.md"
        content = "# Old handoff\n\n## Goal\nKeep this as imported text.\n"
        source.write_text(content)
        self.cli("import", str(source), "--as", "payments")
        imported = self.store.read_memory(self.project, "payments")
        self.assertIn(content.rstrip(), imported.get_section("Current state"))
        self.assertNotIn("Keep this", imported.get_section("Goal"))
        self.assertNotIn("Old handoff", self.cli("show", "auth").stdout)
        self.assertEqual(source.read_text(), content)
        self.cli("archive", "payments")
        self.assertIn("1 archived memories", self.cli("status").stdout)
        self.cli("restore", "payments")
        self.assertIn("payments", self.cli("status").stdout)
        self.assertIn(self.project, self.cli("projects").stdout)
        self.assertEqual(Path(self.cli("where").stdout.strip()), self.store.root)

    def test_passthrough_exit_code_prompt_and_pending(self):
        self.memory()
        result = self.cli("start", "codex", "-m", "work", "--no-capture", "--", "--model", "fake model", "--agent-option", "value", expected=7, env={"TEST_AGENT_EXIT": "7"})
        recorded = json.loads(self.agent_output.read_text())
        self.assertEqual(recorded["argv"][:-1], ["--model", "fake model", "--agent-option", "value"])
        self.assertTrue(recorded["argv"][-1].startswith("[ellie session]"))
        self.assertIn("then wait.", recorded["argv"][-1])
        self.assertEqual(recorded["cwd"], str(self.checkout))
        self.assertEqual(recorded["agent"], "codex")
        job = self.store.read_pending(recorded["run"])
        self.assertEqual(job["exit_code"], 7)
        self.assertIn("ended", job)
        self.assertNotIn("capturing", result.stdout)

    def test_claude_session_id_and_explicit_passthrough_id(self):
        self.cli("start", "claude", "-p", "--no-capture")
        recorded = json.loads(self.agent_output.read_text())
        self.assertEqual(recorded["agent"], "claude-code")
        self.assertEqual(recorded["argv"][:2], ["--session-id", self.store.read_pending(recorded["run"])["session_id"]])
        id = "11111111-1111-4111-8111-111111111111"
        self.cli("start", "claude", "-p", "--no-capture", "--", "--session-id", id)
        recorded = json.loads(self.agent_output.read_text())
        self.assertEqual(recorded["argv"].count("--session-id"), 1)
        self.assertEqual(self.store.read_pending(recorded["run"])["session_id"], id)

    def test_non_tty_last_used_and_dry_run_does_not_launch(self):
        self.memory()
        self.store.update_local("state", lambda data: data.update({"last_used": {self.project: ["work", "deleted"]}}))
        prompt = self.cli("start", "--dry-run").stdout
        self.assertIn("memories: work", prompt)
        self.assertNotIn("deleted", prompt)
        self.assertFalse(self.agent_output.exists())
        self.cli("start", "--new", "draft", "--dry-run")
        self.assertNotIn("draft", [meta.name for meta in self.store.list_memories(self.project)])
        self.assertFalse(self.store.path(".local", "pending").exists())

    def test_about_with_cross_project_and_prompt_budget(self):
        self.memory()
        self.store.add_item(self.project, "work", "R", "Iframe refresh", {"outcome": "failed", "what": "refresh", "evidence": "Safari ITP"})
        self.store.add_item(self.project, "work", "D", "Use authlib", {"status": "active", "chosen": "authlib", "why": "PKCE token refresh built in"})
        other = "github.com/example/other"
        self.store.create_memory(other, "other")
        self.store.add_item(other, "other", "D", "Use Redis", {"status": "active", "chosen": "redis", "why": "Counters"})
        result = self.cli("brief", "token refresh", "--json")
        self.assertEqual(set(json.loads(result.stdout)["ids"]), {"D1", "R1"})
        prompt = self.cli("start", "-p", "--about", "refresh", "--with", other + ":D1", "--dry-run").stdout
        self.assertIn("Safari ITP", prompt)
        self.assertIn("Use authlib", prompt)
        self.assertIn("Use Redis", prompt)
        self.assertIn("## Selected from project history", prompt)
        self.cli("config", "briefing_max_chars", "32")
        prompt = self.cli("start", "-p", "--with", "R1", "--dry-run").stdout
        self.assertIn("Call ellie load", prompt)
        self.assertIn("ellie get", prompt)
        self.assertIn("R1", prompt)

    def test_editor_reindexes(self):
        self.memory()
        self.store.add_item(self.project, "work", "N", "Legacy", {}, body="A note")
        editor = self.root / "editor script.py"
        editor.write_text("from pathlib import Path\nimport sys\np=Path(sys.argv[1]); p.write_text(p.read_text().replace('Legacy','Modern'))\n")
        self.cli("edit", "work", env={"VISUAL": f'{sys.executable} "{editor}"'})
        self.assertIn("Modern", self.cli("recall", "modern").stdout)
        self.assertNotIn("Legacy", self.cli("recall", "legacy").stdout)
        self.assertIn("Indexed 1 items", self.cli("reindex").stdout)

    @unittest.skipIf(os.name == "nt", "pseudo-TTY requires Unix")
    def test_picker_with_scripted_stdin_on_real_pty(self):
        import pty
        self.memory("auth")
        self.memory("billing")
        master, slave = pty.openpty()
        process = subprocess.Popen([sys.executable, "-m", "ellie", "start", "--dry-run"],
                                   cwd=self.checkout, env=self.env, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        os.close(slave)
        try:
            os.write(master, b"1,2\n")
            out, err = process.communicate(timeout=20)
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
                process.wait()
        self.assertEqual(process.returncode, 0, err)
        self.assertIn("Pick [1,2", out)
        self.assertIn("memories: auth, billing", out)

    def test_errors_have_prefix_and_exit_one(self):
        for args in [("bogus",), ("new", "../escape"), ("config", "capture", "invalid"), ("config", "unknown"), ("show", "missing"), ("recall", "query", "-n", "0")]:
            result = self.cli(*args, expected=1)
            self.assertTrue(result.stderr.startswith("ellie:"), result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_broken_pipe_is_quiet(self):
        self.memory()
        self.store.update_memory(self.project, "work", lambda m: m.set_section("Current state", "text " * 300000))
        process = subprocess.Popen([sys.executable, "-m", "ellie", "show", "work"], cwd=self.checkout,
                                   env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.stdout.close()
        err = process.stderr.read()
        process.stderr.close()
        self.assertEqual(process.wait(timeout=20), 0, err)
        self.assertNotIn(b"BrokenPipe", err)

    def test_install_uninstall_commands_use_only_isolated_homes(self):
        self.memory()
        before = self.store.read_memory(self.project, "work").to_bytes()
        self.assertIn("Installed Ellie", self.cli("install").stdout)
        self.cli("install")
        self.assertTrue((Path(self.env["CODEX_HOME"]) / "AGENTS.md").exists())
        self.assertIn("Project memories are intact", self.cli("uninstall").stdout)
        self.assertEqual(self.store.read_memory(self.project, "work").to_bytes(), before)

    def test_reindex_recovers_corrupt_cache_without_changing_memories(self):
        self.memory()
        self.store.add_item(self.project, "work", "N", "Redis counters", {}, body="Keep this history")
        before = {memory.name: memory.to_bytes() for memory in self.store.iter_memories(self.project)}
        index = self.store.path(".local", "index.db")
        index.write_bytes(b"corrupt cache fixture")
        self.assertIn("Indexed 1 items", self.cli("reindex").stdout)
        self.assertIn("Redis counters", self.cli("recall", "redis").stdout)
        self.assertEqual({memory.name: memory.to_bytes() for memory in self.store.iter_memories(self.project)}, before)
