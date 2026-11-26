"""Local capture controls and filtering before Ellie-owned persistence."""

from __future__ import annotations

import json

from .conversations import validate_id
from .redact import redact


def policy(store, project: str) -> dict:
    value = store.read_local("privacy").get(project, {})
    return {"paused": value.get("paused", False), "excluded": value.get("excluded", []),
            "archives": value.get("archives", "filtered")}


def blocked(store, project: str, session: str | None = None) -> str | None:
    value = policy(store, project)
    if value["paused"]:
        return "Memory capture is paused for this project"
    if session and session in value["excluded"]:
        return "This conversation is excluded from memory capture"
    return None


def control(store, project: str, action="status", conversation=None, archives=None) -> dict:
    if action not in {"status", "pause", "resume", "exclude", "include"}:
        raise ValueError("invalid privacy action")
    if action in {"exclude", "include"}:
        validate_id(conversation)
    if archives is not None and archives not in {"filtered", "off"}:
        raise ValueError("archives must be filtered or off")
    if action != "status" or archives is not None:
        def change(data):
            current = data.setdefault(project, {})
            if action in {"pause", "resume"}:
                current["paused"] = action == "pause"
            if action in {"exclude", "include"}:
                excluded = set(current.get("excluded", []))
                excluded.add(conversation) if action == "exclude" else excluded.discard(conversation)
                current["excluded"] = sorted(excluded)
            if archives is not None:
                current["archives"] = archives
        store.update_local("privacy", change)
    return policy(store, project)


def filter_value(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [filter_value(item) for item in value]
    if isinstance(value, dict):
        return {key: filter_value(item) for key, item in value.items()}
    return value


def filtered_line(line: bytes) -> bytes:
    if not line.strip():
        return line
    original = json.loads(line)
    safe = filter_value(original)
    if safe == original:
        return line
    return json.dumps(safe, ensure_ascii=False).encode("utf-8") + (b"\n" if line.endswith(b"\n") else b"")


def needs_filtering(path, limit_bytes=None) -> bool:
    with path.open("rb") as stream:
        remaining = limit_bytes
        while remaining is None or remaining > 0:
            line = stream.readline(-1 if remaining is None else remaining)
            if not line:
                break
            if filtered_line(line) != line:
                return True
            if remaining is not None:
                remaining -= len(line)
    return False


def _model_value(value):
    """Omit opaque media and exact derived duplicates from model text only."""
    if isinstance(value, str):
        if value.startswith("data:image/") and ";base64," in value:
            return "[embedded image omitted from text extraction]"
        return value
    if isinstance(value, list):
        return [_model_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _model_value(item) for key, item in value.items()}
    if (value.get("type") == "base64" and str(value.get("media_type", "")).startswith("image/")
            and isinstance(value.get("data"), str)):
        result["data"] = "[embedded image omitted from text extraction]"
    if value.get("type") in ("reasoning", "compaction") and isinstance(value.get("encrypted_content"), str):
        result["encrypted_content"] = "[encrypted reasoning omitted from text extraction]"
    if value.get("type") == "compacted" and isinstance(result.get("payload"), dict):
        payload = result["payload"]
        if "replacement_history_metadata" in payload:
            payload["replacement_history_metadata"] = "[agent replay metadata omitted; replacement history retained above]"
    command = value.get("command", [])
    if isinstance(command, str):
        command = [command]
    if isinstance(command, list) and isinstance(value.get("parsed_cmd"), list):
        for original, projected in zip(value["parsed_cmd"], result["parsed_cmd"]):
            if isinstance(original, dict) and isinstance(original.get("cmd"), str) and original["cmd"] in command:
                projected["cmd"] = "[exact duplicate of command above]"
    return result


def _model_line(line: bytes) -> bytes:
    if not line.strip():
        return line
    original = json.loads(line)
    projected = _model_value(filter_value(original))
    if projected == original:
        return line
    return json.dumps(projected, ensure_ascii=False).encode("utf-8") + (b"\n" if line.endswith(b"\n") else b"")


def read_chunk(path, offset: int = 0, *, upto: int | None = None, max_bytes: int = 1_048_576):
    """Budget model text, while returning a cursor in the original JSONL bytes."""
    chunks, used = [], 0
    with path.open("rb") as stream:
        if offset:
            stream.seek(offset - 1)
            if stream.read(1) != b"\n":
                raise ValueError("transcript cursor is not at a JSONL record boundary")
        stream.seek(offset)
        while upto is None or stream.tell() < upto:
            position = stream.tell()
            line = stream.readline(-1 if upto is None else upto - position)
            if not line:
                break
            projected = _model_line(line)
            if used + len(projected) > max_bytes:
                if not chunks:
                    raise ValueError("one transcript record exceeds the automatic checkpoint limit")
                stream.seek(position)
                break
            chunks.append(projected)
            used += len(projected)
        end = stream.tell()
    return b"".join(chunks).decode("utf-8"), end


def health(store, project: str) -> dict:
    records = store.read_sessions(project)
    jobs = [job for job in store.list_pending() if job.get("project") == project]
    saved = [record.get("last_saved", "") for record in records.values()]
    saved.append(store.read_local("state").get("last_saved", {}).get(project, ""))
    return {**policy(store, project), "last_saved": max(saved, default=""),
            "last_observed": max((record.get("last_observed", "") for record in records.values()), default=""),
            "last_capture": max((record.get("last_capture", "") for record in records.values()), default=""),
            "pending": len(jobs), "failed": sum(job.get("capture") == "failed" for job in jobs),
            "errors": [{"conversation": job.get("session_id"), "error": job.get("error", "")}
                       for job in jobs if job.get("error")]}
