from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from ellie.backfill import backfill
from ellie.doctor import diagnose, run
from ellie.install import install
from ellie.service import MemoryService
from tests.fake_agents import empty_extraction, install_fakes, write_session
from tests.support import IsolatedTest


class HistoricalTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.git(self.checkout, "init")
        self.git(self.checkout, "remote", "add", "origin", "https://" + self.project + ".git")
        self.memory()
        install_fakes(self)
        payload = empty_extraction()
        payload["notes"] = [{"text": "Historical finding", "memory": None}]
        Path(os.environ["FAKE_PAYLOAD"]).write_text(json.dumps(payload))

    def service(self):
        service = MemoryService(self.store)
        self.addCleanup(service.close)
        return service

    def test_backfill_confirmation_oldest_first_and_source(self):
        old = write_session(self, start=datetime.now(timezone.utc) - timedelta(days=2))
        new = write_session(self, start=datetime.now(timezone.utc) - timedelta(days=1))
        service = self.service()
        output = io.StringIO()
        self.assertEqual(backfill(service, self.project, input_fn=lambda _: "n", output=output), 0)
        self.assertIn("2 extraction runs", output.getvalue())
        self.assertLess(output.getvalue().index(old.id), output.getvalue().index(new.id))
        self.assertEqual(self.store.list_pending(), [])
        self.assertFalse(Path(os.environ["FAKE_CALLS"]).exists())
        self.assertEqual(backfill(service, self.project, input_fn=lambda _: "yes", output=io.StringIO()), 0)
        calls = [json.loads(line) for line in Path(os.environ["FAKE_CALLS"]).read_text().splitlines()]
        self.assertEqual([call["args"][-2] for call in calls], [old.id, new.id])
        self.assertEqual(self.store.get_item(self.project, "N1")[1].fields["source"], "codex · backfill · session " + old.id)
        self.assertEqual(backfill(service, self.project, yes=True, output=io.StringIO()), 0)
        self.assertEqual(len(Path(os.environ["FAKE_CALLS"]).read_text().splitlines()), 2)

    def test_backfill_cli_limit_and_agent_filter(self):
        write_session(self, start=datetime.now(timezone.utc) - timedelta(days=3))
        claude = write_session(self, "claude", start=datetime.now(timezone.utc) - timedelta(days=2))
        result = subprocess.run([sys.executable, "-m", "ellie", "backfill", "--since", "1w", "--limit", "1", "--agent", "claude", "--yes"], cwd=self.checkout, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(claude.id, result.stdout)
        self.assertEqual(self.store.read_sessions(self.project)[claude.id]["agent"], "claude")

    def test_agent_filtered_backfill_leaves_other_agents_pending_jobs_alone(self):
        write_session(self, "codex")
        other = write_session(self, "claude")
        pending = {"run_id": "other-agent-retry", "project": self.project, "agent": "claude",
                   "session_id": other.id, "cwd": other.cwd, "started": other.started.isoformat(),
                   "ended": other.ended.isoformat(), "memories": ["work"], "capture": "failed"}
        self.store.write_pending(pending["run_id"], pending)
        output = io.StringIO()
        self.assertEqual(backfill(self.service(), self.project, agent="codex", yes=True, output=output), 0,
                         output.getvalue())
        self.assertNotIn(other.id, output.getvalue())
        self.assertEqual(self.store.read_pending(pending["run_id"]), pending)
        calls = [json.loads(line) for line in Path(os.environ["FAKE_CALLS"]).read_text().splitlines()]
        self.assertEqual([call["agent"] for call in calls], ["codex"])

    def test_doctor_success_with_fake_login_and_real_local_config(self):
        with patch("ellie.install.run_cli", return_value=False):
            install(codex=True, claude=True, store=self.store)
        write_session(self)
        output = io.StringIO()
        self.assertEqual(run(self.store, output), 0, output.getvalue())
        self.assertIn("PASS codex login", output.getvalue())
        self.assertIn("PASS claude MCP", output.getvalue())
        self.assertFalse(Path(os.environ["FAKE_CALLS"]).exists())

    def test_doctor_reports_malformed_sources_pending_and_corrupt_index(self):
        with patch("ellie.install.run_cli", return_value=False):
            install(codex=True, claude=True, store=self.store)
        session = write_session(self)
        (session.path.parent / "rollout-bad.jsonl").write_text("{bad")
        pending = self.store.path(".local", "pending", "broken.json")
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text("{bad")
        index = self.store.path(".local", "index.db")
        index.write_bytes(b"not a database")
        checks = diagnose(self.store)
        failed = {check.name for check in checks if check.ok is False}
        self.assertTrue({"codex sessions", "pending record", "search index"}.issubset(failed))
        result = subprocess.run([sys.executable, "-m", "ellie", "doctor"], cwd=self.checkout, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Run ellie reindex", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_doctor_reports_write_permissions(self):
        with patch.object(self.store, "probe_writable", side_effect=PermissionError):
            checks = diagnose(self.store)
        self.assertFalse(next(check for check in checks if check.name == "store write").ok)
