"""Idempotent agent integration with backups and narrowly scoped config edits."""

from __future__ import annotations

from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys

from .paths import git_output
from .store import FileLock, FileStore, _replace

BEGIN = "<!-- ellie:begin -->"
END = "<!-- ellie:end -->"
INSTRUCTIONS = """## Project memory (ellie)
A `ellie` MCP server holds this repo's long-term memory: goals, decisions, results, findings,
open questions, shared across sessions and agents (Codex and Claude Code).
- If the conversation starts with a `[ellie session]` block, that memory is loaded.
- A `[ellie conversation]` hook block gives the current native session_id: include
  it in every Ellie call. Use bind/load for this conversation's write workstreams.
- Use conversations to list sources. To use only selected chats, call load with
  conversations=[IDs]; [] means no past chats. Never widen a selection unasked.
- If a hook supplies an `[ellie memory picker]`, show its numbered choices on your first reply
  to my normal message and wait for my selection before starting work. No Ellie command is needed.
  Keep the displayed numbers stable; use a native choice UI if available, otherwise a numbered list.
  Show each choice's Covers description, topics, saved state and next step when available, not just its label.
  Keep those previews visible in chat even if native choice controls hide descriptions.
- Otherwise, if context is not already selected, call `status` and `conversations` with cwd=<repo path>.
  If saved context exists, show a numbered memory picker with descriptions/topics/state/next steps and dates/item counts,
  named workstreams, and `0) Start fresh`. Wait for my choice before loading history or doing the task.
  Conversation rows use only chosen source IDs; Start fresh uses conversations=[]. Never select all by default.
  Respect an explicit choice in my first message and an existing binding; don't ask again on resume.
- Before answering latest work/progress, reload selected memory with `load` and keep the existing
  conversation selection. `status` returns inventory/health; another chat's saves need a fresh load.
- Before choosing an approach, call `recall` to check what was decided, tried or learned before.
- As you work: `decide` for choices (options, tradeoff, why), `result` for things tried
  (worked/failed/partial with evidence), `finding` for things learned, `question` for open issues.
  Skip trivia. Repo-wide facts go to memory="project".
- When I say handoff / wrap up / save, call `handoff`.
- Memory may be outdated: verify against the code before relying on it.
- Never store secrets."""
BLOCK = BEGIN + "\n" + INSTRUCTIONS + "\n" + END + "\n"


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).expanduser()


def claude_config() -> Path:
    return (claude_home() if "CLAUDE_CONFIG_DIR" in os.environ else Path.home()) / ".claude.json"


def guarded(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("refusing to replace a symlinked agent config")
    path = path.expanduser().resolve()
    nearest = path.parent
    while not nearest.exists():
        nearest = nearest.parent
    if git_output(nearest, "rev-parse", "--show-toplevel"):
        raise ValueError("agent configuration must be outside a git repository")
    return path


def read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8") if path.exists() else ""


def backup(path: Path) -> None:
    copy = Path(str(path) + ".ellie-backup")
    if path.exists():
        with FileLock(copy):
            if not copy.exists():
                original = path.read_bytes()
                _replace(copy, lambda stream: stream.write(original))


def modify(path: Path, change, *, remove_empty: bool = False) -> None:
    path = guarded(path)
    with FileLock(path):
        original = read_text(path)
        updated = change(original)
        if updated == original:
            return
        backup(path)
        prior = Path(str(path) + ".ellie-backup")
        # Restore only separator whitespace; never restore removed Ellie config.
        if prior.exists():
            prior_text = read_text(prior)
            if updated in (prior_text + "\n", prior_text + "\n\n"):
                updated = prior_text
        if remove_empty and not updated.strip() and not prior.exists():
            path.unlink(missing_ok=True)
        else:
            _replace(path, lambda stream: stream.write(updated.encode("utf-8")))


def _keys(text: str) -> list[str]:
    result = []
    position = 0
    pattern = re.compile(r'''\s*("(?:[^"\\]|\\.)*"|'[^']*'|[A-Za-z0-9_-]+)\s*''')
    while position < len(text):
        match = pattern.match(text, position)
        if not match:
            raise ValueError("cannot safely parse a TOML table key")
        key = match.group(1)
        result.append(json.loads(key) if key.startswith('"') else key[1:-1] if key.startswith("'") else key)
        position = match.end()
        if position == len(text):
            break
        if text[position] != ".":
            raise ValueError("cannot safely parse a TOML dotted key")
        position += 1
    return result


def _scan_line(line: str, quote: str | None, depth: int) -> tuple[str | None, int]:
    i = 0
    while i < len(line):
        if quote:
            if quote[0] == '"' and line[i] == "\\":
                i += 2
                continue
            if line.startswith(quote, i):
                i += len(quote)
                quote = None
            else:
                i += 1
            continue
        char = line[i]
        if char == "#":
            break
        if char in "\"'":
            quote = char * 3 if line.startswith(char * 3, i) else char
            i += len(quote)
        else:
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
            i += 1
    if quote and len(quote) == 1:
        raise ValueError("unterminated TOML string; configuration left unchanged")
    return quote, depth


def strip_codex_table(text: str) -> str:
    """Remove only Ellie's table/subtables; arrays and multiline strings survive."""
    result = []
    owned = False
    quote = None
    depth = 0
    table = []
    for line in text.splitlines(keepends=True):
        if quote is None and depth == 0:
            header = re.fullmatch(r"\s*(\[\[?)(.*?)(\]\]?)\s*(?:#.*)?(?:\r?\n)?", line)
            if header:
                if len(header.group(1)) != len(header.group(3)):
                    raise ValueError("invalid TOML table header")
                table = _keys(header.group(2).strip())
                owned = table[:2] == ["mcp_servers", "ellie"]
                if not owned:
                    result.append(line)
                continue
            if not owned and "=" in line and not line.lstrip().startswith("#"):
                key = _keys(line.split("=", 1)[0].strip())
                if (table + key)[:2] == ["mcp_servers", "ellie"]:
                    raise ValueError("inline/dotted Ellie config requires the codex mcp command; file left unchanged")
        if not owned:
            result.append(line)
        quote, depth = _scan_line(line, quote, depth)
    if quote or depth:
        raise ValueError("unbalanced TOML; configuration left unchanged")
    return "".join(result)


def codex_table() -> str:
    return ('[mcp_servers.ellie]\ncommand = ' + json.dumps(os.path.abspath(sys.executable))
            + '\nargs = ["-m", "ellie", "mcp"]\ndefault_tools_approval_mode = "approve"\n')


def upsert_codex(text: str) -> str:
    clean = strip_codex_table(text)
    return clean + ("" if not clean or clean.endswith("\n\n") else "\n" if clean.endswith("\n") else "\n\n") + codex_table()


def strip_instructions(text: str) -> str:
    begins = list(re.finditer(r"(?m)^" + re.escape(BEGIN) + r"\s*$", text))
    ends = list(re.finditer(r"(?m)^" + re.escape(END) + r"\s*$", text))
    if len(begins) != len(ends) or any(begin.start() >= end.start() for begin, end in zip(begins, ends)):
        raise ValueError("unbalanced Ellie instruction markers; file left unchanged")
    order = [kind for _, kind in sorted([(match.start(), "begin") for match in begins] + [(match.start(), "end") for match in ends])]
    if order != [kind for _ in begins for kind in ("begin", "end")]:
        raise ValueError("nested Ellie instruction markers; file left unchanged")
    pattern = r"(?ms)^" + re.escape(BEGIN) + r"\r?\n.*?^" + re.escape(END) + r"[^\S\r\n]*(?:\r?\n|$)"
    return re.sub(pattern, "", text)


def upsert_instructions(text: str) -> str:
    if BEGIN in text:
        clean = strip_instructions(text)
    else:
        clean = text
    return clean + ("" if not clean or clean.endswith("\n\n") else "\n" if clean.endswith("\n") else "\n\n") + BLOCK


def run_cli(name: str, *args: str) -> bool:
    executable = shutil.which(name)
    if not executable:
        return False
    try:
        result = subprocess.run([executable, *args], cwd=Path.home(), capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def hook_config(text: str, agent: str, *, remove: bool = False) -> str:
    """Own only commands carrying our exact CLI suffix; preserve other handlers."""
    from .hooks import EVENTS
    data = json.loads(text) if text.strip() else {}
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise ValueError("hook configuration and hooks must be JSON objects")
    original = json.loads(json.dumps(data))
    hooks = data.setdefault("hooks", {})
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            raise ValueError("hook event handlers must be lists")
        kept = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                raise ValueError("invalid hook matcher group")
            handlers = []
            for handler in group.get("hooks", []):
                command = handler.get("command", "") if isinstance(handler, dict) else ""
                owned = isinstance(command, str) and any(command.endswith(f" -m ellie hook {name} {event} --ellie-managed") for name in ("codex", "claude"))
                if not owned:
                    handlers.append(handler)
            if handlers or not group.get("hooks"):
                kept.append({**group, "hooks": handlers})
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not remove:
        events = [*EVENTS, "PostToolUseFailure" if agent == "claude" else "Interrupt"]
        for event in events:
            args = [os.path.abspath(sys.executable), "-m", "ellie", "hook", agent, event, "--ellie-managed"]
            command = subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)
            hooks.setdefault(event, []).append({"hooks": [{"type": "command", "command": command, "timeout": 3 if event == "SessionEnd" else 10}]})
    if not hooks:
        data.pop("hooks", None)
    return text if data == original else json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def configure_hooks(path: Path, agent: str, *, remove=False):
    def change(text):
        updated = hook_config(text, agent, remove=remove)
        prior = Path(str(path) + ".ellie-backup")
        if remove and prior.exists():
            previous = read_text(prior)
            if json.loads(previous or "{}") == json.loads(updated or "{}"):
                return previous
        if remove and json.loads(updated or "{}") == {} and not prior.exists():
            return ""
        return updated
    modify(path, change, remove_empty=remove)


def install(*, codex: bool = False, claude: bool = False, store: FileStore | None = None) -> list[str]:
    store = store if store is not None else FileStore()
    if not codex and not claude:
        codex, claude = True, bool(shutil.which("claude") or claude_home().exists())
    installed = []
    if codex:
        config = guarded(codex_home() / "config.toml")
        backup(config)
        run_cli("codex", "mcp", "remove", "ellie")
        run_cli("codex", "mcp", "add", "ellie", "--", os.path.abspath(sys.executable), "-m", "ellie", "mcp")
        modify(config, upsert_codex)
        modify(codex_home() / "AGENTS.md", upsert_instructions)
        configure_hooks(codex_home() / "hooks.json", "codex")
        installed.append("Codex")
    if claude:
        config = guarded(claude_config())
        backup(config)
        run_cli("claude", "mcp", "remove", "--scope", "user", "ellie")
        run_cli("claude", "mcp", "add", "--scope", "user", "ellie", "--", os.path.abspath(sys.executable), "-m", "ellie", "mcp")
        def add(text):
            data = json.loads(text) if text.strip() else {}
            if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
                raise ValueError("Claude config and mcpServers must be JSON objects")
            entry = {"type": "stdio", "command": os.path.abspath(sys.executable), "args": ["-m", "ellie", "mcp"]}
            if data.get("mcpServers", {}).get("ellie") == entry:
                return text
            data.setdefault("mcpServers", {})["ellie"] = entry
            return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        modify(config, add)
        modify(claude_home() / "CLAUDE.md", upsert_instructions)
        configure_hooks(claude_home() / "settings.json", "claude")
        installed.append("Claude Code")
    store.ensure_resource("extraction.md", files("ellie").joinpath("resources/extraction.md").read_text(encoding="utf-8"))
    return installed


def uninstall() -> None:
    for path, agent in ((codex_home() / "hooks.json", "codex"), (claude_home() / "settings.json", "claude")):
        if path.exists():
            configure_hooks(path, agent, remove=True)
    config = guarded(codex_home() / "config.toml")
    backup(config)
    run_cli("codex", "mcp", "remove", "ellie")
    if config.exists():
        modify(config, strip_codex_table)
    modify(codex_home() / "AGENTS.md", strip_instructions, remove_empty=True)
    config = guarded(claude_config())
    backup(config)
    run_cli("claude", "mcp", "remove", "--scope", "user", "ellie")
    if config.exists():
        def remove(text):
            data = json.loads(text)
            if "ellie" not in data.get("mcpServers", {}):
                return text
            data["mcpServers"].pop("ellie")
            return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        modify(config, remove)
    modify(claude_home() / "CLAUDE.md", strip_instructions, remove_empty=True)
