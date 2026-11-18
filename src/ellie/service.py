"""Shared memory operations used by MCP, CLI, and capture."""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from .briefing import render_memory
from .index import Index
from .model import PROJECT_SECTIONS, WORKSTREAM_SECTIONS, stamp
from .paths import validate_project
from .redact import redact
from .store import FileStore, Store

DEFAULTS = {"agent": "codex", "capture": "auto", "extract_with": "same", "extract_timeout_sec": 600,
            "log_limit": 25, "briefing_max_chars": 24000, "brief_preselect": 12, "backfill_default_since": "30d",
            "checkpoint_interval_sec": 120}


class MemoryService:
    def __init__(self, store: Store | None = None, *, agent: str = "you"):
        self.store = store if store is not None else FileStore()
        self.agent = agent
        self.index = Index(self.store)
        self._current_session = ContextVar("ellie_session", default=None)

    @contextmanager
    def in_session(self, session_id):
        if session_id is not None:
            from .conversations import validate_id
            validate_id(session_id)
        token = self._current_session.set(session_id)
        try:
            yield
        finally:
            self._current_session.reset(token)

    def _scope(self, project, conversations=None):
        session = self._session()
        binding = self.store.read_sessions(project).get(session, {}) if session else {}
        bound = binding.get("context_conversations")
        if bound is not None:
            allowed = set([*bound, session])
            if conversations is not None and not set(conversations).issubset(allowed):
                raise ValueError("Change the session binding before widening conversation context")
            conversations = list(dict.fromkeys([*(bound if conversations is None else conversations), session]))
        return conversations

    def _check_destination(self, project, memory):
        from .privacy import blocked
        reason = blocked(self.store, project, self._session())
        if reason:
            raise ValueError(reason)
        session = self._session()
        record = self.store.read_sessions(project).get(session, {}) if session else {}
        if "bound_memories" in record and memory != "project" and memory not in record["bound_memories"]:
            raise ValueError("Memory is outside this conversation's binding; call bind or load first")

    def bind(self, project: str, memories: list[str], conversations: list[str] | None = None) -> dict:
        from .conversations import now, selected_items
        session = self._session()
        if not session:
            raise ValueError("bind requires session_id for the current conversation")
        for name in memories:
            self.store.read_memory(project, name)
        if conversations is not None:
            selected_items(self.store, project, conversations)
        def change(data):
            record = data.setdefault(session, {})
            record.update({"agent": self.agent, "bound_memories": memories, "memories": memories,
                           "context_conversations": conversations})
            record.setdefault("started", now())
        self.store.update_sessions(project, change)
        return {"session_id": session, "memories": memories, "conversations": conversations}

    def conversations(self, project: str) -> dict:
        from .conversations import list_conversations
        return {"project": project, "conversations": list_conversations(self.store, project)}

    def privacy(self, project: str, action: str = "status", conversation: str | None = None, archives: str | None = None) -> dict:
        from .privacy import control
        return control(self.store, project, action, conversation, archives)

    def timeline(self, project: str, anchor: str | None = None, query: str = "", before: int = 3, after: int = 3, conversations: list[str] | None = None) -> dict:
        from .conversations import memberships, selected_items
        if not 0 <= before <= 25 or not 0 <= after <= 25:
            raise ValueError("timeline depth must be between 0 and 25")
        conversations = self._scope(project, conversations)
        pairs = (selected_items(self.store, project, conversations) if conversations is not None else
                 [(memory.name, item) for memory in self.store.iter_memories(project) for item in memory.items])
        pairs.sort(key=lambda pair: (pair[1].fields.get("date", ""), int(pair[1].id[1:]), pair[1].id))
        if query and not anchor:
            hits = self.recall(project, query, limit=1, conversations=conversations)["items"]
            anchor = hits[0]["id"] if hits else None
            if not anchor:
                return {"items": []}
        if anchor:
            positions = [i for i, (_, item) in enumerate(pairs) if item.id == anchor]
            if not positions:
                raise ValueError("timeline anchor is outside the selected history")
            position = positions[0]
            pairs = pairs[max(0, position - before):position + after + 1]
        else:
            pairs = pairs[-(before + after + 1):]
        belonging = memberships(self.store, project)
        return {"items": [{"id": item.id, "title": item.title, "memory": name, "type": item.type,
                           "date": item.fields.get("date", ""), "conversations": belonging.get(item.id, [])}
                          for name, item in pairs]}

    def close(self) -> None:
        self.index.close()

    @property
    def config(self) -> dict:
        return {**DEFAULTS, **self.store.read_local("config")}

    def project(self, project: str | None = None, cwd: str | None = None) -> str:
        return validate_project(project) if project is not None else self.store.resolve_project(cwd or Path.cwd())[0]

    def status(self, project: str) -> dict:
        memories = [vars(meta) for meta in self.store.list_memories(project)]
        from .capture import uncaptured_status
        from .privacy import health
        return {"project": project, "memories": memories, "capture_health": health(self.store, project),
                "last_used": self.store.read_local("state").get("last_used", {}).get(project, []),
                "archived_count": len(self.store.list_memories(project, True)),
                **uncaptured_status(self.store, project)}

    def load(self, project: str, memories: list[str], conversations: list[str] | None = None) -> dict:
        if self._session():
            previous = self.store.read_sessions(project).get(self._session(), {}).get("context_conversations")
            self.bind(project, memories, previous if conversations is None else conversations)
        conversations = self._scope(project, conversations)
        memories = list(dict.fromkeys(name for name in memories if name != "project"))
        self.store.ensure_project(project, agent=self.agent)
        loaded = [self.store.read_memory(project, name) for name in ["project", *memories]]
        self.store.update_local("state", lambda data: data.setdefault("last_used", {}).update({project: memories}))
        if conversations is not None:
            from .conversations import render_selected
            return {"project": project, "memories": memories, "conversations": conversations,
                    "briefing": render_selected(self.store, project, conversations)}
        return {"project": project, "memories": memories,
                "briefing": "\n\n".join(render_memory(memory, self.config["log_limit"]) for memory in loaded)}

    def get(self, project: str, ids: list[str], conversations: list[str] | None = None) -> dict:
        conversations = self._scope(project, conversations)
        allowed = None
        if conversations is not None:
            from .conversations import selected_items
            allowed = {item.id: (name, item) for name, item in selected_items(self.store, project, conversations)}
        result = []
        for reference in ids:
            item_project, id = reference.rsplit(":", 1) if ":" in reference else (project, reference)
            validate_project(item_project)
            if allowed is not None:
                if item_project != project or id not in allowed:
                    raise ValueError("Item is outside the selected conversations: " + reference)
                name, item = allowed[id]
            else:
                name, item = self.store.get_item(item_project, id)
            result.append({"project": item_project, "memory": name, "id": id, "title": item.title, "fields": item.fields, "text": item.raw})
        return {"items": result}

    def recall(self, project: str, query: str, types: list[str] | None = None, limit: int = 8, include_superseded: bool = False, all_projects: bool = False, conversations: list[str] | None = None) -> dict:
        conversations = self._scope(project, conversations)
        return {"items": [hit.as_dict() for hit in self.index.recall(query, project=project, types=types, limit=limit, include_superseded=include_superseded, all_projects=all_projects, conversations=conversations)]}

    def create(self, project: str, name: str, description: str, goal: str = "", done_when: str = "") -> dict:
        from .privacy import blocked
        reason = blocked(self.store, project, self._session())
        if reason:
            raise ValueError(reason)
        if name == "project":
            raise ValueError("use the shared project memory; create names a workstream")
        self.store.create_memory(project, name, description, agent=self.agent, goal=goal, done_when=done_when)
        return {"name": name}

    def set_goal(self, project: str, memory: str, goal: str, done_when: str) -> dict:
        self._check_destination(project, memory)
        if memory == "project":
            raise ValueError("project memory has no Goal section")
        def change(doc):
            doc.set_section("Goal", redact(goal) + "\n\n**Done when:** " + redact(done_when))
            doc.append_log(self.agent, "goal", " ".join(redact(goal).split()))
        self.store.update_memory(project, memory, change, agent=self.agent)
        from .conversations import save_sections
        save_sections(self.store, project, self._session(), memory, {"Goal": redact(goal) + "\n\n**Done when:** " + redact(done_when)})
        return {"memory": memory}

    def _session(self) -> str | None:
        if self._current_session.get():
            return self._current_session.get()
        run = os.environ.get("ELLIE_RUN_ID")
        return self.store.read_pending(run).get("session_id") if run else None

    def _record_item(self, project: str, id: str) -> dict:
        run = os.environ.get("ELLIE_RUN_ID")
        if run and self.store.read_pending(run):
            def record(job):
                if job.get("project") == project and id not in job.setdefault("live_items", []):
                    job["live_items"].append(id)
            self.store.update_pending(run, record)
        return {"id": id}

    def decide(self, project: str, memory: str, title: str, options: list[str], chosen: str, tradeoff: str, why: str, supersedes: list[str] | None = None, refs: list[str] | None = None) -> dict:
        self._check_destination(project, memory)
        if supersedes:
            self.get(project, supersedes)
        fields = {"status": "active", "options": " · ".join(options), "chosen": chosen, "tradeoff": tradeoff, "why": why}
        if refs:
            fields["refs"] = " · ".join(refs)
        return self._record_item(project, self.store.add_item(project, memory, "D", title, fields, agent=self.agent, session=self._session(), supersedes=supersedes))

    def result(self, project: str, memory: str, title: str, outcome: str, what: str, evidence: str, refs: list[str] | None = None) -> dict:
        self._check_destination(project, memory)
        fields = {"outcome": outcome, "what": what, "evidence": evidence}
        if refs:
            fields["refs"] = " · ".join(refs)
        return self._record_item(project, self.store.add_item(project, memory, "R", title, fields, agent=self.agent, session=self._session()))

    def finding(self, project: str, memory: str, title: str, detail: str, scope: str, evidence: str = "") -> dict:
        self._check_destination(project, memory)
        return self._record_item(project, self.store.add_item(project, memory, "F", title, {"detail": detail, "scope": scope, "evidence": evidence}, agent=self.agent, session=self._session()))

    def question(self, project: str, memory: str, text: str) -> dict:
        self._check_destination(project, memory)
        return self._record_item(project, self.store.add_item(project, memory, "Q", text, {"status": "open"}, agent=self.agent, session=self._session()))

    def resolve(self, project: str, id: str, answer: str) -> dict:
        self.get(project, [id])
        self._check_destination(project, self.store.get_item(project, id)[0])
        self.store.resolve(project, id, answer, agent=self.agent, session=self._session())
        self._record_item(project, id)
        return {"id": id, "status": "resolved"}

    def log(self, project: str, memory: str, entry: str, kind: str) -> dict:
        self._check_destination(project, memory)
        self.store.update_memory(project, memory, lambda doc: doc.append_log(self.agent, kind, redact(entry), self._session()), agent=self.agent)
        return {"memory": memory}

    def update(self, project: str, memory: str, section: str, content: str) -> dict:
        self._check_destination(project, memory)
        allowed = {"Goal", "Current state", "Next steps", "Overview", "Conventions"}
        sections = PROJECT_SECTIONS if memory == "project" else WORKSTREAM_SECTIONS
        if section not in allowed or section not in sections:
            raise ValueError("update only replaces summary sections belonging to this memory")
        self.store.update_memory(project, memory, lambda doc: doc.set_section(section, redact(content)), agent=self.agent)
        from .conversations import save_sections
        save_sections(self.store, project, self._session(), memory, {section: content})
        return {"memory": memory, "section": section}

    def handoff(self, project: str, memory: str, current_state: str, next_steps: str, session_summary: str) -> dict:
        self._check_destination(project, memory)
        if memory == "project":
            raise ValueError("project memory has no handoff state; use a workstream")
        def change(doc):
            doc.set_section("Current state", redact(current_state))
            doc.set_section("Next steps", redact(next_steps))
            doc.append_log(self.agent, "handoff", redact(session_summary), self._session())
        self.store.update_memory(project, memory, change, agent=self.agent)
        from .conversations import save_sections
        save_sections(self.store, project, self._session(), memory, {"Current state": current_state, "Next steps": next_steps}, session_summary)
        run = os.environ.get("ELLIE_RUN_ID")
        if run and self.store.read_pending(run):
            def mark(job):
                if job.get("project") == project:
                    job.setdefault("live_handoffs", {})[memory] = datetime.now().astimezone().isoformat()
            self.store.update_pending(run, mark)
        return {"memory": memory}
