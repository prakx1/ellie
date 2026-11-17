"""Focused memory rendering; interactive selection is added by the launcher."""

from .model import Memory


def meaningful(text: str) -> bool:
    value = text.strip().strip("-* _").casefold()
    return bool(value) and value not in {"none", "(none)", "tbd", "todo", "not set", "n/a"}


def render_memory(memory: Memory, log_limit: int = 25) -> str:
    parts = [f"# Memory: {memory.name}"]
    summary_sections = ("Overview", "Conventions") if memory.name == "project" else ("Goal", "Current state", "Next steps")
    for section in summary_sections:
        content = memory.get_section(section).strip()
        if meaningful(content):
            parts.append(f"## {section}\n{content}")
    items = memory.items
    decisions = [i for i in items if i.type == "D" and i.fields.get("status") == "active"]
    results = sorted([i for i in items if i.type == "R"], key=lambda i: (i.fields.get("date", ""), int(i.id[1:])), reverse=True)[:10]
    findings = [i for i in items if i.type == "F"]
    questions = [i for i in items if i.type == "Q" and i.fields.get("status") == "open"]
    for section, selected in (("Decisions", decisions), ("Results", results), ("Findings", findings), ("Open questions", questions)):
        if selected:
            parts.append("## " + section + "\n\n" + "\n\n".join(i.raw.strip() for i in selected))
    logs = [line for line in memory.get_section("Log").splitlines() if line.strip()]
    if logs and log_limit > 0:
        parts.append("## Log\n" + "\n".join(logs[-log_limit:]))
    return "\n\n".join(parts)
