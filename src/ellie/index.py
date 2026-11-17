"""Rebuildable local search cache, with FTS5 and a portable LIKE fallback."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
import re
import sqlite3
import time

from .store import Store

COLUMNS = "project, memory, id, type, title, body, date, status, outcome, scope"


@dataclass(frozen=True)
class SearchHit:
    project: str
    memory: str
    id: str
    type: str
    title: str
    date: str
    status: str
    outcome: str
    scope: str
    snippet: str
    score: float

    def as_dict(self) -> dict:
        return asdict(self)


def type_weight(type: str, status: str, outcome: str) -> float:
    if status.startswith("superseded") or status == "reverted":
        return 0.3
    if type == "D":
        return 1.2
    if type == "R":
        return 1.3 if outcome in ("failed", "partial") else 1.0
    if type == "F":
        return 1.2
    if type == "Q":
        return 0.5 if status == "resolved" else 1.1
    return 0.8


def recency(value: str, today: date | None = None) -> float:
    try:
        age = max(0, ((today or date.today()) - date.fromisoformat(value[:10])).days)
    except (ValueError, TypeError):
        return 1.0
    return max(0.25, 0.5 ** (age / 120))


class Index:
    def __init__(self, store: Store, path: Path | None = None, *, force_like: bool = False):
        self.store = store
        self.path = path or store.path(".local", "index.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=2)
        self.db.row_factory = sqlite3.Row
        self.db.create_function("ellie_casefold", 1, lambda value: value.casefold())
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=2000")
        self.db.execute("CREATE TABLE IF NOT EXISTS files (project TEXT, memory TEXT, mtime INTEGER, size INTEGER, archived INTEGER, PRIMARY KEY(project, memory))")
        existing = self.db.execute("SELECT sql FROM sqlite_master WHERE name='items'").fetchone()
        if force_like and existing and "VIRTUAL TABLE" in existing[0].upper():
            self.db.execute("DROP TABLE items")
            self.db.execute("DELETE FROM files")
            existing = None
        if not existing:
            if not force_like:
                try:
                    self.db.execute("CREATE VIRTUAL TABLE items USING fts5(project UNINDEXED, memory UNINDEXED, id UNINDEXED, type UNINDEXED, title, body, date UNINDEXED, status UNINDEXED, outcome UNINDEXED, scope UNINDEXED)")
                except sqlite3.OperationalError as exc:
                    if "no such module" not in str(exc).lower():
                        raise
            if force_like or not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='items'").fetchone():
                self.db.execute("CREATE TABLE items (project TEXT, memory TEXT, id TEXT, type TEXT, title TEXT, body TEXT, date TEXT, status TEXT, outcome TEXT, scope TEXT)")
                self.db.execute("CREATE INDEX item_project ON items(project)")
        self.fts = "VIRTUAL TABLE" in self.db.execute("SELECT sql FROM sqlite_master WHERE name='items'").fetchone()[0].upper()
        self.db.commit()
        self.store.subscribe(self.sync_memory)
        self.sync()

    def close(self) -> None:
        self.store.unsubscribe(self.sync_memory)
        self.db.close()

    def __enter__(self) -> Index:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _write(self, action) -> None:
        for attempt in range(4):
            try:
                with self.db:
                    action()
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 3:
                    raise
                time.sleep(0.025 * (attempt + 1))

    def sync_memory(self, project: str, name: str) -> None:
        try:
            version = self.store.memory_version(project, name)
            memory = self.store.read_memory(project, name)
        except FileNotFoundError:
            memory, version = None, None
        def update():
            self.db.execute("DELETE FROM items WHERE project=? AND memory=?", (project, name))
            self.db.execute("DELETE FROM files WHERE project=? AND memory=?", (project, name))
            if memory is None:
                return
            rows = []
            for item in memory.items:
                fields = item.fields
                rows.append((project, name, item.id, item.type, item.title, item.raw, fields.get("date", ""), fields.get("status", ""), fields.get("outcome", ""), fields.get("scope", "project" if name == "project" else "workstream")))
            self.db.executemany(f"INSERT INTO items ({COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            self.db.execute("INSERT INTO files VALUES (?,?,?,?,?)", (project, name, *version))
        self._write(update)

    def sync(self) -> None:
        versions = self.store.memory_versions()
        known = {(row["project"], row["memory"]): (row["mtime"], row["size"], bool(row["archived"]))
                 for row in self.db.execute("SELECT * FROM files")}
        for key in sorted(set(versions) | set(known)):
            if versions.get(key) != known.get(key):
                self.sync_memory(*key)

    def reindex(self) -> int:
        def clear():
            self.db.execute("DELETE FROM items")
            self.db.execute("DELETE FROM files")
        self._write(clear)
        self.sync()
        return self.db.execute("SELECT count(*) FROM items").fetchone()[0]

    def recall(self, query: str, *, project: str | None = None, types: list[str] | None = None, limit: int = 10, include_superseded: bool = False, all_projects: bool = False) -> list[SearchHit]:
        if not isinstance(query, str):
            raise ValueError("query must be text")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if types is not None and (not isinstance(types, list) or any(t not in {"D", "R", "F", "Q", "N"} for t in types)):
            raise ValueError("types must be a list containing D, R, F, Q, or N")
        self.sync()
        tokens = list(dict.fromkeys(re.findall(r"\w+", query.casefold())))
        if not tokens:
            return []
        conditions, params = [], []
        if project and not all_projects:
            conditions.append("project=?")
            params.append(project)
        if not include_superseded:
            conditions.append("status NOT LIKE 'superseded%' AND status != 'reverted'")
        if types:
            conditions.append("type IN (" + ",".join("?" for _ in types) + ")")
            params.extend(types)
        if self.fts:
            conditions.append("items MATCH ?")
            params.append(" OR ".join('"' + token.replace('"', '""') + '"' for token in tokens))
            relevance = "-bm25(items,0,0,0,0,5,1,0,0,0,0) AS relevance"
        else:
            conditions.append("(" + " OR ".join("(ellie_casefold(title) LIKE ? ESCAPE '\\' OR ellie_casefold(body) LIKE ? ESCAPE '\\')" for _ in tokens) + ")")
            for token in tokens:
                pattern = "%" + token.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%") + "%"
                params.extend((pattern, pattern))
            relevance = "1.0 AS relevance"
        rows = self.db.execute(f"SELECT {COLUMNS}, {relevance} FROM items WHERE " + " AND ".join(conditions), params).fetchall()
        hits = []
        for row in rows:
            relevance = row["relevance"] if self.fts else sum(row["title"].casefold().count(t) * 5 + row["body"].casefold().count(t) for t in tokens)
            score = relevance * recency(row["date"]) * type_weight(row["type"], row["status"], row["outcome"])
            snippet = " ".join(row["body"].split())[:240]
            hits.append(SearchHit(*(row[k] for k in ("project", "memory", "id", "type", "title", "date", "status", "outcome", "scope")), snippet, score))
        return sorted(hits, key=lambda h: (-h.score, h.project, h.id))[:limit]
