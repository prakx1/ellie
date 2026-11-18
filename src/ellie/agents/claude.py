"""Claude's distributed JSONL metadata and tool-free fork commands."""

from datetime import datetime
import json
import os
from pathlib import Path

from . import Discovery, Session, session_id, timestamp

REQUIRED_FLAGS = ("--fork-session", "--no-session-persistence", "--json-schema", "--tools", "--strict-mcp-config", "--safe-mode")


def root() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).expanduser()


def paths():
    # Subagents have nested paths; they are not independent user sessions.
    return sorted((root() / "projects").glob("*/*.jsonl"))


def snapshot() -> dict:
    result = {}
    for path in paths():
        try:
            id = session_id(path.stem)
            info = path.stat()
            result[id] = [info.st_mtime_ns, info.st_size]
        except (OSError, ValueError):
            continue
    return result


def read(path: Path, include=None) -> Session | None:
    id = session_id(path.stem)
    cwd = None
    moments = []
    prompts = {}
    malformed = 0
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except ValueError:
                malformed += 1
                continue
            if not isinstance(row, dict) or row.get("sessionId") != id or row.get("isSidechain"):
                continue
            if cwd is None and isinstance(row.get("cwd"), str):
                cwd = row["cwd"]
                if include is not None and not include(cwd):
                    return None
            try:
                moments.append(timestamp(row["timestamp"]))
            except (KeyError, TypeError, ValueError):
                pass
            if row.get("type") != "user" or row.get("isMeta") or not isinstance(row.get("message"), dict):
                continue
            content = row["message"].get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                if any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
                    continue
                text = "\n".join(block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text")
            else:
                continue
            if text:
                prompts[row.get("uuid") or str(line_number)] = text
    if malformed:
        raise ValueError(f"{malformed} malformed JSONL record(s); retry after the session finishes writing")
    if not cwd or not moments:
        raise ValueError("missing session cwd or timestamps")
    texts = list(prompts.values())
    return Session("claude", id, cwd, min(moments), max(moments), path, len(texts), texts[0] if texts else "")


def discover(*, since: datetime | None = None, include=None) -> Discovery:
    result = Discovery()
    for path in paths():
        try:
            if since and path.stat().st_mtime < since.timestamp():
                continue
            session = read(path, include)
            if session is not None:
                result.sessions.append(session)
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError) as exc:
            result.problems.append(f"Claude {path.name}: {exc}")
    return result


def command(executable: str, id: str | None, schema: dict) -> list[str]:
    args = [executable, "-p", "--safe-mode", "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--disable-slash-commands", "--no-chrome", "--permission-prompts", "none", "--no-session-persistence",
            "--output-format", "json", "--json-schema", json.dumps(schema, separators=(",", ":"))]
    if id:
        args.extend(["--resume", session_id(id), "--fork-session"])
    return args
