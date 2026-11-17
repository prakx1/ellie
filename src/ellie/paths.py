"""Project identity and path validation. Git is queried, never modified."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit


def ellie_home() -> Path:
    return Path(os.environ.get("ELLIE_HOME", "~/.ellie")).expanduser().resolve()


def validate_project(project: str) -> str:
    if not isinstance(project, str) or not project:
        raise ValueError("project id must not be empty")
    parts = project.split("/")
    if any(p in ("", ".", "..") or not re.fullmatch(r"[a-z0-9._-]+", p) for p in parts):
        raise ValueError("invalid project id")
    return project


def validate_name(name: str, *, allow_project: bool = True) -> str:
    if not isinstance(name, str) or name in ("", ".", ".."):
        raise ValueError("memory name must not be empty or a dot segment")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name):
        raise ValueError("memory names must start with a-z or 0-9 and contain only a-z, 0-9, '.', '_', '-'")
    if name == "project" and not allow_project:
        raise ValueError("project is reserved for the shared memory")
    return name


def _segment(value: str) -> str:
    value = unquote(value).lower()
    if value in (".", ".."):
        raise ValueError("dot segments are not allowed in project ids")
    value = re.sub(r"[^a-z0-9._-]", "-", value)
    if not value or value in (".", ".."):
        raise ValueError("empty or invalid project path segment")
    return value


def normalize_remote(remote: str) -> str:
    """Remove credentials, transport, port and .git from a remote URL."""
    remote = remote.strip()
    if not remote:
        raise ValueError("empty git remote")
    if "://" in remote:
        parsed = urlsplit(remote)
        host = parsed.hostname or ""
        path = parsed.path
    else:
        match = re.fullmatch(r"(?:[^/@]+@)?([^/:]+):(.+)", remote)
        if match:
            host, path = match.groups()
        else:
            host, _, path = remote.partition("/")
            host = host.rsplit("@", 1)[-1]
    path = path.strip("/")
    if path.lower().endswith(".git"):
        path = path[:-4]
    parts = ([host] if host else []) + path.split("/")
    return validate_project("/".join(_segment(part) for part in parts))


def git_output(cwd: Path, *args: str) -> str | None:
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(key, None)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(cwd), *args],
            env=env, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def repo_root(cwd: Path | str) -> Path:
    cwd = Path(cwd).expanduser().resolve()
    root = git_output(cwd, "rev-parse", "--show-toplevel")
    return Path(root).resolve() if root else cwd


def project_id(cwd: Path | str, links: dict[str, str] | None = None) -> tuple[str, Path]:
    root = repo_root(cwd)
    if links and str(root) in links:
        return validate_project(links[str(root)]), root
    remote = git_output(root, "remote", "get-url", "origin")
    project = normalize_remote(remote) if remote else "local/" + _segment(root.name)
    return validate_project(project), root
