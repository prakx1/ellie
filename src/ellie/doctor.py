"""Local diagnostics. Help/config/login-status probes never invoke a model."""

from dataclasses import dataclass
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from .agents import adapter
from .install import BEGIN, END, claude_config, claude_home, codex_home, read_text, strip_codex_table
from .service import DEFAULTS


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool | None
    message: str
    fix: str = ""


def probe(command: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        return result.returncode == 0, result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False, ""


def diagnose(store) -> list[Check]:
    checks = [Check("python", sys.version_info >= (3, 10), sys.version.split()[0], "Use Python 3.10 or later."),
              Check("git", bool(shutil.which("git")), "Git on PATH", "Install Git for repository identification.")]
    try:
        config = {**DEFAULTS, **store.read_local("config")}
    except (ValueError, OSError):
        config = DEFAULTS
        checks.append(Check("config", False, "Invalid local config JSON", "Repair .local/config.json."))
    for agent in ("codex", "claude"):
        executable = shutil.which(agent)
        needed = config["agent"] == agent
        checks.append(Check(agent, bool(executable) if needed or executable else None,
                            "CLI found" if executable else "Optional CLI missing" if not needed else "Default agent CLI missing", f"Install {agent} and add it to PATH."))
        if not executable:
            continue
        help_args = [executable, "exec", "fork", "--help"] if agent == "codex" else [executable, "--help"]
        good, help_text = probe(help_args)
        missing = [flag for flag in adapter(agent).REQUIRED_FLAGS if flag not in help_text]
        checks.append(Check(agent + " extraction flags", good and not missing, "Required safety flags available" if good and not missing else "Required safety flags unavailable", "Upgrade the CLI; capture never falls back to unsafe flags."))
        if agent == "codex":
            logged_in, _ = probe([executable, "login", "status"])
            checks.append(Check("codex login", logged_in, "Logged in" if logged_in else "Not logged in", "Run codex login using your subscription."))
            try:
                configured, raw = probe([executable, "mcp", "get", "ellie", "--json"])
                transport = json.loads(raw)["transport"] if configured else {}
                registered = transport.get("args") == ["-m", "ellie", "mcp"] and Path(transport.get("command", "")).is_absolute()
            except (ValueError, OSError, KeyError, AttributeError):
                registered = False
            instruction_path = codex_home() / "AGENTS.md"
        else:
            try:
                authenticated, raw = probe([executable, "auth", "status"])
                status = json.loads(raw)
                logged_in = authenticated and isinstance(status, dict) and status.get("loggedIn") is True
            except ValueError:
                logged_in = False
            checks.append(Check("claude login", logged_in, "Logged in" if logged_in else "Not logged in or status unavailable",
                                "Run claude auth login --claudeai using your subscription."))
            try:
                entry = json.loads(read_text(claude_config()) or "{}").get("mcpServers", {}).get("ellie", {})
                registered = entry.get("args") == ["-m", "ellie", "mcp"] and Path(entry.get("command", "")).is_absolute()
            except (ValueError, OSError, AttributeError):
                registered = False
            instruction_path = claude_home() / "CLAUDE.md"
        checks.append(Check(agent + " MCP", registered, "Ellie registered" if registered else "Ellie not registered", f"Run ellie install --{agent}."))
        try:
            text = read_text(instruction_path)
            instructions = BEGIN in text and END in text
        except OSError:
            instructions = False
        checks.append(Check(agent + " instructions", instructions, "Instruction block present" if instructions else "Instruction block missing", f"Run ellie install --{agent}."))
        hook_path = codex_home() / "hooks.json" if agent == "codex" else claude_home() / "settings.json"
        try:
            hooks = json.loads(read_text(hook_path) or "{}").get("hooks", {})
            registered_hooks = all(any(" -m ellie hook " in handler.get("command", "")
                                      for group in hooks.get(event, []) for handler in group.get("hooks", []))
                                   for event in ("SessionStart", "Stop", "SessionEnd"))
        except (ValueError, OSError, TypeError, AttributeError):
            registered_hooks = False
        checks.append(Check(agent + " hooks", registered_hooks, "Ellie lifecycle commands registered" if registered_hooks else "Automatic capture hooks missing", f"Run ellie install --{agent}; review hooks in the agent."))
        if agent == "codex" and registered_hooks:
            good, features = probe([executable, "features", "list"])
            supported = good and any(line.split()[:1] == ["hooks"] and line.split()[-1:] == ["true"] for line in features.splitlines())
            checks.append(Check("codex hook support", True if supported else None, "Hooks enabled" if supported else "Could not verify hook support", "Update Codex if needed; review and trust Ellie with /hooks. Config alone does not prove hook trust."))
        found = adapter(agent).discover()
        checks.append(Check(agent + " sessions", not found.problems, f"{len(found.sessions)} readable sessions" if not found.problems else "; ".join(found.problems), "Inspect the reported files; update the CLI/adapter if its session format changed."))
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
        fts = True
    except sqlite3.OperationalError:
        fts = False
    finally:
        connection.close()
    checks.append(Check("SQLite FTS5", True if fts else None, "Available" if fts else "Unavailable; LIKE fallback is active", "Use a Python SQLite build with FTS5 for better ranking."))
    try:
        store.probe_writable()
        checks.append(Check("store write", True, "Store is writable"))
    except OSError:
        checks.append(Check("store write", False, "Store is not writable", "Fix ELLIE_HOME ownership/permissions or choose another directory."))
    store.list_pending()
    for problem in store.pending_problems:
        checks.append(Check("pending record", False, problem, "Repair the pending JSON; keep a copy before editing it."))
    failed = [job for job in store.list_pending() if job.get("capture") == "failed"]
    if failed:
        checks.append(Check("capture retries", None, f"{len(failed)} failed capture job(s)", "Run ellie capture --wait; see .local/logs for background failures."))
    try:
        for project in store.list_projects():
            seen = set()
            for memory in store.iter_memories(project):
                for item in memory.items:
                    if item.id in seen:
                        raise ValueError("duplicate item ID " + item.id + " in " + project)
                    seen.add(item.id)
        checks.append(Check("memory files", True, "Memory names and project item IDs are consistent"))
    except (ValueError, OSError) as exc:
        checks.append(Check("memory files", False, str(exc), "Repair the affected memory file, then run ellie reindex."))
    index_path = store.path(".local", "index.db")
    if index_path.exists():
        try:
            with closing(sqlite3.connect(index_path.as_uri() + "?mode=ro", uri=True)) as db:
                good = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            checks.append(Check("search index", good, "Index is readable" if good else "Index needs rebuilding", "Run ellie reindex."))
        except sqlite3.DatabaseError:
            checks.append(Check("search index", False, "Index is corrupt", "Run ellie reindex."))
    return checks


def run(store, output=None) -> int:
    output = output or sys.stdout
    checks = diagnose(store)
    for check in checks:
        label = "PASS" if check.ok is True else "FAIL" if check.ok is False else "WARN"
        print(f"{label} {check.name}: {check.message}", file=output)
        if check.ok is not True and check.fix:
            print("  Fix: " + check.fix, file=output)
    return int(any(check.ok is False for check in checks))
