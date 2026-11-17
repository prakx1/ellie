"""Lossless Markdown model. Only the specific spans being edited are replaced."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
import string
import unicodedata

ITEM_SECTIONS = {"D": "Decisions", "R": "Results", "F": "Findings", "Q": "Open questions", "N": "Notes"}
PROJECT_SECTIONS = ("Overview", "Conventions", "Decisions", "Findings", "Open questions", "Notes", "Log")
WORKSTREAM_SECTIONS = ("Goal", "Current state", "Next steps", "Decisions", "Results", "Findings", "Open questions", "Notes", "Log")
ITEM_HEADER = re.compile(r"^[ \t]*###[ \t]+([DRFQN][0-9]+)(?:[ \t]+[·-][ \t]+|[ \t]*:[ \t]+)([^\r\n]+?)[ \t]*$")
FIELD = re.compile(r"^([ \t]*-[ \t]+)([^:\r\n]+?)([ \t]*:[ \t]*)([^\r\n]*)(\r?\n)?$")


def stamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def one_line(text: str, label: str = "value") -> str:
    if not isinstance(text, str) or "\n" in text or "\r" in text:
        raise ValueError(f"{label} must be one line of text")
    return text


def normalized_title(title: str) -> str:
    return " ".join("".join(c for c in title.casefold() if c not in string.punctuation and not unicodedata.category(c).startswith("P")).split())


def _headings(text: str, level: int) -> list[tuple[int, int, str]]:
    result = []
    offset = 0
    fence = None
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip(" \t")
        match = re.match(r"(`{3,}|~{3,})", stripped)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
        elif fence is None:
            match = re.match(r"[ \t]*(#{" + str(level) + r"})[ \t]+([^\r\n]+)", line)
            if match:
                result.append((offset, offset + len(line), match.group(2).strip()))
        offset += len(line)
    return result


@dataclass
class Item:
    raw: str
    memory: str = ""
    section: str = ""

    @property
    def id(self) -> str:
        return self._header().group(1)

    @property
    def title(self) -> str:
        return self._header().group(2)

    @property
    def type(self) -> str:
        return self.id[0]

    def _header(self) -> re.Match:
        match = ITEM_HEADER.fullmatch(self.raw.splitlines()[0]) if self.raw else None
        if not match:
            raise ValueError("invalid item heading")
        return match

    @property
    def fields(self) -> dict[str, str]:
        result = {}
        for line in self.raw.splitlines(keepends=True)[1:]:
            match = FIELD.fullmatch(line)
            if match:
                result[match.group(2).strip()] = match.group(4).strip()
        return result

    @property
    def body(self) -> str:
        return "".join(line for line in self.raw.splitlines(keepends=True)[1:] if not FIELD.fullmatch(line))

    def set_field(self, key: str, value: str) -> None:
        one_line(key, "field key")
        one_line(value)
        if not key or ":" in key:
            raise ValueError("invalid field key")
        lines = self.raw.splitlines(keepends=True)
        matches = [(i, FIELD.fullmatch(line)) for i, line in enumerate(lines[1:], 1)]
        matches = [(i, m) for i, m in matches if m and m.group(2).strip() == key]
        if matches:
            i, match = matches[-1]
            trailing = match.group(4)[len(match.group(4).rstrip()):]
            lines[i] = match.group(1) + match.group(2) + match.group(3) + value + trailing + (match.group(5) or "")
        else:
            if not lines[0].endswith("\n"):
                lines[0] += "\n"
            lines.insert(1, f"- {key}: {value}\n")
        self.raw = "".join(lines)

    @classmethod
    def create(cls, id: str, title: str, fields: dict[str, str], body: str = "") -> Item:
        if not re.fullmatch(r"[DRFQN][0-9]+", id):
            raise ValueError("invalid item id")
        if not one_line(title, "title").strip():
            raise ValueError("title must not be empty")
        for key, value in fields.items():
            one_line(key, "field key")
            one_line(value, key)
            if not key or ":" in key:
                raise ValueError("invalid field key")
        item = cls(f"### {id} · {title}\n" + "".join(f"- {k}: {v}\n" for k, v in fields.items()) + body)
        item.validate()
        return item

    def validate(self) -> None:
        fields = self.fields
        required = {"D": ("status", "chosen", "why"), "R": ("outcome", "what"), "F": ("detail", "scope"), "Q": ("status",), "N": ()}
        missing = [k for k in ("date", "source", *required[self.type]) if k not in fields]
        if missing:
            raise ValueError("missing item fields: " + ", ".join(missing))
        status = fields.get("status", "")
        if self.type == "D" and status not in ("active", "reverted") and not re.fullmatch(r"superseded by D[0-9]+", status):
            raise ValueError("invalid decision status")
        if self.type == "R" and fields["outcome"] not in ("worked", "failed", "partial"):
            raise ValueError("invalid result outcome")
        if self.type == "F" and fields["scope"] not in ("project", "workstream"):
            raise ValueError("invalid finding scope")
        if self.type == "Q" and status not in ("open", "resolved"):
            raise ValueError("invalid question status")


@dataclass(frozen=True)
class MemoryMeta:
    name: str
    description: str = ""
    status: str = "active"
    updated: str = ""
    updated_by: str = ""
    archived: bool = False


class Memory:
    def __init__(self, text: str, *, name: str = "", original: bytes | None = None):
        self.text = text
        self.fallback_name = name
        self.original = original

    @classmethod
    def parse(cls, content: str | bytes, *, name: str = "") -> Memory:
        raw = content.encode("utf-8") if isinstance(content, str) else content
        return cls(raw.decode("utf-8"), name=name, original=raw)

    def render(self) -> str:
        return self.text

    def to_bytes(self) -> bytes:
        return self.text.encode("utf-8")

    def _frontmatter(self) -> tuple[int, int, list[str]] | None:
        lines = self.text.splitlines(keepends=True)
        if not lines or lines[0].strip("\ufeff \t\r\n") != "---":
            return None
        offset = len(lines[0])
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                return len(lines[0]), offset, lines[1:i]
            offset += len(line)
        return None

    @property
    def meta(self) -> dict[str, str]:
        front = self._frontmatter()
        result = {}
        if front:
            for line in front[2]:
                key, sep, value = line.partition(":")
                if sep:
                    result[key.strip()] = value.strip()
        return result

    @property
    def name(self) -> str:
        return self.meta.get("name", self.fallback_name)

    def set_meta(self, key: str, value: str) -> None:
        one_line(key)
        one_line(value)
        if not key or ":" in key:
            raise ValueError("invalid frontmatter key")
        front = self._frontmatter()
        if not front:
            self.text = f"---\n{key}: {value}\n---\n\n" + self.text
            return
        start, end, lines = front
        indices = [i for i, line in enumerate(lines) if ":" in line and line.partition(":")[0].strip() == key]
        if indices:
            i = indices[-1]
            prefix = lines[i].split(":", 1)[0]
            lines[i] = f"{prefix}: {value}\n"
        else:
            lines.append(f"{key}: {value}\n")
        self.text = self.text[:start] + "".join(lines) + self.text[end:]

    def normalized_for_save(self) -> bytes:
        memory = Memory(self.text.replace("\r\n", "\n").replace("\r", "\n"))
        front = memory._frontmatter()
        if front:
            start, end, lines = front
            seen = set()
            kept = []
            for line in reversed(lines):
                key, sep, _ = line.partition(":")
                if sep:
                    key = key.strip()
                    if key in seen:
                        continue
                    seen.add(key)
                kept.append(line)
            memory.text = memory.text[:start] + "".join(reversed(kept)) + memory.text[end:]
        return memory.to_bytes()

    def _sections(self) -> list[tuple[int, int, int, str]]:
        headings = _headings(self.text, 2)
        return [(start, body, headings[i + 1][0] if i + 1 < len(headings) else len(self.text), title) for i, (start, body, title) in enumerate(headings)]

    @property
    def sections(self) -> dict[str, str]:
        return {title: self.text[body:end] for _, body, end, title in self._sections()}

    def get_section(self, title: str) -> str:
        return self.sections.get(title, "")

    def set_section(self, title: str, content: str) -> None:
        one_line(title)
        for _, body, end, found in self._sections():
            if found == title:
                self.text = self.text[:body] + content.rstrip("\r\n") + "\n\n" + self.text[end:]
                return
        self.text = self.text.rstrip("\r\n") + f"\n\n## {title}\n" + content.rstrip("\r\n") + "\n\n"

    def _item_spans(self) -> list[tuple[int, int, Item]]:
        spans = []
        for _, body, end, section in self._sections():
            headings = _headings(self.text[body:end], 3)
            for i, (start, _, _) in enumerate(headings):
                stop = headings[i + 1][0] if i + 1 < len(headings) else end - body
                raw = self.text[body + start:body + stop]
                if ITEM_HEADER.fullmatch(raw.splitlines()[0]):
                    spans.append((body + start, body + stop, Item(raw, self.name, section)))
        return spans

    @property
    def items(self) -> list[Item]:
        return [item for _, _, item in self._item_spans()]

    def get_item(self, id: str) -> Item:
        for item in self.items:
            if item.id == id:
                return item
        raise KeyError(id)

    def replace_item(self, item: Item) -> None:
        for start, end, old in self._item_spans():
            if old.id == item.id:
                self.text = self.text[:start] + item.raw + self.text[end:]
                return
        raise KeyError(item.id)

    def add_item(self, item: Item) -> None:
        section = ITEM_SECTIONS[item.type]
        if self.name == "project" and section not in PROJECT_SECTIONS:
            raise ValueError(f"{section} is not a project memory section")
        if item.id in {old.id for old in self.items}:
            raise ValueError("duplicate item id")
        content = self.get_section(section)
        self.set_section(section, content.rstrip("\r\n") + "\n\n" + item.raw.rstrip("\r\n"))

    def append_log(self, agent: str, kind: str, text: str, session: str | None = None) -> None:
        if kind not in {"goal", "decision", "result", "finding", "question", "note", "progress", "issue", "handoff", "import"}:
            raise ValueError("invalid log kind")
        for value in (agent, text, session or ""):
            one_line(value)
        line = f"- {stamp()} · {agent} · {kind}: {text}"
        if session:
            line += " · session " + session
        self.set_section("Log", self.get_section("Log").rstrip("\r\n") + "\n" + line)

    @classmethod
    def new(cls, name: str, description: str = "", *, agent: str = "you", goal: str = "", done_when: str = "") -> Memory:
        for value in (name, description, agent):
            one_line(value)
        now = stamp()
        text = "---\n" + "".join(f"{k}: {v}\n" for k, v in {"name": name, "description": description, "status": "active", "created": now, "updated": now, "updated_by": agent}.items()) + "---\n\n"
        text += "".join(f"## {section}\n\n" for section in (PROJECT_SECTIONS if name == "project" else WORKSTREAM_SECTIONS))
        memory = cls(text, name=name)
        if name != "project" and (goal or done_when):
            memory.set_section("Goal", goal + ("\n\n**Done when:** " + done_when if done_when else ""))
        return memory
