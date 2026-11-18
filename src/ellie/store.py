"""Storage boundary, atomic file persistence, and locked memory mutations."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable, Iterator, Protocol, TypeVar, runtime_checkable
import uuid

from .model import Item, Memory, MemoryMeta, normalized_title, stamp
from .paths import ellie_home, git_output, project_id, repo_root, validate_name, validate_project
from .redact import redact

T = TypeVar("T")


class ConcurrentUpdateError(ValueError):
    """A caller attempted to replace a memory that changed since it was read."""


class FileLock:
    def __init__(self, target: Path, *, timeout: float = 10, stale_after: float = 60):
        self.path = Path(str(target) + ".lock")
        self.timeout = timeout
        self.stale_after = stale_after
        self.identity: tuple[int, int] | None = None
        self._stop = threading.Event()
        self._heartbeat: threading.Thread | None = None

    def __enter__(self) -> FileLock:
        deadline = time.monotonic() + self.timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    info = self.path.lstat()
                    if time.time() - info.st_mtime > self.stale_after:
                        # Check again before removing a lock that may have been replaced.
                        current = self.path.lstat()
                        if (current.st_ino, current.st_mtime_ns) == (info.st_ino, info.st_mtime_ns):
                            self.path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for lock: {self.path.name}")
                time.sleep(min(0.025, max(0, deadline - time.monotonic())))
                continue
            try:
                info = os.fstat(fd)
                self.identity = (info.st_dev, info.st_ino)
                os.write(fd, json.dumps({"pid": os.getpid(), "token": uuid.uuid4().hex}).encode())
            finally:
                os.close(fd)
            self._stop.clear()
            self._heartbeat = threading.Thread(target=self._refresh, daemon=True)
            self._heartbeat.start()
            return self

    def _refresh(self) -> None:
        while not self._stop.wait(max(0.01, self.stale_after / 3)):
            try:
                info = self.path.lstat()
                if self.identity != (info.st_dev, info.st_ino):
                    return
                os.utime(self.path, None, follow_symlinks=False)
            except OSError:
                return

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._heartbeat:
            self._heartbeat.join()
        try:
            info = self.path.lstat()
            if self.identity == (info.st_dev, info.st_ino):
                self.path.unlink()
        except FileNotFoundError:
            pass


def _replace(path: Path, writer: Callable) -> None:
    """Caller holds the file lock. Failed writes leave the old file intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            if path.exists() and hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), path.stat().st_mode & 0o777)
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def atomic_write(path: Path, data: bytes) -> None:
    with FileLock(path):
        _replace(path, lambda stream: stream.write(data))


@runtime_checkable
class Store(Protocol):
    # root/path refer to per-device support/cache files, even for future backends.
    root: Path
    pending_problems: list[str]
    def list_projects(self) -> list[str]: ...
    def list_memories(self, project: str, archived: bool = False) -> list[MemoryMeta]: ...
    def read_memory(self, project: str, name: str) -> Memory: ...
    def write_memory(self, project: str, memory: Memory) -> None: ...
    def move_memory(self, project: str, name: str, to_archive: bool) -> None: ...
    def read_sessions(self, project: str) -> dict: ...
    def write_sessions(self, project: str, data: dict) -> None: ...
    def archive_transcript(self, project: str, src: Path, name: str, *, limit_bytes: int | None = None, filter_private: bool = False, start_byte: int = 0) -> str: ...
    def update_memory(self, project: str, name: str, change: Callable[[Memory], T], *, agent: str = "you") -> T: ...
    def read_local(self, name: str) -> dict: ...
    def update_local(self, name: str, change: Callable[[dict], T]) -> T: ...
    def create_memory(self, project: str, name: str, description: str = "", **kwargs) -> Memory: ...
    def ensure_project(self, project: str, *, agent: str = "you") -> Memory: ...
    def iter_memories(self, project: str) -> Iterator[Memory]: ...
    def add_item(self, project: str, memory: str, type: str, title: str, fields: dict[str, str], **kwargs) -> str: ...
    def get_item(self, project: str, id: str) -> tuple[str, Item]: ...
    def resolve(self, project: str, id: str, answer: str, **kwargs) -> None: ...
    def resolve_project(self, cwd: Path | str) -> tuple[str, Path]: ...
    def path(self, *parts: str) -> Path: ...
    def memory_version(self, project: str, name: str) -> tuple[int, int, bool]: ...
    def memory_versions(self) -> dict[tuple[str, str], tuple[int, int, bool]]: ...
    def subscribe(self, listener: Callable[[str, str], None]) -> None: ...
    def unsubscribe(self, listener: Callable[[str, str], None]) -> None: ...
    def read_pending(self, run: str) -> dict: ...
    def write_pending(self, run: str, data: dict) -> None: ...
    def update_pending(self, run: str, change: Callable[[dict], T]) -> T: ...
    def list_pending(self) -> list[dict]: ...
    def delete_pending(self, run: str) -> None: ...
    def finish_pending(self, run: str, generation: int = 0, *, keep: bool = False) -> bool: ...
    def worker_active(self, run: str, pid: int) -> bool: ...
    def update_sessions(self, project: str, change: Callable[[dict], T]) -> T: ...
    def ensure_resource(self, name: str, content: str) -> None: ...
    def read_resource(self, name: str, default: str = "") -> str: ...
    def read_archive_text(self, project: str, name: str, limit: int) -> str: ...
    def link(self, cwd: Path | str, project: str) -> None: ...
    def import_memory(self, project: str, source: Path, name: str, description: str | None = None) -> Memory: ...
    def edit_memory(self, project: str, name: str, editor: list[str]) -> None: ...
    def probe_writable(self) -> None: ...


class FileStore:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root).expanduser().resolve() if root is not None else ellie_home()
        nearest = self.root
        while not nearest.exists():
            nearest = nearest.parent
        if git_output(nearest, "rev-parse", "--show-toplevel"):
            raise ValueError("ELLIE_HOME must be outside a git repository")
        self._listeners: list[Callable[[str, str], None]] = []
        self.pending_problems: list[str] = []

    def path(self, *parts: str) -> Path:
        path = self.root.joinpath(*parts)
        try:
            path.resolve().relative_to(self.root)
        except ValueError:
            raise ValueError("store path escapes ELLIE_HOME") from None
        relative = path.relative_to(self.root)
        check = self.root
        for part in relative.parts:
            check = check / part
            if check.is_symlink():
                raise ValueError("symlinks are not allowed inside the memory store")
        return path

    def project_path(self, project: str) -> Path:
        return self.path("projects", validate_project(project))

    def memory_path(self, project: str, name: str, *, archived: bool | None = None) -> Path:
        validate_name(name)
        prefix = ("projects", validate_project(project))
        if name == "project":
            return self.path(*prefix, "project.md")
        active = self.path(*prefix, "memories", name + ".md")
        archive = self.path(*prefix, "archive", name + ".md")
        return archive if archived is True or (archived is None and not active.exists() and archive.exists()) else active

    @contextmanager
    def project_lock(self, project: str) -> Iterator[None]:
        key = hashlib.sha256(validate_project(project).encode()).hexdigest()
        with FileLock(self.path(".local", "locks", key)):
            yield

    def subscribe(self, listener: Callable[[str, str], None]) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[str, str], None]) -> None:
        self._listeners.remove(listener)

    def memory_version(self, project: str, name: str) -> tuple[int, int, bool]:
        path = self.memory_path(project, name)
        info = path.stat()
        return info.st_mtime_ns, info.st_size, path.parent.name == "archive"

    def memory_versions(self) -> dict[tuple[str, str], tuple[int, int, bool]]:
        return {(project, memory.name): self.memory_version(project, memory.name)
                for project in self.list_projects() for memory in self.iter_memories(project)}

    def _notify(self, project: str, name: str) -> None:
        saved = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        self.update_local("state", lambda data: data.setdefault("last_saved", {}).update({project: saved}))
        for listener in self._listeners:
            listener(project, name)

    def list_projects(self) -> list[str]:
        root = self.path("projects")
        if not root.exists():
            return []
        result = []
        for file in root.rglob("project.md"):
            self.path(str(file.relative_to(self.root)))
            result.append(validate_project(file.parent.relative_to(root).as_posix()))
        return sorted(result)

    def list_memories(self, project: str, archived: bool = False) -> list[MemoryMeta]:
        folder = self.path("projects", validate_project(project), "archive" if archived else "memories")
        result = []
        for file in sorted(folder.glob("*.md")):
            memory = self.read_memory(project, file.stem)
            meta = memory.meta
            result.append(MemoryMeta(file.stem, meta.get("description", ""), meta.get("status", "active"), meta.get("updated", ""), meta.get("updated_by", ""), archived))
        return result

    def iter_memories(self, project: str) -> Iterator[Memory]:
        if self.memory_path(project, "project").exists():
            yield self.read_memory(project, "project")
        for archived in (False, True):
            for meta in self.list_memories(project, archived):
                yield self.read_memory(project, meta.name)

    def read_memory(self, project: str, name: str) -> Memory:
        path = self.memory_path(project, name)
        memory = Memory.parse(path.read_bytes(), name=name)
        if memory.name != name:
            raise ValueError(f"memory filename and name disagree: {name}")
        return memory

    def _persist(self, path: Path, memory: Memory) -> None:
        # Redaction also covers hand-edited items on their next explicit save.
        for item in memory.items:
            safe = redact(item.raw)
            if safe != item.raw:
                item.raw = safe
                memory.replace_item(item)
        memory.text = redact(memory.text)
        data = memory.normalized_for_save()
        _replace(path, lambda stream: stream.write(data))
        memory.text = data.decode("utf-8")
        memory.original = data

    def write_memory(self, project: str, memory: Memory) -> None:
        with self.project_lock(project):
            path = self.memory_path(project, memory.name)
            if memory.name != "project":
                self._ensure_project(project, memory.meta.get("updated_by", "you"))
            with FileLock(path):
                if path.exists():
                    if memory.original is None or path.read_bytes() != memory.original:
                        raise ConcurrentUpdateError("memory changed; read it again before saving")
                elif memory.original is not None:
                    raise ConcurrentUpdateError("memory was removed or moved; read it again before saving")
                self._persist(path, memory)
            self._notify(project, memory.name)

    def _ensure_project(self, project: str, agent: str) -> None:
        path = self.memory_path(project, "project")
        if not path.exists():
            with FileLock(path):
                if not path.exists():
                    self._persist(path, Memory.new("project", agent=agent))

    def create_memory(self, project: str, name: str, description: str = "", *, agent: str = "you", goal: str = "", done_when: str = "") -> Memory:
        validate_name(name)
        with self.project_lock(project):
            path = self.memory_path(project, name)
            if path.exists():
                raise FileExistsError(f"memory already exists: {name}")
            self._ensure_project(project, agent)
            memory = Memory.new(name, redact(description), agent=agent, goal=redact(goal), done_when=redact(done_when))
            if name != "project":
                with FileLock(path):
                    self._persist(path, memory)
            else:
                memory = self.read_memory(project, "project")
            self._notify(project, "project")
            self._notify(project, name)
            return memory

    def ensure_project(self, project: str, *, agent: str = "you") -> Memory:
        with self.project_lock(project):
            self._ensure_project(project, agent)
        return self.read_memory(project, "project")

    def update_memory(self, project: str, name: str, change: Callable[[Memory], T], *, agent: str = "you") -> T:
        with self.project_lock(project):
            path = self.memory_path(project, name)
            with FileLock(path):
                memory = self.read_memory(project, name)
                result = change(memory)
                if memory.name != name:
                    raise ValueError("a memory mutation cannot rename the memory")
                memory.set_meta("updated", stamp())
                memory.set_meta("updated_by", agent)
                self._persist(path, memory)
            self._notify(project, name)
            return result

    def move_memory(self, project: str, name: str, to_archive: bool) -> None:
        validate_name(name, allow_project=False)
        with self.project_lock(project):
            src = self.memory_path(project, name, archived=not to_archive)
            dst = self.memory_path(project, name, archived=to_archive)
            with FileLock(src), FileLock(dst):
                if not src.exists():
                    raise FileNotFoundError(f"memory not found: {name}")
                if dst.exists():
                    raise FileExistsError(f"destination memory already exists: {name}")
                memory = Memory.parse(src.read_bytes(), name=name)
                memory.set_meta("status", "archived" if to_archive else "active")
                memory.set_meta("updated", stamp())
                os.replace(src, dst)
                self._persist(dst, memory)
            self._notify(project, name)

    def _read_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        data = json.loads(path.read_bytes())
        if not isinstance(data, dict):
            raise ValueError(f"expected a JSON object in {path.name}")
        return data

    def _update_json(self, path: Path, change: Callable[[dict], T]) -> T:
        with FileLock(path):
            data = self._read_json(path)
            result = change(data)
            payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            _replace(path, lambda stream: stream.write(payload))
            return result

    def read_local(self, name: str) -> dict:
        validate_name(name)
        return self._read_json(self.path(".local", name + ".json"))

    def read_pending(self, run: str) -> dict:
        return self._read_json(self.path(".local", "pending", validate_name(run) + ".json"))

    def write_pending(self, run: str, data: dict) -> None:
        atomic_write(self.path(".local", "pending", validate_name(run) + ".json"), (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())

    def update_pending(self, run: str, change: Callable[[dict], T]) -> T:
        return self._update_json(self.path(".local", "pending", validate_name(run) + ".json"), change)

    def update_local(self, name: str, change: Callable[[dict], T]) -> T:
        validate_name(name)
        return self._update_json(self.path(".local", name + ".json"), change)

    def ensure_resource(self, name: str, content: str) -> None:
        path = self.path(validate_name(name))
        with FileLock(path):
            if not path.exists():
                _replace(path, lambda stream: stream.write(content.encode("utf-8")))

    def read_resource(self, name: str, default: str = "") -> str:
        path = self.path(validate_name(name))
        return path.read_bytes().decode("utf-8") if path.exists() else default

    def list_pending(self) -> list[dict]:
        self.pending_problems = []
        records = []
        for path in sorted(self.path(".local", "pending").glob("*.json")):
            try:
                validate_name(path.stem)
                records.append({**self._read_json(self.path(".local", "pending", path.name)), "run_id": path.stem})
            except (ValueError, OSError) as exc:
                self.pending_problems.append(path.name + ": " + str(exc))
        return records

    def probe_writable(self) -> None:
        path = self.path(".local", "doctor-" + uuid.uuid4().hex)
        with FileLock(path):
            _replace(path, lambda stream: stream.write(b""))
            path.unlink()

    def quarantine_index(self) -> None:
        """Keep a corrupt rebuildable cache for diagnosis; never touch memories."""
        path = self.path(".local", "index.db")
        with FileLock(path):
            tag = ".corrupt-" + uuid.uuid4().hex
            for suffix in ("", "-wal", "-shm"):
                source = self.path(".local", "index.db" + suffix)
                if source.exists():
                    os.replace(source, self.path(".local", "index.db" + tag + suffix))

    def delete_pending(self, run: str) -> None:
        path = self.path(".local", "pending", validate_name(run) + ".json")
        with FileLock(path):
            path.unlink(missing_ok=True)

    def finish_pending(self, run: str, generation: int = 0, *, keep: bool = False) -> bool:
        """A worker may acknowledge its generation, never a newer queued checkpoint."""
        path = self.path(".local", "pending", validate_name(run) + ".json")
        with FileLock(path):
            job = self._read_json(path)
            if keep or job.get("generation", 0) > generation:
                if job:
                    job.update({"capture": "pending", "error": None, "not_before": 0})
                    _replace(path, lambda stream: stream.write((json.dumps(job, ensure_ascii=False, indent=2) + "\n").encode()))
                return False
            path.unlink(missing_ok=True)
            return True

    def worker_active(self, run: str, pid: int) -> bool:
        path = self.path(".local", "workers", validate_name(run) + ".lock")
        try:
            if time.time() - path.stat().st_mtime > 60:
                return False
            return self._read_json(path).get("pid") == pid
        except (OSError, ValueError):
            return False

    def resolve_project(self, cwd: Path | str) -> tuple[str, Path]:
        return project_id(cwd, self.read_local("paths"))

    def link(self, cwd: Path | str, project: str) -> None:
        if validate_project(project) not in self.list_projects():
            raise ValueError("link target must be an existing project")
        root = str(repo_root(cwd))
        self.update_local("paths", lambda data: data.update({root: project}))

    def import_memory(self, project: str, source: Path, name: str, description: str | None = None) -> Memory:
        content = source.read_text(encoding="utf-8")
        if description is None:
            description = next((line.strip() for line in content.splitlines() if line.strip()), "")
        self.create_memory(project, name, redact(description))
        fence = "`" * max(3, max((len(match.group()) + 1 for match in re.finditer(r"`+", content)), default=3))
        header = f"_Imported from {source.name} on {datetime.now().date().isoformat()}. The next handoff or capture will reorganise this._"
        def change(memory):
            memory.set_section("Current state", header + "\n\n" + fence + "markdown\n" + content.rstrip("\n") + "\n" + fence)
            memory.append_log("you", "import", "Imported " + source.name)
        self.update_memory(project, name, change)
        return self.read_memory(project, name)

    def edit_memory(self, project: str, name: str, editor: list[str]) -> None:
        with self.project_lock(project):
            path = self.memory_path(project, name)
            with FileLock(path):
                self.read_memory(project, name)
                result = subprocess.run([*editor, str(path)], cwd=self.root)
                if result.returncode:
                    raise ValueError(f"editor exited with status {result.returncode}")
                memory = self.read_memory(project, name)
                self._persist(path, memory)
            self._notify(project, name)

    def read_sessions(self, project: str) -> dict:
        return self._read_json(self.path("projects", validate_project(project), "sessions", "index.json"))

    def write_sessions(self, project: str, data: dict) -> None:
        if not isinstance(data, dict):
            raise ValueError("sessions must be a JSON object")
        path = self.path("projects", validate_project(project), "sessions", "index.json")
        atomic_write(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())

    def update_sessions(self, project: str, change: Callable[[dict], T]) -> T:
        return self._update_json(self.path("projects", validate_project(project), "sessions", "index.json"), change)

    def archive_transcript(self, project: str, src: Path, name: str, *, limit_bytes: int | None = None, filter_private: bool = False, start_byte: int = 0) -> str:
        if start_byte < 0:
            raise ValueError("transcript offset must not be negative")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+\.jsonl\.gz", name) or name.startswith("."):
            raise ValueError("invalid transcript archive name")
        dest = self.path("projects", validate_project(project), "sessions", name)
        with FileLock(dest):
            def copy(stream):
                with Path(src).open("rb") as source, gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as zipped:
                    source.seek(start_byte)
                    if filter_private:
                        from .privacy import filtered_line
                        remaining = limit_bytes
                        while remaining is None or remaining > 0:
                            line = source.readline(-1 if remaining is None else remaining)
                            if not line:
                                if remaining:
                                    raise ValueError("transcript prefix is incomplete")
                                break
                            zipped.write(filtered_line(line))
                            if remaining is not None:
                                remaining -= len(line)
                    elif limit_bytes is None:
                        shutil.copyfileobj(source, zipped)
                    else:
                        remaining = limit_bytes
                        while remaining:
                            chunk = source.read(min(65536, remaining))
                            if not chunk:
                                raise ValueError("transcript prefix is incomplete")
                            zipped.write(chunk)
                            remaining -= len(chunk)
            _replace(dest, copy)
        return name

    def read_archive_text(self, project: str, name: str, limit: int) -> str:
        path = self.path("projects", validate_project(project), "sessions", validate_name(name))
        with gzip.open(path, "rt", encoding="utf-8") as source:
            return source.read(limit)

    def get_item(self, project: str, id: str) -> tuple[str, Item]:
        if not re.fullmatch(r"[DRFQN][0-9]+", id):
            raise ValueError("invalid item id")
        found = [(memory.name, item) for memory in self.iter_memories(project) for item in memory.items if item.id == id]
        if not found:
            raise KeyError(id)
        if len(found) > 1:
            raise ValueError(f"duplicate project item id: {id}")
        return found[0]

    def _next_id(self, project: str, type: str) -> str:
        highest = max((int(item.id[1:]) for memory in self.iter_memories(project) for item in memory.items if item.type == type), default=0)
        def reserve(data):
            counters = data.setdefault("id_counters", {}).setdefault(project, {})
            counters[type] = max(counters.get(type, 0), highest) + 1
            return f"{type}{counters[type]}"
        return self.update_local("state", reserve)

    def add_item(self, project: str, memory: str, type: str, title: str, fields: dict[str, str], *, agent: str = "you", source: str = "live", session: str | None = None, body: str = "", supersedes: list[str] | None = None, dedupe: bool = False, retry_seconds: int = 600) -> str:
        if type not in "DRFQN" or len(type) != 1:
            raise ValueError("invalid item type")
        if type == "F" and fields.get("scope") == "project":
            memory = "project"
        if type == "F" and memory == "project":
            fields = {**fields, "scope": "project"}
        if source not in {"live", "auto", "manual", "import", "backfill"}:
            raise ValueError("invalid item source")
        with self.project_lock(project):
            target = self.read_memory(project, memory)
            duplicate = None
            for item in target.items:
                if item.type != type or normalized_title(item.title) != normalized_title(title):
                    continue
                if dedupe or self._recent_item(target, item.id, retry_seconds):
                    duplicate = item.id
                    break
            old_decisions = {}
            for old_id in supersedes or []:
                old_name, old = self.get_item(project, old_id)
                if type != "D" or old.type != "D":
                    raise ValueError("only decisions may supersede decisions")
                if old_id == duplicate:
                    raise ValueError("a decision cannot supersede itself")
                old_decisions[old_id] = old_name
            from .conversations import preserve_before_change, remember
            for old_id, old_name in old_decisions.items():
                preserve_before_change(self, project, old_name, self.get_item(project, old_id)[1])
            if duplicate:
                # Repair an interrupted cross-file supersede even on a retry.
                for old_id, old_name in old_decisions.items():
                    old_memory = self.read_memory(project, old_name)
                    old = old_memory.get_item(old_id)
                    if old.fields.get("status") != "superseded by " + duplicate:
                        old.set_field("status", "superseded by " + duplicate)
                        old_memory.replace_item(old)
                        with FileLock(self.memory_path(project, old_name)):
                            self._persist(self.memory_path(project, old_name), old_memory)
                        self._notify(project, old_name)
                remember(self, project, session, memory, self.get_item(project, duplicate)[1], preserve=True)
                for old_id, old_name in old_decisions.items():
                    remember(self, project, session, old_name, self.get_item(project, old_id)[1])
                return duplicate
            prepared = {"date": datetime.now().astimezone().date().isoformat(), "source": f"{agent} · {source}" + (f" · session {session}" if session else ""), **fields}
            if supersedes:
                prepared["supersedes"] = " · ".join(supersedes)
            # Validate before reserving an ID or touching memory files.
            item = Item.create(type + "0", title, prepared, body)
            id = self._next_id(project, type)
            item.raw = item.raw.replace(type + "0", id, 1)
            target.add_item(item)
            target.append_log(agent, {"D": "decision", "R": "result", "F": "finding", "Q": "question", "N": "note"}[type], id + " " + title, session)
            changed = {memory: target}
            for old_id, old_name in old_decisions.items():
                old_memory = changed.setdefault(old_name, self.read_memory(project, old_name))
                old = old_memory.get_item(old_id)
                old.set_field("status", "superseded by " + id)
                old_memory.replace_item(old)
            for name, changed_memory in changed.items():
                changed_memory.set_meta("updated", stamp())
                changed_memory.set_meta("updated_by", agent)
                path = self.memory_path(project, name)
                with FileLock(path):
                    if path.read_bytes() != changed_memory.original:
                        raise ConcurrentUpdateError("memory changed during item creation")
                    self._persist(path, changed_memory)
                self._notify(project, name)
            remember(self, project, session, memory, self.get_item(project, id)[1])
            for old_id, old_name in old_decisions.items():
                remember(self, project, session, old_name, self.get_item(project, old_id)[1])
            return id

    @staticmethod
    def _recent_item(memory: Memory, id: str, seconds: int) -> bool:
        for line in reversed(memory.get_section("Log").splitlines()):
            if not re.search(r" · (?:decision|result|finding|question|note): " + re.escape(id) + r"(?:\s|$)", line):
                continue
            try:
                created = datetime.strptime(line[2:18], "%Y-%m-%d %H:%M").astimezone()
                age = (datetime.now().astimezone() - created).total_seconds()
                return 0 <= age <= seconds
            except ValueError:
                continue
        return False

    def resolve(self, project: str, id: str, answer: str, *, agent: str = "you", session: str | None = None) -> None:
        with self.project_lock(project):
            name, item = self.get_item(project, id)
            if item.type != "Q":
                raise ValueError("only questions can be resolved")
            from .conversations import preserve_before_change, remember
            preserve_before_change(self, project, name, item)
            path = self.memory_path(project, name)
            with FileLock(path):
                memory = self.read_memory(project, name)
                item = memory.get_item(id)
                item.set_field("status", "resolved")
                item.set_field("answer", redact(answer))
                memory.replace_item(item)
                memory.append_log(agent, "question", id + " resolved: " + redact(answer), session)
                memory.set_meta("updated", stamp())
                memory.set_meta("updated_by", agent)
                self._persist(path, memory)
            self._notify(project, name)
            remember(self, project, session, name, self.get_item(project, id)[1])
