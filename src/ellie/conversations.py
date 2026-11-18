"""Conversation provenance and strict historical selection through Store."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .model import Item
from .redact import redact


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def validate_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("invalid conversation ID")
    return value


def remember(store, project: str, session: str | None, name: str, item, *, preserve: bool = False):
    """Keep a historical item version; the Markdown document remains the current view."""
    if not session:
        return
    validate_id(session)
    saved = now()
    def change(data):
        record = data.setdefault(session, {})
        ids = record.setdefault("items", [])
        if item.id not in ids:
            ids.append(item.id)
        memories = record.setdefault("memories", [])
        if name not in memories:
            memories.append(name)
        snapshots = record.setdefault("item_snapshots", {})
        if not preserve or item.id not in snapshots:
            snapshots[item.id] = {"memory": name, "raw": redact(item.raw), "saved_at": saved}
        record.setdefault("started", saved)
        if not preserve:
            record["last_saved"] = saved
    store.update_sessions(project, change)


def preserve_before_change(store, project, name, item):
    belonging = memberships(store, project)
    for session in belonging.get(item.id, sources(item)):
        remember(store, project, session, name, item, preserve=True)


def sources(item) -> list[str]:
    ids = re.findall(r"(?:^| · )session ([A-Za-z0-9_.-]+)(?= · |$)", item.fields.get("source", ""))
    ids.extend(item.fields.get("conversations", "").split(" · "))
    return list(dict.fromkeys(id for id in ids if id))


def memberships(store, project: str) -> dict[str, list[str]]:
    result = {}
    for memory in store.iter_memories(project):
        for item in memory.items:
            result[item.id] = sources(item)
    for session, record in store.read_sessions(project).items():
        for id in record.get("items", []):
            result.setdefault(id, [])
            if session not in result[id]:
                result[id].append(session)
    return result


def list_conversations(store, project: str) -> list[dict]:
    records = store.read_sessions(project)
    belonging = memberships(store, project)
    for ids in belonging.values():
        for id in ids:
            records.setdefault(id, {})
    result = []
    for id, record in records.items():
        ids = sorted({item for item, sessions in belonging.items() if id in sessions})
        names = sorted(set(record.get("memories", [])))
        result.append({"id": id, "title": record.get("title") or record.get("summary") or "Conversation " + id[:12],
                       "summary": record.get("summary", ""), "agent": record.get("agent", "unknown"),
                       "started": record.get("started", ""), "ended": record.get("ended", ""),
                       "last_saved": record.get("last_saved", ""), "capture": record.get("capture", "live"),
                       "items": ids, "memories": names, "error": record.get("error", ""),
                       "historical_versions": bool(record.get("item_snapshots"))})
    return sorted(result, key=lambda record: (record["started"], record["id"]), reverse=True)


def save_sections(store, project, session, name, sections, summary=None):
    if not session:
        return
    validate_id(session)
    def change(data):
        record = data.setdefault(session, {})
        record.setdefault("context", {}).setdefault(name, {}).update({key: redact(value) for key, value in sections.items()})
        record["last_saved"] = now()
        if summary is not None:
            record["summary"] = redact(summary)
    store.update_sessions(project, change)


def selected_items(store, project: str, conversations: list[str]):
    if not isinstance(conversations, list) or any(not isinstance(id, str) for id in conversations):
        raise ValueError("conversations must be a list of IDs")
    belonging = memberships(store, project)
    known = set(store.read_sessions(project)) | {session for values in belonging.values() for session in values}
    if set(conversations) - known:
        raise ValueError("Unknown conversation in this project: " + ", ".join(sorted(set(conversations) - known)))
    records = store.read_sessions(project)
    chosen = set(conversations)
    result = {}
    for memory in store.iter_memories(project):
        for item in memory.items:
            if chosen.intersection(belonging.get(item.id, [])):
                result[item.id] = (memory.name, item)
    versions = {}
    for session in conversations:
        for id, version in records.get(session, {}).get("item_snapshots", {}).items():
            if id not in versions or version.get("saved_at", "") > versions[id].get("saved_at", ""):
                versions[id] = version
    for id, version in versions.items():
        item = Item(version["raw"], memory=version["memory"])
        if item.id != id:
            raise ValueError("conversation snapshot ID disagrees with its item")
        result[id] = (version["memory"], item)
    return list(result.values())


def render_selected(store, project: str, conversations: list[str]) -> str:
    items = selected_items(store, project, conversations)
    records = store.read_sessions(project)
    context = []
    for id in conversations:
        record = records.get(id, {})
        if record.get("summary"):
            context.append("## Conversation " + id + "\n" + record["summary"])
        for name, sections in record.get("context", {}).items():
            context.append("From conversation " + id + " · memory: " + name + "\n"
                           + "\n".join("## " + title + "\n" + value for title, value in sections.items()))
    return ("# Selected conversations\nProject: " + project + "\nConversations: " + ", ".join(conversations)
            + "\nOnly these conversations are included. Unattributed items and global summaries are excluded.\n\n"
            + "\n\n".join(context + ["From memory: " + name + "\n" + item.raw.strip() for name, item in items]))
