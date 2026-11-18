"""Interactive agent launcher and startup prompt construction."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from .briefing import Selection, pick_conversations, pick_memories, render_briefing, select_history
from .model import Memory
from .paths import validate_name

USAGE = """How to use ellie in this session:
- Before choosing an approach, call ellie `recall` to check past decisions, results and findings.
- Record as you go: `decide` for choices (options, tradeoff, why), `result` for things tried
  (worked/failed/partial + evidence), `finding` for things learned, `question` for open issues.
- When I say handoff / wrap up / save, call `handoff`.
- Treat memory as possibly outdated: verify against the code before relying on it.
First give me a 3–5 line recap of where things stand and the next step, then wait."""


def startup_prompt(service, project: str, selection: Selection) -> str:
    context = render_briefing(service, project, selection)
    if len(context) > service.config["briefing_max_chars"]:
        context = ("The selected context exceeds the inline briefing budget. Call ellie load with memories="
                   + repr(selection.memories) + " (project memory always loads).")
        if selection.conversations is not None:
            context += " Include conversations=" + repr(selection.conversations) + "; do not load unselected history."
        if selection.ids:
            context += " Then call ellie get with ids=" + repr(selection.ids) + "."
    scope = "project memory always loaded" if selection.conversations is None else "only selected conversations loaded; other project history excluded"
    return (f"[ellie session]\nproject: {project}\nmemories: {', '.join(selection.memories) or '(none)'}"
            f"   ({scope})\n\n{context}\n\n---\n{USAGE}")


def start(service, options, agent_args: list[str]) -> int:
    project = service.project()
    agent = options.agent or service.config["agent"]
    selection = Selection(options.memory or [])
    sources = getattr(options, "conversations", None)
    if getattr(options, "no_history", False):
        if sources is not None:
            raise ValueError("--no-history cannot be combined with --from-conversation")
        sources = []
    if getattr(options, "pick_conversations", False):
        sources = pick_conversations(service, project)
        if sources is None:
            return 0
    if sources is not None:
        from .conversations import selected_items
        selected_items(service.store, project, sources)
    if options.new:
        validate_name(options.new, allow_project=False)
        if options.dry_run:
            selection = Selection([options.new], drafts={options.new: Memory.new(options.new, options.description or "")})
        else:
            service.create(project, options.new, options.description or "")
            selection = Selection([options.new])
    elif options.project_only:
        selection = Selection()
    elif options.memory is None:
        if sys.stdin.isatty():
            selection = pick_memories(service, project, dry_run=options.dry_run)
        else:
            status = service.status(project)
            active = {meta["name"] for meta in status["memories"]}
            selection.memories = [name for name in status["last_used"] if name in active]
    if sources is not None:
        selection.conversations = sources
    if options.about:
        history = select_history(service, project, options.about, conversations=selection.conversations)
        selection.memories = list(dict.fromkeys([*selection.memories, *history.memories]))
        selection.ids.extend(history.ids)
    selection.ids.extend(options.with_ids or [])
    prompt = startup_prompt(service, project, selection)
    if options.dry_run:
        print(prompt)
        return 0
    executable = shutil.which(agent)
    if not executable:
        raise ValueError(f"{agent} is not on PATH")
    service.store.ensure_project(project)
    service.store.update_local("state", lambda data: data.setdefault("last_used", {}).update({project: selection.memories}))
    run_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4()) if agent == "claude" else None
    command = [executable, *agent_args]
    if agent == "claude":
        explicit = next((arg.split("=", 1)[1] for arg in agent_args if arg.startswith("--session-id=")), None)
        if "--session-id" in agent_args:
            position = agent_args.index("--session-id")
            if position + 1 >= len(agent_args):
                raise ValueError("--session-id requires a UUID")
            explicit = agent_args[position + 1]
        if explicit:
            session_id = str(uuid.UUID(explicit))
        else:
            command.extend(["--session-id", session_id])
    command.append(" ".join(prompt.splitlines()) if os.name == "nt" else prompt)
    record = {"run_id": run_id, "project": project, "agent": agent, "cwd": str(Path.cwd()),
              "started": datetime.now().astimezone().isoformat(), "memories": selection.memories,
              "session_id": session_id, "capture": "pending"}
    record["context_conversations"] = selection.conversations
    record["capture_disabled"] = options.no_capture or service.config["capture"] != "auto"
    from .capture import snapshot_sessions
    record["before_sessions"] = snapshot_sessions(agent)
    service.store.write_pending(run_id, record)
    env = {**os.environ, "ELLIE_AGENT": "claude-code" if agent == "claude" else "codex", "ELLIE_RUN_ID": run_id}
    process = subprocess.Popen(command, cwd=Path.cwd(), env=env)
    try:
        code = process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        code = 130
    service.store.update_pending(run_id, lambda job: job.update({"ended": datetime.now().astimezone().isoformat(), "exit_code": code}))
    mode = service.config["capture"]
    capture = not options.no_capture and mode != "off"
    if capture and mode == "ask":
        capture = sys.stdin.isatty() and input("Capture this session? [y/N] ").strip().lower() in {"y", "yes"}
    if capture:
        from .capture import start_background
        start_background(service.store, run_id)
        print("ellie: capturing session in background (ellie status to see result)")
    return 128 - code if code < 0 else code
