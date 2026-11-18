"""Loopback-only, read-only dashboard. No model calls or agent session scanning."""

from __future__ import annotations

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .index import Index
from .store import Store


def snapshot(store: Store, selected: str | None = None) -> dict:
    """Read saved documents and capture records without loading a memory in an agent."""
    projects = []
    documents = {}
    for project in store.list_projects():
        memories = []
        archived = {meta.name for meta in store.list_memories(project, True)}
        for memory in store.iter_memories(project):
            memories.append({
                "name": memory.name, "meta": memory.meta, "sections": memory.sections,
                "archived": memory.name in archived, "raw": memory.render(),
                "items": [{"id": item.id, "type": item.type, "title": item.title,
                           "fields": item.fields, "body": item.body, "raw": item.raw,
                           "memory": memory.name, "archived": memory.name in archived}
                          for item in memory.items],
            })
        documents[project] = memories
        shared = next((m for m in memories if m["name"] == "project"), {})
        projects.append({
            "id": project, "name": project.rsplit("/", 1)[-1],
            "description": shared.get("meta", {}).get("description", ""),
            "workstreams": sum(m["name"] != "project" and not m["archived"] for m in memories),
            "items": sum(len(m["items"]) for m in memories),
        })
    if selected is None:
        selected = projects[0]["id"] if projects else None
    if selected is not None and selected not in documents:
        raise FileNotFoundError("Project not found")
    detail = None
    if selected:
        sessions = store.read_sessions(selected)
        pending = [job for job in store.list_pending() if job.get("project") == selected]
        # Do not expose archives/transcripts, source paths, prompts or arbitrary job data.
        keys = ("agent", "started", "ended", "capture", "memories", "items", "error")
        detail = {
            "id": selected, "memories": documents[selected],
            "sessions": [{"id": id, **{k: record[k] for k in keys if k in record}}
                         for id, record in sessions.items() if isinstance(record, dict)],
            "pending": [{"id": job.get("run_id", ""),
                         **{k: job[k] for k in keys if k in job}} for job in pending],
            "warnings": list(store.pending_problems),
        }
    return {"projects": projects, "project": detail,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


class DashboardServer(ThreadingHTTPServer):
    def __init__(self, store: Store, port: int, project: str | None = None):
        self.store = store
        self.project = project
        super().__init__(("127.0.0.1", port), DashboardHandler)
        self.timeout = 1


class DashboardHandler(BaseHTTPRequestHandler):
    # A client which opens a socket and sends nothing must not block the viewer forever.
    timeout = 5

    def log_message(self, format, *args):
        pass

    def _send(self, code, content, kind="application/json; charset=utf-8"):
        body = content if isinstance(content, bytes) else json.dumps(content, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _allowed(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in hosts:
            self._send(403, {"error": "Loopback host required"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {"http://" + host for host in hosts}:
            self._send(403, {"error": "Same-origin requests only"})
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self._send(403, {"error": "Same-origin requests only"})
            return False
        return True

    def do_GET(self):
        if not self._allowed():
            return
        route = urlsplit(self.path)
        query = parse_qs(route.query)
        try:
            assets = {"/": ("index.html", "text/html"),
                      "/assets/style.css": ("style.css", "text/css"),
                      "/assets/app.js": ("app.js", "text/javascript")}
            if route.path in assets:
                name, kind = assets[route.path]
                data = files("ellie").joinpath("resources", "ui", name).read_bytes()
                self._send(200, data, kind + "; charset=utf-8")
            elif route.path == "/api/snapshot":
                project = query.get("project", [self.server.project])[0]
                self._send(200, snapshot(self.server.store, project))
            elif route.path == "/api/search":
                project = query.get("project", [self.server.project])[0]
                if project not in self.server.store.list_projects():
                    raise FileNotFoundError("Project not found")
                term = query.get("q", [""])[0].strip()
                if len(term) > 1000:
                    raise ValueError("Search is limited to 1000 characters")
                # A fresh connection per request stays on the serving thread.
                with Index(self.server.store) as index:
                    hits = index.recall(term, project=project, limit=500, include_superseded=True) if term else []
                self._send(200, {"items": [hit.as_dict() for hit in hits]})
            else:
                self._send(404, {"error": "Not found"})
        except FileNotFoundError as exc:
            self._send(404, {"error": str(exc)})
        except (ValueError, UnicodeError) as exc:
            self._send(400, {"error": str(exc)})
        except (OSError, sqlite3.Error) as exc:
            self._send(503, {"error": "Could not read saved memory: " + str(exc)})

    def do_POST(self):
        if self._allowed():
            self._send(405, {"error": "This dashboard is read-only"})

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST


def make_server(store: Store, *, port: int = 8767, project: str | None = None) -> DashboardServer:
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    return DashboardServer(store, port, project)


def run(store: Store, *, port: int = 8767, open_browser: bool = True) -> int:
    project, _ = store.resolve_project(Path.cwd())
    if project not in store.list_projects():
        project = None
    try:
        server = make_server(store, port=port, project=project)
    except OSError as exc:
        raise OSError(f"Cannot open dashboard on port {port}; try ellie ui --port 0 ({exc})") from exc
    with server:
        url = f"http://127.0.0.1:{server.server_port}"
        print(f"Ellie dashboard: {url}", flush=True)
        print("Read-only · local to this machine · Ctrl-C to stop", flush=True)
        if open_browser:
            try:
                webbrowser.open(url)
            except webbrowser.Error:
                print("Open the URL above in your browser.", flush=True)
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            pass
    return 0
