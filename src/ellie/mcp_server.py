"""Newline-delimited stdio JSON-RPC, with no SDK or runtime dependencies."""

from __future__ import annotations

import json
import os
import sys

from . import __version__
from .redact import redact
from .service import MemoryService
from .validation import validate

TEXT = {"type": "string"}
TEXTS = {"type": "array", "items": TEXT}
BOOL = {"type": "boolean"}


def tool(name, description, properties, required):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": {**properties, "project": TEXT, "cwd": TEXT, "session_id": TEXT},
                            "required": required, "additionalProperties": False}}


TOOLS = [
    tool("conversations", "Before selecting context, list this project's conversations, titles, source item IDs and capture status.", {}, []),
    tool("bind", "Bind the current session_id to write workstreams and optional source conversations; [] means no past conversations.", {"memories": TEXTS, "conversations": TEXTS}, ["session_id", "memories"]),
    tool("timeline", "After recall, inspect nearby items around an anchor ID or query, limited to selected conversations.", {"anchor": TEXT, "query": TEXT, "before": {"type": "integer", "minimum": 0, "maximum": 25}, "after": {"type": "integer", "minimum": 0, "maximum": 25}, "conversations": TEXTS}, []),
    tool("status", "Use at the start of work to discover this project's memories and uncaptured sessions.", {}, []),
    tool("load", "Before work, load workstreams or only selected source conversations; preserves the session's context restriction.", {"memories": TEXTS, "conversations": TEXTS}, ["memories"]),
    tool("get", "After recall, fetch full items by ID. Conversation restrictions also apply to full-item reads.", {"ids": TEXTS, "conversations": TEXTS}, ["ids"]),
    tool("recall", "Before choosing an approach, search past decisions, failures and findings within the selected conversation context.", {"query": TEXT, "types": TEXTS, "limit": {"type": "integer", "minimum": 1, "maximum": 1000}, "include_superseded": BOOL, "all_projects": BOOL, "conversations": TEXTS}, ["query"]),
    tool("create", "Create a named workstream when starting a distinct feature, fix or investigation.", {"name": TEXT, "description": TEXT, "goal": TEXT, "done_when": TEXT}, ["name", "description"]),
    tool("set_goal", "Set or revise a workstream's goal and explicit completion criteria when its purpose changes.", {"memory": TEXT, "goal": TEXT, "done_when": TEXT}, ["memory", "goal", "done_when"]),
    tool("decide", "Record a consequential choice as it happens, including alternatives, tradeoff and why. Supersede earlier decisions explicitly.", {"memory": TEXT, "title": TEXT, "options": TEXTS, "chosen": TEXT, "tradeoff": TEXT, "why": TEXT, "supersedes": TEXTS, "refs": TEXTS}, ["memory", "title", "options", "chosen", "tradeoff", "why"]),
    tool("result", "After trying something, record whether it worked, failed or partly worked, with evidence for future sessions.", {"memory": TEXT, "title": TEXT, "outcome": {"type": "string", "enum": ["worked", "failed", "partial"]}, "what": TEXT, "evidence": TEXT, "refs": TEXTS}, ["memory", "title", "outcome", "what", "evidence"]),
    tool("finding", "Save a durable fact or gotcha learned from the code or tools. Use project scope for repo-wide knowledge.", {"memory": TEXT, "title": TEXT, "detail": TEXT, "evidence": TEXT, "scope": {"type": "string", "enum": ["workstream", "project"]}}, ["memory", "title", "detail", "scope"]),
    tool("question", "Record an unresolved question that another session should investigate.", {"memory": TEXT, "text": TEXT}, ["memory", "text"]),
    tool("resolve", "When an open question is answered, save the answer and mark its item resolved.", {"id": TEXT, "answer": TEXT}, ["id", "answer"]),
    tool("log", "Add a brief progress update, issue or timeline note without creating a knowledge item.", {"memory": TEXT, "entry": TEXT, "kind": {"type": "string", "enum": ["progress", "issue", "note"]}}, ["memory", "entry", "kind"]),
    tool("update", "Replace a summary section when its content changes. Item sections and the append-only Log cannot be replaced.", {"memory": TEXT, "section": TEXT, "content": TEXT}, ["memory", "section", "content"]),
    tool("handoff", "When asked to hand off, wrap up or save, record current state, ordered next steps and a session summary.", {"memory": TEXT, "current_state": TEXT, "next_steps": TEXT, "session_summary": TEXT}, ["memory", "current_state", "next_steps", "session_summary"]),
]


def reject_constant(value):
    raise ValueError("non-finite JSON number")


class Server:
    def __init__(self, service: MemoryService | None = None):
        self.service = service or MemoryService(agent=os.environ.get("ELLIE_AGENT", "you"))
        self.tools = {tool["name"]: tool for tool in TOOLS}

    @staticmethod
    def error(id, code, message):
        return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}

    def handle(self, request):
        if not isinstance(request, dict):
            return self.error(None, -32600, "expected a JSON-RPC request object")
        id = request.get("id")
        if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str) or isinstance(id, (bool, list, dict)):
            return self.error(None, -32600, "invalid JSON-RPC request")
        method = request["method"]
        if method.startswith("notifications/"):
            return None
        params = request.get("params", {})
        if not isinstance(params, dict):
            return self.error(id, -32602, "params must be an object") if "id" in request else None
        try:
            if method == "initialize":
                if "ELLIE_AGENT" not in os.environ:
                    name = str(params.get("clientInfo", {}).get("name", "")).lower()
                    self.service.agent = "codex" if "codex" in name else "claude-code" if "claude" in name else "you"
                result = {"protocolVersion": params.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
                          "serverInfo": {"name": "ellie", "version": __version__},
                          "instructions": "Use status/load at start, recall before choosing, record decisions/results/findings, and handoff when wrapping up. Verify old memory against code; never save secrets."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method in ("resources/list", "prompts/list"):
                result = {method.split("/")[0]: []}
            elif method == "tools/call":
                result = self.call(params)
            else:
                return self.error(id, -32601, "method not found") if "id" in request else None
            return {"jsonrpc": "2.0", "id": id, "result": result} if "id" in request else None
        except Exception as exc:
            return self.error(id, -32602, redact(str(exc))) if "id" in request else None

    def call(self, params):
        try:
            name = params.get("name")
            if name not in self.tools:
                raise ValueError("unknown tool")
            arguments = params.get("arguments", {})
            validate(arguments, self.tools[name]["inputSchema"])
            arguments = dict(arguments)
            session_id = arguments.pop("session_id", None)
            project = self.service.project(arguments.pop("project", None), arguments.pop("cwd", None))
            with self.service.in_session(session_id):
                value = getattr(self.service, name)(project, **arguments)
            return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "structuredContent": value, "isError": False}
        except Exception as exc:
            return {"content": [{"type": "text", "text": redact(str(exc))}], "isError": True}


def main() -> int:
    server = Server()
    try:
        for line in sys.stdin.buffer:
            if not line.strip():
                continue
            try:
                request = json.loads(line, parse_constant=reject_constant)
            except (ValueError, UnicodeError):
                response = server.error(None, -32700, "invalid JSON")
            else:
                response = server.handle(request)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
                sys.stdout.flush()
    except BrokenPipeError:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        return 0
    finally:
        server.service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
