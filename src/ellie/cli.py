"""Ellie's standard-library command-line interface."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import sys

from . import __version__
from .briefing import render_briefing, select_history
from .paths import ellie_home
from .service import DEFAULTS, MemoryService


class EllieParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def parser() -> argparse.ArgumentParser:
    root = EllieParser(prog="ellie", description="🐘 Local project memory for coding agents")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command")
    for name in ("status", "where", "projects", "reindex", "mcp"):
        commands.add_parser(name)
    start = commands.add_parser("start", help="Start an agent with selected project memory")
    start.add_argument("agent", nargs="?", choices=["codex", "claude"])
    choices = start.add_mutually_exclusive_group()
    choices.add_argument("-m", "--memory", action="append")
    choices.add_argument("-p", "--project-only", action="store_true")
    choices.add_argument("--new")
    start.add_argument("-d", "--description")
    start.add_argument("--about")
    start.add_argument("--with", dest="with_ids", action="append")
    start.add_argument("--no-capture", action="store_true")
    start.add_argument("--dry-run", action="store_true")
    brief = commands.add_parser("brief", help="Select and print history relevant to a task")
    brief.add_argument("task")
    brief.add_argument("--json", action="store_true")
    recall = commands.add_parser("recall", help="Search project history")
    recall.add_argument("query")
    recall.add_argument("--type", dest="types")
    recall.add_argument("--all-projects", action="store_true")
    recall.add_argument("--include-superseded", action="store_true")
    recall.add_argument("-n", type=int, default=10)
    show = commands.add_parser("show")
    show.add_argument("name", nargs="?", default="project")
    new = commands.add_parser("new")
    new.add_argument("name")
    new.add_argument("-d", "--description", default="")
    new.add_argument("--goal", default="")
    new.add_argument("--done-when", default="")
    edit = commands.add_parser("edit")
    edit.add_argument("name", nargs="?", default="project")
    log = commands.add_parser("log")
    log.add_argument("name")
    log.add_argument("text")
    log.add_argument("-k", "--kind", choices=["progress", "issue", "note"], default="note")
    for name in ("archive", "restore"):
        command = commands.add_parser(name)
        command.add_argument("name")
    import_command = commands.add_parser("import")
    import_command.add_argument("file", type=Path)
    import_command.add_argument("--as", dest="name", required=True)
    import_command.add_argument("-d", "--description")
    link = commands.add_parser("link")
    link.add_argument("project")
    config = commands.add_parser("config")
    config.add_argument("key", nargs="?")
    config.add_argument("value", nargs="?")
    return root


def set_config(service, key, value):
    if key not in DEFAULTS:
        raise ValueError("unknown config key: " + key)
    if isinstance(DEFAULTS[key], int):
        try:
            value = int(value)
        except ValueError:
            raise ValueError(f"{key} must be an integer") from None
        if value < (0 if key in {"log_limit", "brief_preselect"} else 1):
            raise ValueError(f"{key} is out of range")
    choices = {"agent": {"codex", "claude"}, "capture": {"auto", "ask", "off"}, "extract_with": {"same", "codex", "claude"}}
    if key in choices and value not in choices[key]:
        raise ValueError("invalid value for " + key)
    if key == "backfill_default_since" and not re.fullmatch(r"[1-9][0-9]*[dhw]", value):
        raise ValueError("time windows use a positive count followed by d, h, or w")
    service.store.update_local("config", lambda data: data.update({key: value}))
    return value


def dispatch(service, options, agent_args):
    command = options.command or "status"
    if command == "start":
        from .launch import start
        return start(service, options, agent_args)
    if command == "config":
        if options.key is None:
            print(json.dumps(service.config, indent=2))
        elif options.value is None:
            if options.key not in DEFAULTS:
                raise ValueError("unknown config key: " + options.key)
            print(service.config[options.key])
        else:
            print(set_config(service, options.key, options.value))
        return 0
    if command == "projects":
        for project in service.store.list_projects():
            print(f"{project}  {len(service.store.list_memories(project))} memories  {len(service.store.list_memories(project, True))} archived")
        return 0
    if command == "reindex":
        print(f"Indexed {service.index.reindex()} items.")
        return 0
    project = service.project()
    if command == "status":
        status = service.status(project)
        print("Project: " + project)
        print("Repo: " + str(service.store.resolve_project(Path.cwd())[1]))
        for memory in status["memories"]:
            marker = "*" if memory["name"] in status["last_used"] else " "
            print(f"{marker} {memory['name']}  {memory['description']}  {memory['updated']} · {memory['updated_by']}")
        if not status["memories"]:
            print("No workstreams yet. Create one with ellie new NAME.")
        print(f"{status['archived_count']} archived memories")
        print(f"{status['uncaptured_sessions']} uncaptured sessions" + (" — run ellie capture" if status["uncaptured_sessions"] else ""))
    elif command == "new":
        service.create(project, options.name, options.description, options.goal, options.done_when)
        print("Created " + options.name)
    elif command == "show":
        if re.fullmatch(r"[DRFQN][0-9]+", options.name) or ":" in options.name:
            print(service.get(project, [options.name])["items"][0]["text"], end="")
        else:
            print(service.store.read_memory(project, options.name).render(), end="")
    elif command == "edit":
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "vi")
        service.store.edit_memory(project, options.name, shlex.split(editor, posix=os.name != "nt"))
    elif command == "log":
        service.log(project, options.name, options.text, options.kind)
    elif command in {"archive", "restore"}:
        service.store.move_memory(project, options.name, command == "archive")
    elif command == "import":
        service.store.import_memory(project, options.file, options.name, options.description)
        print("Imported " + options.name)
    elif command == "link":
        service.store.link(Path.cwd(), options.project)
        print("Linked to " + options.project)
    elif command == "recall":
        types = options.types.split(",") if options.types else None
        hits = service.recall(project, options.query, types, options.n, options.include_superseded, options.all_projects)["items"]
        for hit in hits:
            prefix = hit["project"] + ":" if options.all_projects else ""
            print(f"{prefix}{hit['id']} · {hit['title']} · {hit['date']} · {hit['status'] or hit['outcome']} · {hit['memory']}\n  {hit['snippet']}")
    elif command == "brief":
        selection = select_history(service, project, options.task, interactive=False if options.json else None)
        context = render_briefing(service, project, selection)
        print(json.dumps({"project": project, "memories": selection.memories, "ids": selection.ids, "briefing": context}, ensure_ascii=False) if options.json else context)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    agent_args = []
    if "--" in argv:
        position = argv.index("--")
        argv, agent_args = argv[:position], argv[position + 1:]
    try:
        options = parser().parse_args(argv)
        if agent_args and options.command != "start":
            raise ValueError("arguments after -- are only supported by ellie start")
        if options.command == "where":
            print(ellie_home())
            return 0
        if options.command == "mcp":
            from .mcp_server import main as mcp
            return mcp()
        service = MemoryService()
        try:
            return dispatch(service, options, agent_args)
        finally:
            service.close()
    except BrokenPipeError:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        print("ellie: interrupted", file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError, EOFError, sqlite3.Error) as exc:
        print("ellie: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
