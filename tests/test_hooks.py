import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

from ellie.service import MemoryService
from tests.fake_agents import empty_extraction, install_fakes, write_session
from tests.support import IsolatedTest


class HookTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.git(self.checkout, "init")
        self.git(self.checkout, "remote", "add", "origin", "https://" + self.project + ".git")
        self.memory()
        install_fakes(self)

    def hook(self, session, event, **extra):
        payload = {"session_id": session.id, "cwd": str(self.checkout), "transcript_path": str(session.path), **extra}
        result = subprocess.run([sys.executable, "-m", "ellie", "hook", session.agent, event, "--no-worker"],
                                input=json.dumps(payload), capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_first_reply_offers_a_numbered_picker_without_loading_old_content(self):
        self.store.add_item(self.project, "work", "N", "Login decision", {},
                            session="past-login", body="Full login history stays unloaded")
        self.store.update_sessions(self.project, lambda data: data["past-login"].update(
            {"title": "hello, can we start?", "summary": "Fix login retries", "agent": "codex",
             "started": "2026-11-20T10:00:00Z"}))
        self.store.add_item(self.project, "project", "N", "Shared private detail", {})
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent):
                session = write_session(self, agent)
                for event in ("SessionStart", "UserPromptSubmit"):
                    context = self.hook(session, event, prompt="Work on login")["hookSpecificOutput"]["additionalContext"]
                    self.assertIn("[ellie memory picker]", context)
                    self.assertIn("0) Start fresh", context)
                    self.assertIn("1) Conversation: Fix login retries", context)
                    self.assertNotIn("hello, can we start?", context)
                    self.assertIn("past-login", context)
                    self.assertIn("Workstream: work", context)
                    self.assertIn("wait for the user's choice", context)
                    self.assertNotIn("Full login history stays unloaded", context)
                    self.assertNotIn("Shared private detail", context)
                    self.assertLessEqual(len(context), 7000)
        self.assertFalse(Path(os.environ["FAKE_CALLS"]).exists())

    def test_picker_shows_what_a_memory_covers_and_its_next_step(self):
        self.store.add_item(self.project, "work", "N", "GitHub deployment setup", {}, session="past-work")
        self.store.add_item(self.project, "work", "N", "Publish the product website", {}, session="past-work")
        service = MemoryService(self.store)
        self.addCleanup(service.close)
        with service.in_session("past-work"):
            service.handoff(self.project, "work", "Deployment pipeline configured", "Add the homepage", "Work completed")
        self.store.update_sessions(self.project, lambda data: data["past-work"].update({"title": "hello"}))
        for agent in ("codex", "claude"):
            session = write_session(self, agent)
            context = self.hook(session, "SessionStart")["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Covers: GitHub deployment setup; Publish the product website", context)
            self.assertIn("State: Deployment pipeline configured", context)
            self.assertIn("Next: Add the homepage", context)
            self.assertIn("Show each option's Covers/State/Next preview", context)
            self.assertNotIn("Conversation: Work completed", context)
            self.assertNotIn("Conversation: hello", context)

    def test_a_chosen_scope_is_preserved_without_another_picker_on_resume(self):
        self.store.add_item(self.project, "work", "N", "Login history", {},
                            session="past-login", body="Selected login body")
        self.store.add_item(self.project, "work", "N", "Payments history", {},
                            session="past-payments", body="Unselected payments body")
        service = MemoryService(self.store)
        self.addCleanup(service.close)
        for selected in (None, ["past-login"], []):
            with self.subTest(selected=selected):
                session = write_session(self)
                self.hook(session, "SessionStart")
                with service.in_session(session.id):
                    service.load(self.project, ["work"], conversations=selected)
                for event in ("UserPromptSubmit", "SessionStart"):
                    context = self.hook(session, event)["hookSpecificOutput"]["additionalContext"]
                    self.assertNotIn("[ellie memory picker]", context)
                    if selected is not None:
                        self.assertNotIn("Unselected payments body", context)
                        if event == "SessionStart":
                            self.assertEqual("Selected login body" in context, bool(selected))
                self.assertTrue(self.store.read_sessions(self.project)[session.id]["context_selected"])

    def test_empty_chats_and_archived_workstreams_do_not_offer_meaningless_choices(self):
        self.store.move_memory(self.project, "work", True)
        for agent in ("codex", "claude"):
            session = write_session(self, agent)
            context = self.hook(session, "SessionStart")["hookSpecificOutput"]["additionalContext"]
            self.assertNotIn("[ellie memory picker]", context)
        self.store.add_item(self.project, "project", "N", "Saved after startup", {})
        context = self.hook(session, "UserPromptSubmit")["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("[ellie memory picker]", context)

    def test_picker_numbers_stay_stable_when_another_chat_saves_new_memory(self):
        self.store.add_item(self.project, "work", "N", "Earlier history", {}, session="past-earlier")
        session = write_session(self)
        before = self.hook(session, "SessionStart")["hookSpecificOutput"]["additionalContext"]
        self.store.add_item(self.project, "work", "N", "Later history", {}, session="past-later")
        after = self.hook(session, "UserPromptSubmit", prompt="1")["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(before, after)

    def test_large_catalog_fits_the_hook_budget_and_keeps_a_more_choice(self):
        self.store.move_memory(self.project, "work", True)
        for number in range(10):
            name = "work-" + str(number) + "x" * 225
            self.store.create_memory(self.project, name, "Description " * 30)
            past = "past-" + str(number) + "y" * 120
            self.store.add_item(self.project, name, "N", "Saved history", {}, session=past)
            self.store.update_sessions(self.project, lambda data: data[past].update(
                {"title": "Long conversation title " * 20, "agent": "claude-code"}))
        session = write_session(self)
        context = self.hook(session, "SessionStart")["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(context), 7000)
        self.assertIn("m) More choices", context)
        self.assertIn("Never assume all history", context)

    def test_launcher_selection_and_legacy_bindings_are_not_prompted_again(self):
        self.store.add_item(self.project, "work", "N", "Past history", {}, session="past-chat")
        run = "launcher-selection"
        self.store.write_pending(run, {"run_id": run, "project": self.project,
                                      "memories": ["work"], "context_conversations": []})
        session = write_session(self)
        with patch.dict(os.environ, {"ELLIE_RUN_ID": run}):
            context = self.hook(session, "SessionStart")["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("[ellie memory picker]", context)
        self.assertNotIn("Past history", context)
        legacy = write_session(self)
        self.store.update_sessions(self.project, lambda data: data.update(
            {legacy.id: {"bound_memories": ["work"], "context_conversations": ["past-chat"]}}))
        context = self.hook(legacy, "SessionStart")["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("[ellie memory picker]", context)
        self.assertIn("Past history", context)

    def test_normal_session_is_bound_and_durably_queued_without_a_model_in_hook(self):
        session = write_session(self)
        response = self.hook(session, "SessionStart")
        context = response["hookSpecificOutput"]["additionalContext"]
        self.assertIn(session.id, context)
        record = self.store.read_sessions(self.project)[session.id]
        self.assertTrue(record["bound_memories"])
        self.hook(session, "UserPromptSubmit", prompt="Investigate <private>hidden</private> retries")
        self.hook(session, "PostToolUse", tool_name="Bash", tool_use_id="tool-1")
        self.hook(session, "Stop", turn_id="turn-1")
        jobs = self.store.list_pending()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["session_id"], session.id)
        self.assertTrue(jobs[0]["incremental"])
        self.assertNotIn("hidden", json.dumps(self.store.read_sessions(self.project)))
        self.assertFalse(Path(os.environ["FAKE_CALLS"]).exists())

    def test_checkpoints_capture_only_new_records_and_retain_source_conversation(self):
        from ellie.capture import process_job
        session = write_session(self)
        self.hook(session, "SessionStart")
        target = self.store.read_sessions(self.project)[session.id]["bound_memories"][0]
        value = empty_extraction(target)
        value["notes"] = [{"text": "First checkpoint", "memory": None}]
        Path(os.environ["FAKE_PAYLOAD"]).write_text(json.dumps(value))
        self.hook(session, "Stop", turn_id="turn-1")
        job = self.store.list_pending()[0]
        result = process_job(self.store, job["run_id"])
        self.assertEqual(result["capture"], "done", result)
        first_size = session.path.stat().st_size
        with session.path.open("a") as stream:
            stream.write(json.dumps({"timestamp": "2026-11-19T09:00:00Z", "type": "event_msg", "payload": {"type": "user_message", "message": "Second delta"}}) + "\n")
        value["notes"] = [{"text": "Second checkpoint", "memory": None}]
        Path(os.environ["FAKE_PAYLOAD"]).write_text(json.dumps(value))
        self.hook(session, "Stop", turn_id="turn-2")
        result = process_job(self.store, job["run_id"])
        self.assertEqual(result["capture"], "done", result)
        calls = [json.loads(line) for line in Path(os.environ["FAKE_CALLS"]).read_text().splitlines()]
        self.assertNotIn("fork", calls[-1]["args"])
        self.assertIn("Second delta", calls[-1]["prompt"])
        self.assertNotIn("User prompt 0", calls[-1]["prompt"])
        record = self.store.read_sessions(self.project)[session.id]
        self.assertGreater(record["source_version"][1], first_size)
        self.assertEqual(len(record["items"]), 2)
        self.assertEqual(len(record["item_snapshots"]), 2)
        self.assertIn("last_capture", record)

    def test_new_checkpoint_arriving_during_model_run_is_not_acknowledged_early(self):
        session = write_session(self)
        self.hook(session, "SessionStart")
        target = self.store.read_sessions(self.project)[session.id]["bound_memories"][0]
        value = empty_extraction(target)
        value["notes"] = [{"text": "First save", "memory": None}]
        Path(os.environ["FAKE_PAYLOAD"]).write_text(json.dumps(value))
        self.hook(session, "Stop", turn_id="turn-1")
        run = self.store.list_pending()[0]["run_id"]
        started, release = self.root / "started", self.root / "release"
        env = {**os.environ, "FAKE_STARTED": str(started), "FAKE_RELEASE": str(release)}
        worker = subprocess.Popen([sys.executable, "-m", "ellie", "_capture", run], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(started.exists(), "extractor never started")
            with session.path.open("a") as stream:
                stream.write(json.dumps({"timestamp": "2026-11-19T09:00:00Z", "type": "event_msg", "payload": {"type": "user_message", "message": "Later activity"}}) + "\n")
            value["notes"] = [{"text": "Second save", "memory": None}]
            Path(os.environ["FAKE_PAYLOAD"]).write_text(json.dumps(value))
            self.hook(session, "Stop", turn_id="turn-2")
            release.touch()
            out, err = worker.communicate(timeout=15)
            self.assertEqual(worker.returncode, 0, err)
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=10)
        self.assertEqual(len(self.store.read_sessions(self.project)[session.id]["items"]), 2)
        self.assertEqual(self.store.read_sessions(self.project)[session.id]["source_version"], session.version)
        self.assertEqual(self.store.list_pending(), [])

    def test_private_transcript_uses_filtered_fresh_extraction(self):
        from ellie.capture import process_job
        session = write_session(self)
        session.path.write_text(session.path.read_text().replace("User prompt 0", "Public <private>hidden-content</private>"))
        self.hook(session, "SessionStart")
        target = self.store.read_sessions(self.project)[session.id]["bound_memories"][0]
        Path(os.environ["FAKE_PAYLOAD"]).write_text(json.dumps(empty_extraction(target)))
        self.hook(session, "Stop")
        run = self.store.list_pending()[0]["run_id"]
        self.store.update_pending(run, lambda job: job.update({"incremental": False}))
        result = process_job(self.store, run)
        self.assertEqual(result["capture"], "done", result)
        calls = [json.loads(line) for line in Path(os.environ["FAKE_CALLS"]).read_text().splitlines()]
        self.assertNotIn("hidden-content", calls[-1]["prompt"])
        record = self.store.read_sessions(self.project)[session.id]
        self.assertNotIn("hidden-content", self.store.read_archive_text(self.project, record["archive"], 100000))
        self.assertIn("hidden-content", session.path.read_text())

    def test_large_session_is_processed_as_complete_record_batches(self):
        from ellie.capture import process_job
        import gzip
        session = write_session(self)
        with session.path.open("a") as stream:
            for text in ("first large record", "second large record"):
                stream.write(json.dumps({"timestamp": "2026-11-19T09:00:00Z", "type": "event_msg", "payload": {"type": "agent_message", "message": text + " x" * 280000}}) + "\n")
        source = session.path.read_bytes()
        self.hook(session, "SessionStart")
        target = self.store.read_sessions(self.project)[session.id]["bound_memories"][0]
        Path(os.environ["FAKE_PAYLOAD"]).write_text(json.dumps(empty_extraction(target)))
        self.hook(session, "Stop")
        run = self.store.list_pending()[0]["run_id"]
        first = process_job(self.store, run)
        self.assertTrue(first["more"])
        second = process_job(self.store, run)
        self.assertFalse(second["more"])
        record = self.store.read_sessions(self.project)[session.id]
        parts = record["archive_parts"]
        self.assertEqual(len(parts), 2)
        restored = b"".join(gzip.decompress(self.store.path("projects", self.project, "sessions", part["archive"]).read_bytes()) for part in parts)
        self.assertEqual(restored, source)
        self.assertEqual(parts[0]["end"], parts[1]["start"])

    def test_worker_keeps_failure_after_bounded_retries(self):
        from ellie.capture import drain_job
        from ellie.privacy import health
        session = write_session(self)
        self.hook(session, "SessionStart")
        self.hook(session, "Stop")
        run = self.store.list_pending()[0]["run_id"]
        with patch.dict(os.environ, {"FAKE_MODE": "error"}):
            result = drain_job(self.store, run)
        self.assertEqual(result["capture"], "failed")
        self.assertEqual(self.store.read_pending(run)["attempts"], 3)
        self.assertEqual(Path(os.environ["FAKE_COUNTER"]).read_text(), "3")
        self.assertEqual(health(self.store, self.project)["failed"], 1)
        from ellie.capture import plan_jobs
        jobs, errors = plan_jobs(self.store, self.project)
        self.assertEqual(errors, [])
        self.assertIn(run, [job["run_id"] for job in jobs])

    def test_unrelated_live_pid_does_not_block_recovery_dispatch(self):
        session = write_session(self)
        self.hook(session, "SessionStart")
        self.hook(session, "Stop", turn_id="first")
        run = self.store.list_pending()[0]["run_id"]
        self.store.update_pending(run, lambda job: job.update({"worker_pid": os.getpid()}))
        self.assertFalse(self.store.worker_active(run, os.getpid()))

    def test_pause_exclude_recursion_and_foreign_transcript_do_not_queue(self):
        from ellie.privacy import control
        session = write_session(self)
        control(self.store, self.project, "pause")
        self.assertEqual(self.hook(session, "SessionStart"), {})
        control(self.store, self.project, "resume")
        with patch.dict(os.environ, {"ELLIE_CAPTURE": "1"}):
            self.assertEqual(self.hook(session, "Stop"), {})
        control(self.store, self.project, "exclude", session.id)
        self.assertEqual(self.hook(session, "Stop"), {})
        self.assertEqual(self.store.list_pending(), [])
        control(self.store, self.project, "include", session.id)
        payload = {"session_id": session.id, "cwd": str(self.checkout), "transcript_path": str(self.checkout / "file.jsonl")}
        result = subprocess.run([sys.executable, "-m", "ellie", "hook", "codex", "Stop", "--no-worker"], input=json.dumps(payload), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.store.list_pending(), [])
