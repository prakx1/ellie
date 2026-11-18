"""Canned CLIs and agent-owned session fixtures; never contact a model."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import uuid

from ellie.agents import adapter


def empty_extraction(memory="work", *, worthwhile=True):
    return {"worthwhile": worthwhile, "target_memory": {"existing": memory, "new_name": None, "new_description": None},
            "goal": None, "decisions": [], "results": [], "findings": [], "questions": [],
            "resolved_questions": [], "notes": [], "state": None, "session_summary": "Work completed"}


def write_session(test, agent="codex", *, id=None, count=2, paginated=False, cwd=None, history_base=None, start=None):
    id = id or str(uuid.uuid4())
    cwd = str(cwd or test.checkout)
    start = start or datetime.now(timezone.utc) - timedelta(minutes=10)
    records = []
    if agent == "codex":
        path = Path(os.environ["CODEX_HOME"]) / "sessions" / start.strftime("%Y/%m/%d") / ("rollout-2026-11-18T00-00-00-" + id + ".jsonl")
        meta = {"id": id, "cwd": cwd, "timestamp": start.isoformat(), "source": "cli"}
        if paginated:
            meta["history_mode"] = "paginated"
        if history_base:
            meta["history_base"] = history_base
        records.append({"timestamp": start.isoformat(), "type": "session_meta", "payload": meta, "ordinal": 0})
        records.append({"timestamp": start.isoformat(), "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>injected</environment_context>"}]}})
        for i in range(count):
            content = "User prompt " + str(i)
            payload = {"type": "item_completed", "item": {"type": "UserMessage", "id": "message-" + str(i), "content": [{"type": "text", "text": content}]}} if paginated else {"type": "user_message", "message": content}
            records.append({"timestamp": (start + timedelta(seconds=i + 1)).isoformat(), "type": "event_msg", "payload": payload, "ordinal": i + 1})
    else:
        path = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / cwd.replace("/", "-").replace(".", "-") / (id + ".jsonl")
        records.append({"type": "custom-title", "sessionId": id, "customTitle": "Fixture"})
        for i in range(count):
            records.append({"type": "user", "sessionId": id, "cwd": cwd, "timestamp": (start + timedelta(seconds=i)).isoformat(), "uuid": "prompt-" + str(i), "message": {"role": "user", "content": "User prompt " + str(i)}})
        records.extend([
            {"type": "user", "sessionId": id, "cwd": cwd, "timestamp": start.isoformat(), "uuid": "tool", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}},
            {"type": "user", "sessionId": id, "cwd": cwd, "timestamp": start.isoformat(), "uuid": "meta", "isMeta": True, "message": {"role": "user", "content": "Injected"}},
        ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return adapter(agent).read(path)


FAKE_SCRIPT = r'''
import json, os, pathlib, sys, time
args=sys.argv[1:]
agent=pathlib.Path(sys.argv[0]).name
if '--help' in args:
    print('--ephemeral --ignore-user-config --ignore-rules --output-schema --disable --fork-session --no-session-persistence --json-schema --tools --strict-mcp-config --safe-mode' if os.environ.get('FAKE_MODE') != 'old-version' else 'old help')
    raise SystemExit(0)
if args[:3] == ['mcp','list','--json']:
    print('[{"name":"external-server"}]')
    raise SystemExit(0)
if not (agent=='codex' and args and args[0]=='exec') and not (agent=='claude' and '-p' in args):
    if os.environ.get('FAKE_INTERACTIVE_RECORD'):
        pathlib.Path(os.environ['FAKE_INTERACTIVE_RECORD']).write_text(json.dumps(args))
    if agent=='codex' and os.environ.get('FAKE_SESSION_TARGET'):
        p=pathlib.Path(os.environ['FAKE_SESSION_TARGET']); p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(pathlib.Path(os.environ['FAKE_SESSION_TEMPLATE']).read_bytes())
    raise SystemExit(0)
counter=pathlib.Path(os.environ['FAKE_COUNTER'])
count=int(counter.read_text())+1 if counter.exists() else 1
counter.write_text(str(count))
prompt=sys.stdin.read()
with pathlib.Path(os.environ['FAKE_CALLS']).open('a') as log:
    log.write(json.dumps({'agent':agent,'args':args,'prompt':prompt,'cwd':os.getcwd(),'has_api_key':bool(os.environ.get('OPENAI_API_KEY') or os.environ.get('ANTHROPIC_API_KEY'))})+'\n')
mode=os.environ.get('FAKE_MODE','valid')
if mode=='timeout': time.sleep(10)
if mode=='error':
    print('Canned CLI failure',file=sys.stderr); raise SystemExit(9)
payload=json.loads(pathlib.Path(os.environ['FAKE_PAYLOAD']).read_text())
invalid=mode=='invalid' or (mode=='invalid-then-valid' and count==1)
raw='{}' if invalid else json.dumps(payload)
if agent=='codex':
    if mode!='missing-output': pathlib.Path(args[args.index('-o')+1]).write_text(raw)
    print('{"type":"turn.completed"}')
else:
    print(json.dumps({'type':'result','subtype':'success','structured_output':json.loads(raw)}) if mode!='missing-output' else '{"type":"result","subtype":"success"}')
'''


def install_fakes(test):
    directory = test.root / "fake-bin"
    directory.mkdir()
    for agent in ("codex", "claude"):
        path = directory / agent
        path.write_text("#!" + sys.executable + "\n" + FAKE_SCRIPT)
        path.chmod(0o755)
    environment = {"PATH": str(directory) + os.pathsep + os.environ["PATH"],
                   "FAKE_PAYLOAD": str(test.root / "payload.json"), "FAKE_CALLS": str(test.root / "calls.jsonl"),
                   "FAKE_COUNTER": str(test.root / "counter"), "FAKE_MODE": "valid"}
    os.environ.update(environment)
    return environment
