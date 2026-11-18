import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

from ellie.install import BEGIN, claude_config, claude_home, codex_home, install, strip_codex_table, uninstall
from tests.support import IsolatedTest


OTHER_CONFIG = '''model = "example"
description = """
[mcp_servers.ellie]
This is string content, not a table.
"""

[mcp_servers.other]
command = "other-server"
args = [
  "--array", "[literal brackets]", # preserve me
]

[mcp_servers.other.env]
NOTE = "Keep this user value"
'''


class InstallTests(IsolatedTest):
    def test_hooks_are_idempotent_and_remove_only_ellie_handlers(self):
        other = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "keep-other-hook"}]}]}}
        codex = codex_home() / "hooks.json"
        settings = claude_home() / "settings.json"
        codex.write_text(json.dumps(other))
        settings.write_text(json.dumps({**other, "permissions": {"allow": ["Read"]}}))
        before = {path: path.read_bytes() for path in (codex, settings)}
        with patch("ellie.install.run_cli", return_value=False):
            install(codex=True, claude=True, store=self.store)
            first = {path: path.read_bytes() for path in (codex, settings)}
            install(codex=True, claude=True, store=self.store)
            self.assertEqual(first, {path: path.read_bytes() for path in (codex, settings)})
            self.assertIn("SessionStart", json.loads(codex.read_text())["hooks"])
            self.assertIn("PostToolUseFailure", json.loads(settings.read_text())["hooks"])
            self.assertEqual(json.loads(settings.read_text())["permissions"], {"allow": ["Read"]})
            uninstall()
        self.assertEqual(before, {path: path.read_bytes() for path in (codex, settings)})

    def seed(self):
        (codex_home() / "config.toml").write_text(OTHER_CONFIG)
        (codex_home() / "AGENTS.md").write_text("User Codex instructions\n")
        (claude_home() / "CLAUDE.md").write_text("User Claude instructions\n")
        claude_config().write_text(json.dumps({"userChoice": 42, "mcpServers": {"other": {"command": "keep"}}}))
        (claude_home() / "settings.json").write_text('{"permissions":{"allow":["Read"]}}')

    def test_idempotence_backups_and_uninstall_preserve_user_data(self):
        self.seed()
        self.memory()
        original_memory = self.store.read_memory(self.project, "work").to_bytes()
        original_config = (codex_home() / "config.toml").read_bytes()
        settings = (claude_home() / "settings.json").read_bytes()
        with patch("ellie.install.run_cli", return_value=False):
            self.assertEqual(install(codex=True, claude=True, store=self.store), ["Codex", "Claude Code"])
            paths = [codex_home() / "config.toml", codex_home() / "AGENTS.md", claude_home() / "CLAUDE.md", claude_config()]
            first = [path.read_bytes() for path in paths]
            install(codex=True, claude=True, store=self.store)
            self.assertEqual([path.read_bytes() for path in paths], first)
            self.assertEqual((codex_home() / "config.toml.ellie-backup").read_bytes(), original_config)
            self.assertEqual((codex_home() / "AGENTS.md").read_text().count(BEGIN), 1)
            self.assertIn('default_tools_approval_mode = "approve"', (codex_home() / "config.toml").read_text())
            self.assertTrue(self.store.path("extraction.md").exists())
            self.store.path("extraction.md").write_text("User guidance")
            install(codex=True, store=self.store)
            self.assertEqual(self.store.path("extraction.md").read_text(), "User guidance")
            uninstall()
            uninstall()
        self.assertEqual((codex_home() / "config.toml").read_bytes(), original_config)
        self.assertEqual((codex_home() / "AGENTS.md").read_text(), "User Codex instructions\n")
        self.assertEqual((claude_home() / "CLAUDE.md").read_text(), "User Claude instructions\n")
        data = json.loads(claude_config().read_text())
        self.assertEqual(data, {"userChoice": 42, "mcpServers": {"other": {"command": "keep"}}})
        self.assertEqual((claude_home() / "settings.json").read_bytes(), settings)
        self.assertEqual(self.store.read_memory(self.project, "work").to_bytes(), original_memory)

    def test_table_stripping_handles_quoted_names_subtables_and_arrays(self):
        own = '''["mcp_servers"."ellie"]
command = "python"
args = ["-m", "ellie", "mcp"]
[mcp_servers.ellie.env]
EXAMPLE = "value"
'''
        unrelated = '[mcp_servers.ellie-other]\ncommand = "keep"\n'
        text = OTHER_CONFIG + own + unrelated
        self.assertEqual(strip_codex_table(text), OTHER_CONFIG + unrelated)

    def test_unsafe_toml_and_unbalanced_markers_fail_without_rewriting(self):
        path = codex_home() / "config.toml"
        for content in ('mcp_servers.ellie = {command="python"}\n', 'args = ["unterminated"\n'):
            path.write_text(content)
            with patch("ellie.install.run_cli", return_value=False):
                with self.assertRaises(ValueError):
                    install(codex=True, store=self.store)
            self.assertEqual(path.read_text(), content)
        path.write_text(OTHER_CONFIG)
        instructions = codex_home() / "AGENTS.md"
        instructions.write_text("User text\n" + BEGIN + "\nunfinished\n")
        with patch("ellie.install.run_cli", return_value=False):
            with self.assertRaisesRegex(ValueError, "unbalanced Ellie"):
                install(codex=True, store=self.store)
        self.assertIn("unfinished", instructions.read_text())

    def test_real_codex_parses_fallback_table(self):
        executable = shutil.which("codex")
        if not executable:
            self.skipTest("Codex is not installed")
        with patch("ellie.install.run_cli", return_value=False):
            install(codex=True, store=self.store)
        result = subprocess.run([executable, "mcp", "get", "ellie", "--json"], cwd=self.root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["transport"]["args"], ["-m", "ellie", "mcp"])
        self.assertEqual(data["transport"]["command"], os.path.abspath(sys.executable))

    def test_config_inside_repo_is_rejected_before_cli_runs(self):
        self.git(codex_home(), "init")
        with patch("ellie.install.run_cli", return_value=False) as cli:
            with self.assertRaisesRegex(ValueError, "outside a git repository"):
                install(codex=True, store=self.store)
            cli.assert_not_called()

    def test_default_targets_and_no_persistence_of_blanket_permissions(self):
        with patch("ellie.install.run_cli", return_value=False) as cli:
            self.assertEqual(install(store=self.store), ["Codex", "Claude Code"])
        self.assertTrue(any(call.args[:4] == ("claude", "mcp", "add", "--scope") for call in cli.call_args_list))
        settings = json.loads((claude_home() / "settings.json").read_text())
        self.assertIn("SessionStart", settings["hooks"])
        self.assertNotIn("permissions", settings)

    def test_instruction_without_final_newline_is_restored_exactly(self):
        path = codex_home() / "AGENTS.md"
        path.write_bytes(b"Original text without newline")
        with patch("ellie.install.run_cli", return_value=False):
            install(codex=True, store=self.store)
            uninstall()
        self.assertEqual(path.read_bytes(), b"Original text without newline")

    def test_interpreter_symlink_preserves_the_virtual_environment(self):
        executable = self.root / "tool-venv" / "bin" / "python"
        executable.parent.mkdir(parents=True)
        executable.symlink_to(sys.executable)
        with patch("ellie.install.run_cli", return_value=False), patch("ellie.install.sys.executable", str(executable)):
            install(codex=True, claude=True, store=self.store)
        self.assertIn(json.dumps(str(executable)), (codex_home() / "config.toml").read_text())
        self.assertEqual(json.loads(claude_config().read_text())["mcpServers"]["ellie"]["command"], str(executable))
