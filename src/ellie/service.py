"""Shared memory operations used by MCP, CLI, and capture."""

from __future__ import annotations

import os
from pathlib import Path

from .briefing import render_memory
from .index import Index
from .model import PROJECT_SECTIONS, WORKSTREAM_SECTIONS, stamp
from .paths import validate_project
from .redact import redact
from .store import FileStore, Store

DEFAULTS = {"agent": "codex", "capture": "auto", "extract_with": "same", "extract_timeout_sec": 600,
            "log_limit": 25, "briefing_max_chars": 24000, "brief_preselect": 12, "backfill_default_since": "30d"}


class MemoryService:
    def __init__(self, store: Store | None = None, *, agent: str = "you"):
        self.store = store if store is not None else FileStore()
        self.agent = agent
        self.index = Index(self.store)

    def close(self) -> None:
        self.index.close()

    @property
    def config(self) -> dict:
        return {**DEFAULTS, **self.store.read_local("config")}

    def project(self, project: str | None = None, cwd: str | None = None) -> str:
        return validate_project(project) if project is not None else self.store.resolve_project(cwd or Path.cwd())[0]

    def status(self, project: str) -> dict:
        memories = [vars(meta) for meta in self.store.list_memories(project)]
        sessions = self.store.read_sessions(project)
        return {"project": project, "memories": memories,
                "last_used": self.store.read_local("state").get("last_used", {}).get(project, []),
                "archived_count": len(self.store.list_memories(project, True)),
                "uncaptured_sessions": sum(record.get("capture") not in {"done", "skipped"} for record in sessions.values())}

    def load(self, project: str, memories: list[str]) -> dict:
        memories = list(dict.fromkeys(name for name in memories if name != "project"))
        self.store.ensure_project(project, agent=self.agent)
        loaded = [self.store.read_memory(project, name) for name in ["project", *memories]]
        self.store.update_local("state", lambda data: data.setdefault("last_used", {}).update({project: memories}))
        return {"project": project, "memories": memories,
                "briefing": "\n\n".join(render_memory(memory, self.config["log_limit"]) for memory in loaded)}

    def get(self, project: str, ids: list[str]) -> dict:
        result = []
        for reference in ids:
            item_project, id = reference.rsplit(":", 1) if ":" in reference else (project, reference)
            validate_project(item_project)
            name, item = self.store.get_item(item_project, id)
            result.append({"project": item_project, "memory": name, "id": id, "title": item.title, "fields": item.fields, "text": item.raw})
        return {"items": result}

    def recall(self, project: str, query: str, types: list[str] | None = None, limit: int = 8, include_superseded: bool = False, all_projects: bool = False) -> dict:
        return {"items": [hit.as_dict() for hit in self.index.recall(query, project=project, types=types, limit=limit, include_superseded=include_superseded, all_projects=all_projects)]}

    def create(self, project: str, name: str, description: str, goal: str = "", done_when: str = "") -> dict:
        if name == "project":
            raise ValueError("use the shared project memory; create names a workstream")
        self.store.create_memory(project, name, description, agent=self.agent, goal=goal, done_when=done_when)
        return {"name": name}

    def set_goal(self, project: str, memory: str, goal: str, done_when: str) -> dict:
        if memory == "project":
            raise ValueError("project memory has no Goal section")
        def change(doc):
            doc.set_section("Goal", redact(goal) + "\n\n**Done when:** " + redact(done_when))
            doc.append_log(self.agent, "goal", " ".join(redact(goal).split()))
        self.store.update_memory(project, memory, change, agent=self.agent)
        return {"memory": memory}

    def _session(self) -> str | None:
        run = os.environ.get("ELLIE_RUN_ID")
        return self.store.read_pending(run).get("session_id") if run else None

    def decide(self, project: str, memory: str, title: str, options: list[str], chosen: str, tradeoff: str, why: str, supersedes: list[str] | None = None, refs: list[str] | None = None) -> dict:
        fields = {"status": "active", "options": " · ".join(options), "chosen": chosen, "tradeoff": tradeoff, "why": why}
        if refs:
            fields["refs"] = " · ".join(refs)
        return {"id": self.store.add_item(project, memory, "D", title, fields, agent=self.agent, session=self._session(), supersedes=supersedes)}

    def result(self, project: str, memory: str, title: str, outcome: str, what: str, evidence: str, refs: list[str] | None = None) -> dict:
        fields = {"outcome": outcome, "what": what, "evidence": evidence}
        if refs:
            fields["refs"] = " · ".join(refs)
        return {"id": self.store.add_item(project, memory, "R", title, fields, agent=self.agent, session=self._session())}

    def finding(self, project: str, memory: str, title: str, detail: str, scope: str, evidence: str = "") -> dict:
        return {"id": self.store.add_item(project, memory, "F", title, {"detail": detail, "scope": scope, "evidence": evidence}, agent=self.agent, session=self._session())}

    def question(self, project: str, memory: str, text: str) -> dict:
        return {"id": self.store.add_item(project, memory, "Q", text, {"status": "open"}, agent=self.agent, session=self._session())}

    def resolve(self, project: str, id: str, answer: str) -> dict:
        self.store.resolve(project, id, answer, agent=self.agent, session=self._session())
        return {"id": id, "status": "resolved"}

    def log(self, project: str, memory: str, entry: str, kind: str) -> dict:
        self.store.update_memory(project, memory, lambda doc: doc.append_log(self.agent, kind, redact(entry), self._session()), agent=self.agent)
        return {"memory": memory}

    def update(self, project: str, memory: str, section: str, content: str) -> dict:
        allowed = {"Goal", "Current state", "Next steps", "Overview", "Conventions"}
        sections = PROJECT_SECTIONS if memory == "project" else WORKSTREAM_SECTIONS
        if section not in allowed or section not in sections:
            raise ValueError("update only replaces summary sections belonging to this memory")
        self.store.update_memory(project, memory, lambda doc: doc.set_section(section, redact(content)), agent=self.agent)
        return {"memory": memory, "section": section}

    def handoff(self, project: str, memory: str, current_state: str, next_steps: str, session_summary: str) -> dict:
        if memory == "project":
            raise ValueError("project memory has no handoff state; use a workstream")
        def change(doc):
            doc.set_section("Current state", redact(current_state))
            doc.set_section("Next steps", redact(next_steps))
            doc.append_log(self.agent, "handoff", redact(session_summary), self._session())
        self.store.update_memory(project, memory, change, agent=self.agent)
        run = os.environ.get("ELLIE_RUN_ID")
        if run:
            def mark(job):
                if job.get("project") == project:
                    job.setdefault("live_handoffs", {})[memory] = stamp()
            self.store.update_pending(run, mark)
        return {"memory": memory}
