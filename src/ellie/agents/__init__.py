"""Read-only adapters for agent-owned transcript formats."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import uuid


def timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing or invalid timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone() if parsed.tzinfo is None else parsed


def session_id(value: str) -> str:
    return str(uuid.UUID(value))


@dataclass
class Session:
    agent: str
    id: str
    cwd: str
    started: datetime
    ended: datetime
    path: Path
    user_messages: int
    first_user_message: str = ""
    history_base: dict | None = None
    is_subagent: bool = False

    @property
    def history_id(self) -> str:
        """Physical rollout identity; Codex branches can share a logical ID."""
        if self.agent == "codex":
            try:
                return session_id(self.path.stem[-36:])
            except ValueError:
                pass
        return self.id

    @property
    def version(self) -> list[int]:
        stat = self.path.stat()
        return [stat.st_mtime_ns, stat.st_size]


@dataclass
class Discovery:
    sessions: list[Session] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def adapter(agent: str):
    from . import claude, codex
    if agent == "codex":
        return codex
    if agent in {"claude", "claude-code"}:
        return claude
    raise ValueError("unsupported agent: " + agent)
