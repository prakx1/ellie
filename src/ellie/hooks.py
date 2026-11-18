"""Small lifecycle handlers: bind, inject compact context, durably queue work."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time

from .agents import adapter
from .conversations import list_conversations, now, render_selected, validate_id
from .privacy import blocked
from .redact import redact

EVENTS = ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "SessionEnd", "PreCompact")


def transcript_path(agent: str, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    root = adapter(agent).root().resolve()
    roots = [root / "sessions", root / "archived_sessions"] if agent == "codex" else [root / "projects"]
    if not any(path.is_relative_to(folder) for folder in roots) or path.suffix != ".jsonl":
        raise ValueError("hook transcript must be in the agent's session directory")
    return path


def _worker_alive(job):
    pid = job.get("worker_pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def enqueue(store, project, session, agent, cwd, path, event, payload, *, start_worker=True):
    from .capture import start_background
    from .service import DEFAULTS
    config = {**DEFAULTS, **store.read_local("config")}
    if config["capture"] != "auto" or blocked(store, project, session):
        return None
    record = store.read_sessions(project)[session]
    if record.get("capture_disabled"):
        return None
    run = "hook-" + agent + "-" + hashlib.sha256(session.encode()).hexdigest()[:32]
    version = None
    if path and path.exists():
        stat = path.stat()
        version = [stat.st_mtime_ns, stat.st_size]
    signature = hashlib.sha256(json.dumps([event, payload.get("turn_id"), payload.get("tool_use_id"), version], sort_keys=True).encode()).hexdigest()
    force = event in {"Stop", "SessionEnd", "PreCompact", "Interrupt"}
    clock = time.time()
    def change(job):
        if not job:
            job.update({"run_id": run, "project": project, "agent": agent, "session_id": session,
                        "cwd": cwd, "started": record.get("started", now()), "capture": "pending",
                        "launched_by": "hooks", "incremental": True, "source": "auto",
                        "not_before": clock + config["checkpoint_interval_sec"]})
        events = job.setdefault("event_ids", [])
        if signature not in events:
            events.append(signature)
            job["event_ids"] = events[-256:]
            job["generation"] = job.get("generation", 0) + 1
            job["attempts"] = 0
        job.update({"memories": record.get("bound_memories", record.get("memories", [])),
                    "bound_memories": record.get("bound_memories"),
                    "context_conversations": record.get("context_conversations"),
                    "transcript_path": str(path) if path else None, "requested_version": version})
        if force:
            job["not_before"] = clock
        if event == "SessionEnd":
            job["ended"] = now()
        launch = not _worker_alive(job) and clock - job.get("dispatch_at", 0) > 2
        if launch and start_worker:
            job["dispatch_at"] = clock
        return launch
    launch = store.update_pending(run, change)
    if launch and start_worker:
        start_background(store, run)
    return run


def _bind(store, project, session, agent, payload):
    record = store.read_sessions(project).get(session, {})
    launcher = store.read_pending(os.environ["ELLIE_RUN_ID"]) if os.environ.get("ELLIE_RUN_ID") else {}
    memories = record.get("bound_memories")
    if memories is None:
        memories = launcher.get("memories") or ["chat-" + session.lower()]
        for name in memories:
            try:
                store.read_memory(project, name)
            except FileNotFoundError:
                store.create_memory(project, name, "Conversation " + session[:12], agent=agent)
    def change(data):
        current = data.setdefault(session, {})
        current.update({"agent": agent, "cwd": payload["cwd"], "bound_memories": memories, "memories": memories,
                        "last_observed": now(), "capture_disabled": launcher.get("capture_disabled", False)})
        current.setdefault("context_conversations", launcher.get("context_conversations"))
        current.setdefault("started", launcher.get("started", now()))
    store.update_sessions(project, change)
    if launcher and launcher.get("project") == project:
        store.update_pending(launcher["run_id"], lambda job: job.update({"session_id": session, "memories": memories}))
    return store.read_sessions(project)[session]


def context(store, project, session, record, *, compact=False):
    text = (f"[ellie conversation]\nproject: {project}\nsession_id: {session}\nwrite memories: "
            + ", ".join(record.get("bound_memories", []))
            + "\nInclude this session_id and project in EVERY Ellie MCP call. This binding belongs only to this conversation."
            + "\nUse conversations to choose historical sources; load(memories=[destination], conversations=[source IDs])"
            + " excludes other history. Use [] for no past conversations. Record useful decisions/results/findings as you work.")
    if compact:
        return text
    selected = record.get("context_conversations")
    if selected is not None:
        text += "\n" + render_selected(store, project, list(dict.fromkeys([*selected, session])))
    else:
        records = [item for item in list_conversations(store, project) if item["id"] != session][:8]
        text += "\nAvailable source conversations (choose before loading full history):\n"
        text += "\n".join(f"{item['id']} · {item['title'][:120]} · {len(item['items'])} items" for item in records)
        for memory in store.iter_memories(project):
            if memory.name == "project" or memory.name in record.get("bound_memories", []):
                text += "\n" + memory.name + ": " + memory.get_section("Goal").strip()[:300]
                text += "\n" + "\n".join(item.id + " · " + item.title for item in memory.items[-5:])
    if len(text) > 7000:
        text = text[:6500] + "\nContext shortened. Call load with the same conversation selection for complete details."
    return redact(text)


def handle(store, agent: str, event: str, payload: dict, *, start_worker=True) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("hook payload must be an object")
    if os.environ.get("ELLIE_CAPTURE") == "1" or payload.get("subagent") or payload.get("agent_id"):
        return {}
    if event not in {*EVENTS, "PostToolUseFailure", "Interrupt"}:
        raise ValueError("unsupported hook event")
    if not isinstance(payload, dict) or not isinstance(payload.get("cwd"), str):
        raise ValueError("hook requires cwd and session_id")
    session = validate_id(payload.get("session_id"))
    project, _ = store.resolve_project(payload["cwd"])
    if blocked(store, project, session):
        return {}
    tool = str(payload.get("tool_name", "")).lower()
    if "mcp__ellie" in tool or tool in {"todowrite", "askuserquestion", "listmcpresourcestool"}:
        return {}
    path = transcript_path(agent, payload.get("transcript_path"))
    record = _bind(store, project, session, agent, payload)
    if event == "UserPromptSubmit":
        title = " ".join(redact(str(payload.get("prompt", ""))).split())[:140]
        if title and not record.get("title"):
            store.update_sessions(project, lambda data: data[session].update({"title": title}))
    if event == "SessionStart":
        # Restart workers for pending checkpoints after a crash; jobs remain durable.
        if start_worker:
            from .capture import start_background
            for job in store.list_pending():
                if job.get("project") == project and job.get("incremental") and job.get("attempts", 0) < 3 and not _worker_alive(job):
                    start_background(store, job["run_id"])
    elif event != "UserPromptSubmit":
        enqueue(store, project, session, agent, payload["cwd"], path, event, payload, start_worker=start_worker)
    if event in {"SessionStart", "UserPromptSubmit"}:
        return {"hookSpecificOutput": {"hookEventName": event,
                                      "additionalContext": context(store, project, session, record, compact=event != "SessionStart")}}
    return {}
