"""Session matching, durable jobs, background extraction, and idempotent merging."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid

from .agents import Discovery, Session, adapter, timestamp
from .extract import extract, target_memory
from .model import normalized_title
from .paths import project_id
from .redact import redact
from .service import DEFAULTS
from .store import FileLock, FileStore


def cutoff(window: str) -> datetime:
    match = re.fullmatch(r"([1-9][0-9]*)([dhw])", window)
    if not match:
        raise ValueError("time windows use a positive count followed by d, h, or w")
    number = int(match.group(1))
    return datetime.now().astimezone() - timedelta(seconds=number * {"h": 3600, "d": 86400, "w": 604800}[match.group(2)])


def snapshot_sessions(agent: str) -> dict:
    return adapter(agent).snapshot()


def discover_project(store, project: str, *, agent: str | None = None, since: datetime | None = None) -> Discovery:
    links = store.read_local("paths")
    membership = {}
    def include(cwd):
        if cwd not in membership:
            membership[cwd] = project_id(cwd, links)[0] == project
        return membership[cwd]
    result = Discovery()
    for name in ([agent] if agent else ["codex", "claude"]):
        found = adapter(name).discover(since=since, include=include)
        result.sessions.extend(found.sessions)
        result.problems.extend(found.problems)
    result.sessions.sort(key=lambda session: (session.started, session.agent, session.id))
    return result


def captured(session: Session, registry: dict) -> bool:
    record = registry.get(session.id, {})
    return record.get("capture") in {"done", "skipped"} and record.get("source_version") == session.version


def match_session(job: dict, sessions: list[Session], preferred: str | None = None) -> Session:
    agent = "claude" if job["agent"] == "claude-code" else job["agent"]
    candidates = [s for s in sessions if s.agent == agent]
    if job.get("session_id"):
        candidates = [s for s in candidates if s.id == job["session_id"]]
    else:
        started = timestamp(job["started"])
        before = job.get("before_sessions", {})
        candidates = [s for s in candidates if s.version != before.get(s.id)
                      and s.ended >= started - timedelta(seconds=5)
                      and Path(s.cwd).resolve() == Path(job["cwd"]).resolve()]
    if preferred:
        candidates = [s for s in candidates if s.id == preferred]
    if len(candidates) != 1:
        raise ValueError("session not found" if not candidates else "ambiguous session match; use ellie capture --session ID")
    return candidates[0]


def uncaptured_status(store, project: str) -> dict:
    found = discover_project(store, project, since=cutoff("7d"))
    registry = store.read_sessions(project)
    sessions = {s.id: s for s in found.sessions if not captured(s, registry)}
    pending = [job for job in store.list_pending() if job.get("project") == project]
    unknown = 0
    extra_ids = set()
    active_ids = set()
    for job in pending:
        if not job.get("ended"):
            try:
                active = match_session(job, found.sessions)
                sessions.pop(active.id, None)
                active_ids.add(active.id)
            except ValueError:
                pass
        elif job.get("session_id") not in sessions:
            try:
                match_session(job, found.sessions)
            except ValueError:
                if job.get("session_id"):
                    extra_ids.add(job["session_id"])
                elif not any(s.agent == job.get("agent") and s.cwd == job.get("cwd") for s in found.sessions):
                    unknown += 1
    missing = {id for id, record in registry.items() if record.get("capture") not in {"done", "skipped"} and id not in sessions}
    return {"uncaptured_sessions": len((set(sessions) | missing | extra_ids) - active_ids) + unknown,
            "capture_jobs": [{key: job.get(key) for key in ("run_id", "capture", "error")} for job in pending],
            "discovery_warnings": found.problems}


def _line(text: str) -> str:
    return " ".join(redact(text).split())


def _live_handoff(memory, job: dict, session: Session) -> bool:
    start = timestamp(job.get("started") or session.started.isoformat())
    mark = job.get("live_handoffs", {}).get(memory.name)
    if mark:
        try:
            if timestamp(mark) >= start:
                return True
        except ValueError:
            pass
    floor = start.replace(second=0, microsecond=0)
    for line in memory.get_section("Log").splitlines():
        if " · handoff:" not in line or " · session " + session.id not in line or " · capture " in line:
            continue
        try:
            if timestamp(line[2:18]) >= floor:
                return True
        except ValueError:
            continue
    return False


def merge(store, project: str, session: Session, job: dict, value: dict) -> tuple[list[str], str]:
    ids = list(job.get("live_items", []))
    target, new = target_memory(value, job.get("memories", []))
    bound = job.get("bound_memories")
    if bound is not None and target not in bound and target != "project":
        raise ValueError("capture target is outside the conversation's bound workstreams")
    if not value["worthwhile"]:
        return ids, job.get("memories", ["project"])[0] if job.get("memories") else "project"
    actor = "claude-code" if session.agent == "claude" else "codex"
    source = job.get("source", "auto")
    if new:
        try:
            store.create_memory(project, target, _line(value["target_memory"]["new_description"] or ""), agent=actor)
        except FileExistsError:
            pass
    fallback = not job.get("memories") and not value["target_memory"]["existing"] and not value["target_memory"]["new_name"]
    for key, type in (("decisions", "D"), ("results", "R"), ("findings", "F"), ("questions", "Q"), ("notes", "N")):
        for record in value[key]:
            destination = record["memory"] or target
            if bound is not None and destination not in bound and not (type == "F" and record.get("scope") == "project") and destination != "project":
                raise ValueError("capture item is outside the conversation's bound workstreams")
            if fallback and type not in {"D", "F"}:
                continue
            title = _line(record.get("title", record.get("text", "")))
            fields = {}
            body = ""
            supersedes = None
            if type == "D":
                fields = {"status": "active", "options": " · ".join(map(_line, record["options"])), **{key: _line(record[key]) for key in ("chosen", "tradeoff", "why")}}
                supersedes = record["supersedes"]
            elif type == "R":
                fields = {key: _line(record[key]) for key in ("outcome", "what", "evidence")}
            elif type == "F":
                fields = {key: _line(record[key]) for key in ("detail", "evidence", "scope")}
                if fields["scope"] == "project":
                    destination = "project"
            elif type == "Q":
                fields = {"status": "open"}
            else:
                title = _line(record["text"])[:120]
                body = redact(record["text"])
                if re.search(r"(?m)^\s*#{2,3}\s", body):
                    fence = "`" * max(3, max((len(m.group()) + 1 for m in re.finditer(r"`+", body)), default=3))
                    body = fence + "text\n" + body + "\n" + fence + "\n"
            if record.get("refs"):
                fields["refs"] = " · ".join(map(_line, record["refs"]))
            id = store.add_item(project, destination, type, title, fields, body=body, supersedes=supersedes,
                                agent=actor, source=source, session=session.id, dedupe=True)
            ids.append(id)
    for resolution in value["resolved_questions"]:
        id, answer = resolution["id"], _line(resolution["answer"])
        item = store.get_item(project, id)[1]
        if item.fields.get("status") != "resolved" or item.fields.get("answer") != answer:
            store.resolve(project, id, answer, agent=actor, session=session.id)
        ids.append(id)
    if target != "project":
        def handoff(memory):
            if value["goal"] is not None:
                goal = redact(value["goal"]["text"]) + "\n\n**Done when:** " + redact(value["goal"]["done_when"])
                if memory.get_section("Goal").strip() != goal.strip():
                    memory.set_section("Goal", goal)
                    memory.append_log(actor, "goal", _line(value["goal"]["text"]), session.id)
            if value["state"] is not None and not _live_handoff(memory, job, session):
                memory.set_section("Current state", redact(value["state"]["current_state"]))
                memory.set_section("Next steps", redact(value["state"]["next_steps"]))
            memory.append_log(actor, "handoff", _line(value["session_summary"]) + " · capture " + source, session.id)
        store.update_memory(project, target, handoff, agent=actor)
    elif value["session_summary"]:
        store.update_memory(project, target, lambda memory: memory.append_log(actor, "handoff", _line(value["session_summary"]) + " · capture " + source, session.id), agent=actor)
    from .conversations import save_sections
    sections = {}
    if value["goal"] and target != "project":
        sections["Goal"] = value["goal"]["text"] + "\n\n**Done when:** " + value["goal"]["done_when"]
    if value["state"] and target != "project" and not _live_handoff(store.read_memory(project, target), job, session):
        sections.update({"Current state": value["state"]["current_state"], "Next steps": value["state"]["next_steps"]})
    save_sections(store, project, session.id, target, sections, value["session_summary"])
    return list(dict.fromkeys(ids)), target


def _archives(store, project: str, session: Session, *, enabled=True, primary_size=None, start_byte=None) -> tuple[str | None, list[dict], list[Session]]:
    primary = f"{session.started.astimezone().date().isoformat()}_{session.agent}_{session.id}.jsonl.gz"
    if start_byte is not None:
        primary = primary.replace(".jsonl.gz", f"_part-{start_byte}-{primary_size}.jsonl.gz")
    ancestry, parents = [], []
    base = session.history_base if not start_byte else None
    seen = {session.id}
    while base:
        if not isinstance(base, dict) or "thread_id" not in base:
            raise ValueError("unsupported Codex parent-history reference")
        if base["thread_id"] in seen or len(seen) > 50:
            raise ValueError("cyclic or excessive Codex history ancestry")
        seen.add(base["thread_id"])
        size = base.get("end_byte_offset")
        if isinstance(size, bool) or not isinstance(size, int):
            raise ValueError("Codex history prefix has no supported byte boundary")
        parent = adapter("codex").find_ancestor(base["thread_id"], limit_bytes=size)
        name = f"{parent.started.astimezone().date().isoformat()}_codex_{parent.id}_prefix-{size}.jsonl.gz"
        if enabled:
            store.archive_transcript(project, parent.path, name, limit_bytes=size, filter_private=True)
        ancestry.append({**base, "archive": name if enabled else None})
        parents.append(parent)
        base = parent.history_base
    if enabled:
        count = primary_size - (start_byte or 0) if primary_size is not None else None
        store.archive_transcript(project, session.path, primary, limit_bytes=count, start_byte=start_byte or 0, filter_private=True)
    return primary if enabled else None, ancestry, parents


def _summary(store, project: str, target: str, ids: list[str]) -> str:
    counts = Counter(id[0] for id in ids)
    names = {"D": "decision", "R": "result", "F": "finding", "Q": "question", "N": "note"}
    parts = []
    for key, label in names.items():
        if key == "R":
            outcomes = Counter(store.get_item(project, id)[1].fields.get("outcome", "worked") for id in ids if id.startswith("R"))
            for outcome in ("failed", "partial", "worked"):
                count = outcomes[outcome]
                if count:
                    parts.append(f"{count} {outcome} result{'s' if count != 1 else ''}")
        elif counts[key]:
            parts.append(f"{counts[key]} {label}{'s' if counts[key] != 1 else ''}")
    return f"Captured {target}: " + (", ".join(parts) if parts else "no durable items") + "."


def process_job(store, run_id: str) -> dict:
    try:
        lock = FileLock(store.path(".local", "jobs", run_id), timeout=0)
        lock.__enter__()
    except TimeoutError:
        return {"capture": "running", "run_id": run_id}
    try:
        job = store.read_pending(run_id)
        if not job:
            return {"capture": "done", "run_id": run_id}
        project = job["project"]
        generation = job.get("generation", 0)
        from .privacy import blocked, needs_filtering, policy, read_chunk
        reason = blocked(store, project, job.get("session_id"))
        if reason:
            store.update_pending(run_id, lambda current: current.update({"capture": "paused", "error": reason}))
            return {"capture": "paused", "run_id": run_id, "error": reason}
        session = None
        try:
            if job.get("transcript_path"):
                from .hooks import transcript_path
                path = transcript_path(job["agent"], job["transcript_path"])
                candidate = adapter(job["agent"]).read(path)
                if candidate is None or store.resolve_project(candidate.cwd)[0] != project:
                    raise ValueError("hook transcript does not belong to this project")
                found = Discovery([candidate])
            else:
                found = discover_project(store, project)
            session = match_session(job, found.sessions)
            job["session_id"] = session.id
            store.update_pending(run_id, lambda current: current.update({"session_id": session.id, "capture": "running", "error": None}))
            with FileLock(store.path(".local", "sessions", session.agent + "-" + session.id), timeout=0):
                registry = store.read_sessions(project)
                if captured(session, registry):
                    store.finish_pending(run_id, generation)
                    return {"capture": registry[session.id]["capture"], "session_id": session.id}
                version = session.version
                transcript, offset = None, None
                if job.get("incremental"):
                    offset = registry.get(session.id, {}).get("source_version", [0, 0])[1]
                    if offset > version[1]:
                        offset = 0
                    transcript, end = read_chunk(session.path, offset, upto=version[1])
                    version = [version[0], end]
                    transcript = f"Conversation {session.id}; new activity from source byte {offset}.\n" + transcript
                store.ensure_project(project)
                store.update_sessions(project, lambda data: data.setdefault(session.id, {}).update({"capture": "running", "agent": session.agent}))
                archive, ancestry, parents = _archives(store, project, session, enabled=policy(store, project)["archives"] != "off", primary_size=version[1], start_byte=offset)
                if offset:
                    ancestry = registry.get(session.id, {}).get("ancestry", [])
                store.update_sessions(project, lambda data: data[session.id].update({"archive": archive, "ancestry": ancestry}))
                if session.user_messages + sum(parent.user_messages for parent in parents) < 2 and not job.get("incremental"):
                    ids, target, status = [], "project", "skipped"
                else:
                    config = {**DEFAULTS, **store.read_local("config")}
                    config["context_conversations"] = job.get("context_conversations")
                    config["bound_memories"] = job.get("bound_memories")
                    config["current_session"] = session.id
                    filtered = False if job.get("incremental") else needs_filtering(session.path, version[1]) or any(needs_filtering(parent.path, entry["end_byte_offset"]) for parent, entry in zip(parents, ancestry))
                    if not job.get("incremental") and (filtered or config["extract_with"] not in {"same", session.agent}):
                        pieces = []
                        size = 0
                        for source, boundary in [*[(parent, entry["end_byte_offset"]) for parent, entry in reversed(list(zip(parents, ancestry)))], (session, version[1])]:
                            piece, _ = read_chunk(source.path, upto=boundary, max_bytes=boundary)
                            size += len(piece)
                            if size > 2_000_000:
                                raise ValueError("cross-agent transcript exceeds 2000000 characters; use extract_with=same")
                            pieces.append(piece)
                        transcript = "\n".join(pieces)
                    value = extract(session, store, project, job.get("memories", []), config, transcript=transcript)
                    # Fetch live handoff markers again after the model returns.
                    job = {**job, **store.read_pending(run_id)}
                    reason = blocked(store, project, session.id)
                    if reason:
                        raise ValueError(reason)
                    ids, target = merge(store, project, session, job, value)
                    status = "done"
                def record(data):
                    from .conversations import now
                    previous = data.get(session.id, {})
                    data[session.id] = {**previous, "agent": session.agent, "started": session.started.isoformat(),
                        "ended": job.get("ended") or session.ended.isoformat(), "cwd": session.cwd,
                        "memories": job.get("memories") or ([target] if target != "project" else []),
                        "launched_by": job.get("launched_by", "ellie"), "capture": status,
                        "items": list(dict.fromkeys([*previous.get("items", []), *ids])),
                        "archive": archive, "ancestry": ancestry, "source_version": version,
                        "title": previous.get("title") or _line(session.first_user_message)[:140],
                        "last_capture": now(), "filtered_archive": True}
                    data[session.id].pop("error", None)
                    if job.get("incremental") and archive:
                        parts = data[session.id].setdefault("archive_parts", [])
                        if not any(part["archive"] == archive for part in parts):
                            parts.append({"archive": archive, "start": offset, "end": version[1]})
                store.update_sessions(project, record)
                from .conversations import remember
                for id in ids:
                    name, item = store.get_item(project, id)
                    remember(store, project, session.id, name, item)
                summary = _summary(store, project, target, ids)
                if status == "done":
                    store.update_local("state", lambda data: data.setdefault("capture_summaries", {}).setdefault(project, []).append(summary))
                more = not store.finish_pending(run_id, generation, keep=bool(job.get("incremental") and session.version != version))
                return {"capture": status, "session_id": session.id, "items": ids, "summary": summary, "more": more}
        except TimeoutError:
            return {"capture": "running", "run_id": run_id}
        except Exception as exc:
            message = redact(str(exc))
            store.update_pending(run_id, lambda current: current.update({"capture": "failed", "error": message}))
            if session is not None:
                store.update_sessions(project, lambda data: data.setdefault(session.id, {}).update({"capture": "failed", "error": message}))
            return {"capture": "failed", "run_id": run_id, "error": message}
    finally:
        lock.__exit__(None, None, None)


def drain_job(store, run_id: str) -> dict:
    """Coalesce checkpoints and retry failures a bounded number of times in a child."""
    try:
        with FileLock(store.path(".local", "workers", run_id), timeout=0):
            def mark(job):
                if not job:
                    raise FileNotFoundError(run_id)
                job["worker_pid"] = os.getpid()
            store.update_pending(run_id, mark)
            while True:
                job = store.read_pending(run_id)
                if not job:
                    return {"capture": "done"}
                delay = job.get("not_before", 0) - time.time()
                if delay > 0:
                    time.sleep(min(delay, 1))
                    continue
                result = process_job(store, run_id)
                if result["capture"] == "failed":
                    attempts = job.get("attempts", 0) + 1
                    store.update_pending(run_id, lambda current: current.update({"attempts": attempts, "not_before": time.time() + 2 ** attempts}))
                    if attempts >= 3:
                        return result
                elif result["capture"] in {"paused", "running"} or not store.read_pending(run_id):
                    return result
    except (TimeoutError, FileNotFoundError):
        return {"capture": "running"}


def start_background(store, run_id: str) -> subprocess.Popen:
    log = store.path(".local", "logs", run_id + ".log")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as output:
        process = subprocess.Popen([sys.executable, "-m", "ellie", "_capture", run_id], cwd=store.root,
                                   env={**os.environ, "ELLIE_HOME": str(store.root)}, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
    # Reap children while the parent remains alive; daemon threads never delay CLI exit.
    threading.Thread(target=process.wait, daemon=True).start()
    return process


def plan_jobs(store, project: str, *, since: str = "7d", session_id: str | None = None, source: str = "auto", agent: str | None = None) -> tuple[list[dict], list[str]]:
    found = discover_project(store, project, agent=agent)
    registry = store.read_sessions(project)
    all_pending = [job for job in store.list_pending() if job.get("project") == project]
    pending = [job for job in all_pending if job.get("ended")]
    jobs, claimed, errors = [], set(), []
    for job in all_pending:
        if not job.get("ended"):
            try:
                claimed.add(match_session(job, found.sessions).id)
            except ValueError:
                pass
    for job in pending:
        if session_id and job.get("session_id") not in (None, session_id):
            continue
        try:
            session = match_session(job, found.sessions, session_id)
            jobs.append({**job, "session_id": session.id})
            claimed.add(session.id)
        except ValueError as exc:
            if not session_id:
                errors.append(f"{job['run_id']}: {exc}")
    earliest = cutoff(since)
    for session in found.sessions:
        if session.id in claimed or captured(session, registry) or (session_id and session.id != session_id):
            continue
        if session.path.stat().st_mtime < earliest.timestamp() and not session_id:
            continue
        run_id = str(uuid.uuid4())
        jobs.append({"run_id": run_id, "project": project, "agent": session.agent, "session_id": session.id,
                     "cwd": session.cwd, "started": session.started.isoformat(), "ended": session.ended.isoformat(),
                     "memories": [], "capture": "pending", "launched_by": "external", "source": source})
    if session_id and not jobs and not any(session.id == session_id for session in found.sessions):
        errors.append("session not found for this project: " + session_id)
    return jobs, errors
