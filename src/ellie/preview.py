"""Small, local previews of saved knowledge; never use a chat opener as its topic."""

import re

from .briefing import meaningful
from .redact import redact


def text(value):
    value = " ".join(redact(value).split()) if isinstance(value, str) else ""
    if not meaningful(value) or value.casefold().rstrip(".! ") in {
        "work completed", "work complete", "session completed", "session complete", "done",
    }:
        return ""
    return value


def clip(value, limit):
    value = text(value)
    if len(value) <= limit:
        return value
    prefix = value[:limit - 1]
    if " " in prefix:
        prefix = prefix.rsplit(" ", 1)[0]
    return prefix.rstrip() + "…"


def first_line(value):
    if not isinstance(value, str):
        return ""
    for line in value.splitlines():
        line = re.sub(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)", "", line).replace("**", "")
        if text(line) and not line.casefold().startswith("done when:"):
            return text(line)
    return ""


def preview(summary="", titles=(), *, sections=None, fallback="Saved conversation"):
    topics = list(dict.fromkeys(label for title in titles if (label := text(title))))
    summary = text(summary)
    sections = sections or {}
    goal = first_line(sections.get("Goal", ""))
    state = first_line(sections.get("Current state", ""))
    next_step = first_line(sections.get("Next steps", ""))
    return {"title": clip(goal or summary or (topics[0] if topics else state or next_step or fallback), 100),
            "description": clip(goal or summary or "; ".join(topics[:3]) or state or next_step or "No description saved yet", 240),
            "topics": [clip(topic, 80) for topic in topics[:3]],
            "current_state": clip(state, 140), "next_steps": clip(next_step, 140)}


def lines(details):
    result = ["Covers: " + details["description"]]
    topics = details.get("topics", [])
    if topics and not all(topic in details["description"] for topic in topics):
        result.append("Topics: " + "; ".join(topics))
    for key, label in (("current_state", "State"), ("next_steps", "Next")):
        if details.get(key):
            result.append(label + ": " + details[key])
    return result
