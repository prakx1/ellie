from copy import deepcopy
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from unittest.mock import patch

from ellie.capture import plan_jobs, process_job, start_background, uncaptured_status
from ellie.extract import SCHEMA
from ellie.service import MemoryService
from tests.fake_agents import empty_extraction, install_fakes, write_session
from tests.support import IsolatedTest


class CaptureTests(IsolatedTest):
    def test_capture_preserves_live_version_when_another_conversation_changed_item(self):
        session = write_session(self)
        id = self.store.add_item(self.project, "work", "Q", "Which provider?", {"status": "open"}, session=session.id)
        self.store.resolve(self.project, id, "Other conversation answer", session="chat-b")
        self.payload = empty_extraction(worthwhile=False)
        self.save_payload()
        run = self.job(session)
        self.store.update_pending(run, lambda job: job.update({"live_items": [id]}))
        self.assertEqual(process_job(self.store, run)["capture"], "done")
        service = MemoryService(self.store)
        self.addCleanup(service.close)
        original = service.get(self.project, [id], conversations=[session.id])["items"][0]
        self.assertEqual(original["fields"]["status"], "open")
        self.assertNotIn("Other conversation answer", original["text"])

    def setUp(self):
        super().setUp()
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.git(self.checkout, "init")
        self.git(self.checkout, "remote", "add", "origin", "https://" + self.project + ".git")
        self.memory()
        self.fake_env = install_fakes(self)
        self.payload = empty_extraction()

    def save_payload(self):
        Path(os.environ["FAKE_PAYLOAD"]).write_text(json.dumps(self.payload))

    def job(self, session, *, memories=None, source="auto"):
        run = str(uuid.uuid4())
        self.store.write_pending(run, {"run_id": run, "project": self.project, "agent": session.agent,
                                      "session_id": session.id, "cwd": session.cwd, "started": session.started.isoformat(),
                                      "ended": session.ended.isoformat(), "memories": ["work"] if memories is None else memories,
                                      "capture": "pending", "source": source})
        return run

    def calls(self):
        path = Path(os.environ["FAKE_CALLS"])
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def full_payload(self):
        self.payload.update({
            "decisions": [{"title": "Use authlib", "options": ["authlib", "custom"], "chosen": "authlib", "tradeoff": "Dependency", "why": "Less security code", "supersedes": [], "refs": ["src/auth.py"], "memory": None}],
            "results": [{"title": "Iframe refresh", "outcome": "failed", "what": "Silent refresh", "evidence": "Safari ITP", "refs": [], "memory": None}],
            "findings": [{"title": "Gateway IP header", "detail": "X-Real-IP", "evidence": "Request dump", "scope": "project", "memory": None}],
            "questions": [{"text": "Do services bypass limits?", "memory": None}],
            "notes": [{"text": "A durable note", "memory": None}],
            "goal": {"text": "Migrate auth", "done_when": "PKCE everywhere"},
            "state": {"current_state": "Refresh endpoint works", "next_steps": "Migrate clients"},
            "session_summary": "Auth endpoint done"})

    def test_merge_archive_source_and_readonly_codex_flags(self):
        session = write_session(self, paginated=True)
        self.full_payload()
        self.save_payload()
        source = session.path.read_bytes()
        run = self.job(session)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only-sentinel"}):
            result = process_job(self.store, run)
        self.assertEqual(result["capture"], "done", result)
        self.assertIn("1 failed result", result["summary"])
        self.assertEqual(set(result["items"]), {"D1", "R1", "F1", "Q1", "N1"})
        self.assertEqual(self.store.get_item(self.project, "F1")[0], "project")
        self.assertEqual(self.store.get_item(self.project, "D1")[1].fields["source"], "codex · auto · session " + session.id)
        self.assertIn("Migrate clients", self.store.read_memory(self.project, "work").get_section("Next steps"))
        registry = self.store.read_sessions(self.project)[session.id]
        self.assertEqual(gzip.decompress(self.store.path("projects", self.project, "sessions", registry["archive"]).read_bytes()), source)
        self.assertEqual(session.path.read_bytes(), source)
        self.assertEqual(self.store.read_pending(run), {})
        call = self.calls()[0]
        self.assertFalse(call["has_api_key"])
        self.assertIn('sandbox_mode="read-only"', call["args"])
        self.assertIn('approval_policy="never"', call["args"])
        self.assertTrue(any(value.startswith("mcp_servers=") and '"external-server"' in value
                            and "enabled=false" in value for value in call["args"]))
        self.assertEqual(call["args"][-3:], ["fork", session.id, "-"])
        self.assertNotEqual(call["cwd"], str(self.checkout))
        for feature in ("hooks", "plugins", "apps", "shell_tool"):
            self.assertIn(feature, call["args"])

    def test_claude_envelope_and_no_tools(self):
        session = write_session(self, "claude")
        self.full_payload(); self.save_payload()
        result = process_job(self.store, self.job(session))
        self.assertEqual(result["capture"], "done", result)
        args = self.calls()[0]["args"]
        self.assertIn("--fork-session", args)
        self.assertIn("--no-session-persistence", args)
        self.assertIn("--safe-mode", args)
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertEqual(args[args.index("--mcp-config") + 1], '{"mcpServers":{}}')
        self.assertEqual(self.store.get_item(self.project, "R1")[1].fields["source"], "claude-code · auto · session " + session.id)

    def test_invalid_then_valid_retry(self):
        session = write_session(self)
        self.save_payload()
        with patch.dict(os.environ, {"FAKE_MODE": "invalid-then-valid"}):
            result = process_job(self.store, self.job(session))
        self.assertEqual(result["capture"], "done", result)
        self.assertEqual(len(self.calls()), 2)
        self.assertIn("validation error", self.calls()[1]["prompt"])

    def test_invalid_twice_keeps_pending_and_retries_later(self):
        session = write_session(self)
        self.full_payload(); self.save_payload()
        run = self.job(session)
        with patch.dict(os.environ, {"FAKE_MODE": "invalid"}):
            result = process_job(self.store, run)
        self.assertEqual(result["capture"], "failed")
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(self.store.read_pending(run)["capture"], "failed")
        self.assertEqual(self.store.read_memory(self.project, "work").items, [])
        self.assertEqual(process_job(self.store, run)["capture"], "done")
        self.assertEqual(len(self.store.read_memory(self.project, "work").items), 4)

    def test_timeout_and_unsupported_flags_fail_closed(self):
        for mode in ("timeout", "old-version", "missing-output"):
            session = write_session(self)
            self.save_payload()
            self.store.update_local("config", lambda data: data.update({"extract_timeout_sec": 0.1}))
            run = self.job(session)
            with patch.dict(os.environ, {"FAKE_MODE": mode}):
                result = process_job(self.store, run)
            self.assertEqual(result["capture"], "failed", result)
            self.assertTrue(self.store.read_pending(run))
            self.assertEqual(self.store.read_memory(self.project, "work").items, [])

    def test_live_handoff_supersede_resolve_and_dedupe(self):
        session = write_session(self)
        self.store.add_item(self.project, "work", "D", "Old choice", {"status": "active", "chosen": "custom", "why": "Old"})
        self.store.add_item(self.project, "work", "Q", "Known question", {"status": "open"})
        self.full_payload()
        self.payload["decisions"][0]["supersedes"] = ["D1"]
        self.payload["resolved_questions"] = [{"id": "Q1", "answer": "No bypass"}]
        self.save_payload()
        run = self.job(session)
        service = MemoryService(self.store, agent="codex")
        try:
            with patch.dict(os.environ, {"ELLIE_RUN_ID": run}):
                service.handoff(self.project, "work", "Live state wins", "Live next step", "Live handoff")
        finally:
            service.close()
        result = process_job(self.store, run)
        self.assertEqual(result["capture"], "done", result)
        self.assertEqual(self.store.get_item(self.project, "D1")[1].fields["status"], "superseded by D2")
        self.assertEqual(self.store.get_item(self.project, "Q1")[1].fields["answer"], "No bypass")
        self.assertIn("Live state wins", self.store.read_memory(self.project, "work").get_section("Current state"))
        before = len([item for memory in self.store.iter_memories(self.project) for item in memory.items])
        # Simulate failure after writes but before registry completion.
        self.store.update_sessions(self.project, lambda data: data[session.id].update({"capture": "failed"}))
        self.assertEqual(process_job(self.store, self.job(session))["capture"], "done")
        self.assertEqual(len([item for memory in self.store.iter_memories(self.project) for item in memory.items]), before)

    def test_new_target_loaded_override_and_project_fallback(self):
        self.payload["target_memory"] = {"existing": None, "new_name": "fresh", "new_description": "New stream"}
        self.payload["state"] = {"current_state": "New state", "next_steps": "Continue"}
        self.save_payload()
        result = process_job(self.store, self.job(write_session(self), memories=["work"]))
        self.assertEqual(result["capture"], "done", result)
        self.assertNotIn("fresh", [m.name for m in self.store.list_memories(self.project)])
        result = process_job(self.store, self.job(write_session(self), memories=[]))
        self.assertEqual(result["capture"], "done", result)
        self.assertIn("fresh", [m.name for m in self.store.list_memories(self.project)])
        self.full_payload()
        self.payload["target_memory"] = {"existing": None, "new_name": None, "new_description": None}
        self.save_payload()
        result = process_job(self.store, self.job(write_session(self), memories=[]))
        self.assertEqual(result["capture"], "done", result)
        self.assertTrue(all(self.store.get_item(self.project, id)[1].type in {"D", "F"} for id in result["items"]))

    def test_skip_trivial_and_archive_parent_prefix(self):
        self.save_payload()
        trivial = write_session(self, count=1)
        self.assertEqual(process_job(self.store, self.job(trivial))["capture"], "skipped")
        self.assertEqual(self.calls(), [])
        parent = write_session(self, paginated=True)
        prefix = parent.path.read_bytes()
        base = {"thread_id": parent.id, "end_byte_offset": len(prefix), "end_ordinal_exclusive": 3}
        with parent.path.open("a") as stream:
            stream.write(json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "LATER_PARENT_TURN"}}) + "\n")
        child = write_session(self, count=1, paginated=True, history_base=base)
        result = process_job(self.store, self.job(child))
        self.assertEqual(result["capture"], "done", result)
        record = self.store.read_sessions(self.project)[child.id]
        self.assertEqual(len(record["ancestry"]), 1)
        raw = self.store.path("projects", self.project, "sessions", record["ancestry"][0]["archive"]).read_bytes()
        self.assertEqual(gzip.decompress(raw), prefix)

    def test_cross_agent_uses_transcript_not_foreign_resume_id(self):
        session = write_session(self)
        self.save_payload()
        self.store.update_local("config", lambda data: data.update({"extract_with": "claude"}))
        result = process_job(self.store, self.job(session))
        self.assertEqual(result["capture"], "done", result)
        call = self.calls()[0]
        self.assertEqual(call["agent"], "claude")
        self.assertNotIn("--resume", call["args"])
        self.assertIn("User prompt 0", call["prompt"])

    def test_background_worker_and_uncaptured_external_planning(self):
        session = write_session(self)
        self.save_payload()
        self.assertEqual(uncaptured_status(self.store, self.project)["uncaptured_sessions"], 1)
        jobs, errors = plan_jobs(self.store, self.project)
        self.assertEqual(errors, [])
        self.assertEqual(jobs[0]["launched_by"], "external")
        self.assertEqual(self.store.list_pending(), [])
        self.store.write_pending(jobs[0]["run_id"], jobs[0])
        process = start_background(self.store, jobs[0]["run_id"])
        deadline = time.monotonic() + 15
        while self.store.read_pending(jobs[0]["run_id"]) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(process.wait(timeout=15), 0)
        self.assertEqual(self.store.read_sessions(self.project)[session.id]["capture"], "done")
        self.assertEqual(uncaptured_status(self.store, self.project)["uncaptured_sessions"], 0)

    def test_schema_objects_are_strict_and_all_properties_required(self):
        def check(schema):
            if "object" in ([schema.get("type")] if isinstance(schema.get("type"), str) else schema.get("type", [])):
                self.assertFalse(schema["additionalProperties"])
                self.assertEqual(set(schema["properties"]), set(schema["required"]))
            for child in schema.get("properties", {}).values():
                check(child)
            if "items" in schema:
                check(schema["items"])
        check(SCHEMA)

    def cli(self, *args):
        result = subprocess.run([sys.executable, "-m", "ellie", *args], cwd=self.checkout,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_capture_cli_dry_run_then_wait_and_resumed_session(self):
        session = write_session(self)
        self.full_payload(); self.save_payload()
        self.assertIn("Would capture", self.cli("capture", "--dry-run"))
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.store.list_pending(), [])
        self.assertIn("1 failed result", self.cli("capture", "--wait"))
        self.assertEqual(self.store.read_sessions(self.project)[session.id]["launched_by"], "external")
        with session.path.open("a") as stream:
            stream.write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "type": "event_msg", "payload": {"type": "user_message", "message": "Continue"}}) + "\n")
        self.assertEqual(uncaptured_status(self.store, self.project)["uncaptured_sessions"], 1)
        self.payload["state"]["current_state"] = "New resumed state"
        self.save_payload()
        self.cli("capture", "--wait", "--session", session.id)
        self.assertIn("New resumed state", self.store.read_memory(self.project, "work").get_section("Current state"))
        self.assertEqual(len(self.calls()), 2)

    def test_automatic_launcher_capture_and_cross_agent_startup(self):
        session = write_session(self, start=datetime.now(timezone.utc))
        template = self.root / "session-template.jsonl"
        template.write_bytes(session.path.read_bytes())
        session.path.unlink()
        self.full_payload(); self.save_payload()
        record = self.root / "interactive.json"
        with patch.dict(os.environ, {"FAKE_SESSION_TARGET": str(session.path), "FAKE_SESSION_TEMPLATE": str(template), "FAKE_INTERACTIVE_RECORD": str(record)}):
            self.assertIn("capturing session in background", self.cli("start", "codex", "-m", "work"))
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                registry = self.store.read_sessions(self.project)
                if registry.get(session.id, {}).get("capture") in {"done", "failed"}:
                    break
                time.sleep(0.05)
            self.assertEqual(self.store.read_sessions(self.project)[session.id]["capture"], "done", self.store.list_pending())
            self.assertIn("1 failed result", self.cli("status"))
            self.cli("start", "claude", "-m", "work", "--no-capture")
        args = json.loads(record.read_text())
        self.assertIn("Refresh endpoint works", args[-1])
        self.assertIn("Migrate clients", args[-1])
        self.assertEqual(session.path.read_bytes(), template.read_bytes())

    def test_concurrent_workers_do_not_extract_same_session_twice(self):
        session = write_session(self)
        self.full_payload(); self.save_payload()
        run = self.job(session)
        workers = [subprocess.Popen([sys.executable, "-m", "ellie", "_capture", run], cwd=self.root,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for worker in workers:
            out, err = worker.communicate(timeout=30)
            self.assertEqual(worker.returncode, 0, err)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.store.read_sessions(self.project)[session.id]["capture"], "done")

    def test_missing_parent_and_semantic_errors_leave_job_for_retry(self):
        parent = write_session(self, paginated=True)
        base = {"thread_id": parent.id, "end_byte_offset": parent.path.stat().st_size, "end_ordinal_exclusive": 3}
        child = write_session(self, history_base=base)
        parent.path.unlink()
        self.save_payload()
        result = process_job(self.store, self.job(child))
        self.assertEqual(result["capture"], "failed")
        self.assertIn("missing Codex parent history", result["error"])
        self.assertEqual(self.calls(), [])
        self.payload["questions"] = [{"text": "   ", "memory": None}]
        self.save_payload()
        result = process_job(self.store, self.job(write_session(self)))
        self.assertEqual(result["capture"], "failed")
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(self.store.read_memory(self.project, "work").items, [])

    def test_live_items_are_linked_even_when_extractor_has_nothing_new(self):
        session = write_session(self)
        run = self.job(session)
        self.store.update_pending(run, lambda job: job.pop("session_id"))
        service = MemoryService(self.store, agent="codex")
        try:
            with patch.dict(os.environ, {"ELLIE_RUN_ID": run}):
                service.decide(self.project, "work", "Live decision", ["files", "database"], "files", "Manual sync", "Readable")
        finally:
            service.close()
        self.payload = empty_extraction(worthwhile=False)
        self.save_payload()
        result = process_job(self.store, run)
        self.assertEqual(result["capture"], "done", result)
        self.assertEqual(result["items"], ["D1"])
        self.assertIn("1 decision", result["summary"])
