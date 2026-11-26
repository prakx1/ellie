"""Codex rollout discovery and safely restricted fork command construction."""

from datetime import datetime
import json
import os
from pathlib import Path

from . import Discovery, Session, session_id, timestamp

REQUIRED_FLAGS = ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--output-schema", "--disable", "--skip-git-repo-check")


def root() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()


def paths():
    return sorted((root() / "sessions").glob("**/rollout-*.jsonl"))


def snapshot() -> dict:
    result = {}
    for path in paths():
        try:
            id = session_id(path.stem[-36:])
            stat = path.stat()
            result[id] = [stat.st_mtime_ns, stat.st_size]
        except (OSError, ValueError):
            continue
    return result


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block.get("text", "") for block in content if isinstance(block, dict) and isinstance(block.get("text", ""), str))
    return ""


def read(path: Path, include=None, *, limit_bytes: int | None = None) -> Session | None:
    with path.open(encoding="utf-8", newline="") as stream:
        first_line = next((line for line in stream if line.strip()), "{}")
        used_bytes = len(first_line.encode("utf-8"))
        first = json.loads(first_line)
        if first.get("type") != "session_meta" or not isinstance(first.get("payload"), dict):
            raise ValueError("missing session_meta header")
        meta = first["payload"]
        id = session_id(meta.get("id") or meta.get("session_id", ""))
        cwd = meta.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            raise ValueError("missing session cwd")
        if include is not None and not include(cwd):
            return None
        started = timestamp(meta.get("timestamp") or first.get("timestamp", ""))
        ended = started
        events, fallback = {}, []
        malformed = 0
        for line_number, line in enumerate(stream, 2):
            used_bytes += len(line.encode("utf-8"))
            if limit_bytes is not None and used_bytes > limit_bytes:
                break
            try:
                row = json.loads(line)
            except ValueError:
                malformed += 1
                continue
            if not isinstance(row, dict):
                continue
            try:
                ended = max(ended, timestamp(row["timestamp"]))
            except (KeyError, TypeError, ValueError):
                pass
            payload = row.get("payload", {})
            if not isinstance(payload, dict):
                continue
            if row.get("type") == "event_msg":
                if payload.get("type") == "user_message":
                    events[payload.get("id") or str(line_number)] = _text(payload.get("message", ""))
                elif payload.get("type") == "item_completed":
                    item = payload.get("item", {})
                    if isinstance(item, dict) and item.get("type") == "UserMessage":
                        events[item.get("id") or str(line_number)] = _text(item.get("content"))
            elif row.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "user":
                text = _text(payload.get("content"))
                if not text.lstrip().startswith(("<environment_context>", "<instructions>", "# AGENTS.md", "# Repository instructions")):
                    fallback.append(text)
        if malformed:
            raise ValueError(f"{malformed} malformed JSONL record(s); retry after the session finishes writing")
        prompts = list(events.values()) if events else fallback
        source = meta.get("source", "")
        return Session("codex", id, cwd, started, ended, path, len(prompts), prompts[0] if prompts else "", meta.get("history_base"), "subagent" in str(source).lower())


def discover(*, since: datetime | None = None, include=None) -> Discovery:
    result = Discovery()
    for path in paths():
        try:
            if since and path.stat().st_mtime < since.timestamp():
                continue
            session = read(path, include)
            if session is not None and not session.is_subagent:
                result.sessions.append(session)
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError) as exc:
            result.problems.append(f"Codex {path.name}: {exc}")
    return result


def find_ancestor(id: str, *, limit_bytes: int | None = None) -> Session:
    id = session_id(id)
    candidates = [*paths(), *(root() / "archived_sessions").glob("**/rollout-*.jsonl")]
    for path in candidates:
        if path.stem.endswith(id):
            if limit_bytes is not None and (limit_bytes <= 0 or limit_bytes > path.stat().st_size):
                raise ValueError("invalid or unavailable Codex history prefix")
            session = read(path, limit_bytes=limit_bytes)
            if session is not None and session.history_id == id:
                return session
    raise ValueError("missing Codex parent history: " + id)


def command(executable: str, id: str | None, directory: Path, schema: Path, output: Path, servers: list[str]) -> list[str]:
    args = [executable, "exec", "--cd", str(directory), "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--ignore-rules"]
    for feature in ("hooks", "plugins", "apps", "shell_tool", "multi_agent", "multi_agent_v2"):
        args.extend(["--disable", feature])
    for config in ('sandbox_mode="read-only"', 'approval_policy="never"', 'web_search="disabled"'):
        args.extend(["-c", config])
    # Ignoring user config removes transports, but disabled entries still need
    # valid ones. An inline TOML map also preserves dots/quotes in server names;
    # Codex's dotted -c keys do not parse quoted path segments as TOML keys.
    disabled = json.dumps(str(directory / "disabled-mcp"))
    entries = [json.dumps(server) + "={command=" + disabled + ",enabled=false}" for server in servers]
    if entries:
        args.extend(["-c", "mcp_servers={" + ",".join(entries) + "}"])
    args.extend(["--output-schema", str(schema), "-o", str(output)])
    return args + (["fork", session_id(id), "-"] if id else ["-"])
