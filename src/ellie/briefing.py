"""Focused rendering and plain-input memory/history selectors."""

from collections import Counter
from dataclasses import dataclass, field
import sys

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


@dataclass
class Selection:
    memories: list[str] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    drafts: dict[str, Memory] = field(default_factory=dict)


def render_briefing(service, project: str, selection: Selection) -> str:
    parts = []
    for name in dict.fromkeys(["project", *selection.memories]):
        if name in selection.drafts:
            memory = selection.drafts[name]
        else:
            try:
                memory = service.store.read_memory(project, name)
            except FileNotFoundError:
                if name != "project":
                    raise
                memory = Memory.new("project")
        parts.append(render_memory(memory, service.config["log_limit"]))
    if selection.ids:
        items = service.get(project, list(dict.fromkeys(selection.ids)))["items"]
        parts.append("## Selected from project history\n\n" + "\n\n".join(
            f"From {item['project']} · memory: {item['memory']}\n\n{item['text'].strip()}" for item in items))
    return "\n\n".join(parts)


def select_history(service, project: str, query: str, *, interactive: bool | None = None, input_fn=None, output=None) -> Selection:
    input_fn = input_fn or input
    output = output or sys.stdout
    if interactive is None:
        interactive = sys.stdin.isatty()
    hits = service.index.recall(query, project=project, limit=20)
    selected = set()
    selected_memories = set()
    used = 0
    for hit in hits:
        size = len(service.store.get_item(project, hit.id)[1].raw)
        if len(selected) >= service.config["brief_preselect"]:
            break
        if used + size <= 8000:
            selected.add(hit.id)
            used += size
    while interactive:
        print(f'\nRelevant to "{query}":', file=output)
        rows = [("item", hit.id) for hit in hits]
        for i, hit in enumerate(hits, 1):
            print(f" {'[x]' if hit.id in selected else '[ ]'} {i}) {hit.id} {hit.title} · {hit.date} · {hit.status or hit.outcome} · {hit.memory}", file=output)
        counts = Counter(hit.memory for hit in hits if hit.memory != "project")
        for name, count in sorted(counts.items()):
            rows.append(("memory", name))
            print(f" {'[x]' if name in selected_memories else '[ ]'} {len(rows)}) memory: {name} ({count} matches)", file=output)
        try:
            command = input_fn("numbers = toggle · a <query> = search more · s <ID/number> = show · Enter = done · q = cancel: ").strip()
        except EOFError:
            command = ""
        if not command:
            break
        if command == "q":
            return Selection()
        if command.startswith("a "):
            more = service.index.recall(command[2:], project=project, limit=20)
            known = {hit.id for hit in hits}
            hits.extend(hit for hit in more if hit.id not in known)
            continue
        if command.startswith("s "):
            reference = command[2:].strip()
            try:
                if reference.isdigit():
                    kind, reference = rows[int(reference) - 1]
                    if kind == "memory":
                        print(service.store.read_memory(project, reference).render(), file=output)
                        continue
                print(service.store.get_item(project, reference)[1].raw, file=output)
            except (KeyError, IndexError, ValueError) as exc:
                print(f"ellie: cannot show that selection: {exc}", file=output)
            continue
        try:
            numbers = [int(value) for value in command.replace(",", " ").split()]
            if not numbers or any(number < 1 or number > len(rows) for number in numbers):
                raise ValueError
            for number in numbers:
                kind, value = rows[number - 1]
                target = selected if kind == "item" else selected_memories
                target.symmetric_difference_update({value})
        except ValueError:
            print("ellie: enter valid row numbers, a query, s ID, or q", file=output)
    return Selection(sorted(selected_memories), [hit.id for hit in hits if hit.id in selected])


def pick_memories(service, project: str, *, input_fn=None, output=None, dry_run: bool = False) -> Selection:
    input_fn = input_fn or input
    output = output or sys.stdout
    status = service.status(project)
    memories = status["memories"]
    last = [name for name in status["last_used"] if name in {m["name"] for m in memories}]
    print(f"ellie · {project} (project memory always loads)", file=output)
    for i, meta in enumerate(memories, 1):
        marker = "*" if meta["name"] in last else " "
        print(f"{marker} {i}) {meta['name']}  {meta['description']}  {meta['updated']} · {meta['updated_by']}", file=output)
    if status["uncaptured_sessions"]:
        print(f"{status['uncaptured_sessions']} earlier session(s) not captured. Run ellie capture after this.", file=output)
    while True:
        try:
            answer = input_fn("Pick [1,2 · Enter = last used (*) · 0 = none · n = new · / = search]: ").strip()
        except EOFError:
            answer = ""
        if not answer:
            return Selection(last)
        if answer == "0":
            return Selection()
        if answer == "n":
            name = input_fn("Name: ").strip()
            description = input_fn("Description: ").strip()
            goal = input_fn("Goal: ").strip()
            done = input_fn("Done when: ").strip()
            if dry_run:
                from .paths import validate_name
                validate_name(name, allow_project=False)
                return Selection([name], drafts={name: Memory.new(name, description, goal=goal, done_when=done)})
            service.create(project, name, description, goal, done)
            return Selection([name])
        if answer.startswith("/"):
            task = answer[1:].strip() or input_fn("Task: ")
            return select_history(service, project, task, interactive=True, input_fn=input_fn, output=output)
        try:
            numbers = [int(value) for value in answer.replace(",", " ").split()]
            if not numbers or any(n < 1 or n > len(memories) for n in numbers):
                raise ValueError
            return Selection(list(dict.fromkeys(memories[n - 1]["name"] for n in numbers)))
        except ValueError:
            print("ellie: choose valid memory numbers, 0, n, or /", file=output)
