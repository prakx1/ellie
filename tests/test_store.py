from concurrent.futures import ThreadPoolExecutor
import gzip
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

from ellie.model import Memory
from ellie.store import ConcurrentUpdateError, FileLock, FileStore, Store, atomic_write
from tests.support import IsolatedTest


DECISION = {"status": "active", "chosen": "files", "why": "readable"}


class StoreTests(IsolatedTest):
    def test_protocol_and_no_read_side_effects(self):
        empty = FileStore(self.root / "absent")
        self.assertIsInstance(empty, Store)
        self.assertEqual(empty.list_projects(), [])
        self.assertEqual(empty.read_local("state"), {})
        self.assertFalse(empty.root.exists())

    def test_creation_archive_restore_and_project_ids(self):
        self.memory()
        self.assertEqual(self.store.list_projects(), [self.project])
        self.assertEqual(self.store.read_memory(self.project, "project").name, "project")
        self.assertEqual([m.name for m in self.store.list_memories(self.project)], ["work"])
        self.store.move_memory(self.project, "work", True)
        self.assertEqual(self.store.list_memories(self.project), [])
        self.assertTrue(self.store.list_memories(self.project, True)[0].archived)
        self.assertEqual(self.store.read_memory(self.project, "work").meta["status"], "archived")
        self.store.move_memory(self.project, "work", False)
        self.assertEqual(self.store.read_memory(self.project, "work").meta["status"], "active")
        with self.assertRaises(ValueError):
            self.store.move_memory(self.project, "project", True)
        with self.assertRaises(FileExistsError):
            self.memory()

    def test_ids_across_memories_archives_and_deleted_items(self):
        self.memory("one")
        self.memory("two")
        self.assertEqual(self.store.add_item(self.project, "one", "D", "First", DECISION), "D1")
        self.store.move_memory(self.project, "one", True)
        self.assertEqual(self.store.add_item(self.project, "two", "D", "Second", DECISION), "D2")
        self.store.update_memory(self.project, "two", lambda m: m.set_section("Decisions", ""))
        self.assertEqual(self.store.add_item(self.project, "two", "D", "Third", DECISION), "D3")
        self.assertEqual(self.store.add_item(self.project, "two", "Q", "Why?", {"status": "open"}), "Q1")

    def test_supersede_and_resolve_across_memories(self):
        self.memory("one")
        self.memory("two")
        old = self.store.add_item(self.project, "one", "D", "Old", DECISION)
        new = self.store.add_item(self.project, "two", "D", "New", DECISION, supersedes=[old])
        self.assertEqual(self.store.get_item(self.project, old)[1].fields["status"], "superseded by " + new)
        self.assertEqual(self.store.get_item(self.project, new)[1].fields["supersedes"], old)
        q = self.store.add_item(self.project, "one", "Q", "Unknown?", {"status": "open"})
        self.store.resolve(self.project, q, "Now known")
        self.assertEqual(self.store.get_item(self.project, q)[1].fields["answer"], "Now known")
        self.assertEqual(self.store.get_item(self.project, q)[1].fields["status"], "resolved")
        with self.assertRaises(ValueError):
            self.store.resolve(self.project, old, "No")

    def test_bad_supersedes_does_not_add_an_item(self):
        self.memory()
        with self.assertRaises(KeyError):
            self.store.add_item(self.project, "work", "D", "No", DECISION, supersedes=["D99"])
        self.assertEqual(self.store.read_memory(self.project, "work").items, [])

    def test_project_scope_finding_and_secret_redaction(self):
        self.memory()
        secret = "sk-" + "x" * 32
        id = self.store.add_item(self.project, "work", "F", "A finding", {"scope": "project", "detail": secret})
        name, item = self.store.get_item(self.project, id)
        self.assertEqual(name, "project")
        self.assertEqual(item.fields["detail"], "[redacted]")

    def test_retry_dedupe_and_old_item(self):
        self.memory()
        first = self.store.add_item(self.project, "work", "D", "Use: Files!", DECISION)
        self.assertEqual(self.store.add_item(self.project, "work", "D", "use files", DECISION), first)
        self.store.update_memory(self.project, "work", lambda m: m.set_section("Log", ""))
        self.assertNotEqual(self.store.add_item(self.project, "work", "D", "use files", DECISION), first)

    def test_stale_memory_save_is_rejected(self):
        self.memory()
        old = self.store.read_memory(self.project, "work")
        self.store.update_memory(self.project, "work", lambda m: m.set_section("Goal", "new"))
        old.set_section("Goal", "stale")
        with self.assertRaises(ConcurrentUpdateError):
            self.store.write_memory(self.project, old)
        self.assertIn("new", self.store.read_memory(self.project, "work").get_section("Goal"))

    def test_atomic_failure_preserves_file_and_cleans_temp_and_lock(self):
        path = self.root / "atomic.txt"
        atomic_write(path, b"original")
        with patch("ellie.store.os.replace", side_effect=OSError("injected failure")):
            with self.assertRaises(OSError):
                atomic_write(path, b"replacement")
        self.assertEqual(path.read_bytes(), b"original")
        self.assertEqual(list(path.parent.glob(".atomic.txt.*")), [])
        self.assertFalse(Path(str(path) + ".lock").exists())

    def test_lock_timeout_stale_recovery_and_replacement_ownership(self):
        path = self.root / "locked"
        with FileLock(path):
            with self.assertRaises(TimeoutError):
                with FileLock(path, timeout=0.02):
                    pass
        lock = Path(str(path) + ".lock")
        lock.write_text("old")
        os.utime(lock, (time.time() - 70, time.time() - 70))
        with FileLock(path):
            self.assertTrue(lock.exists())
        self.assertFalse(lock.exists())
        with FileLock(path):
            replacement = self.root / "replacement"
            replacement.write_text("other owner")
            os.replace(replacement, lock)
        self.assertEqual(lock.read_text(), "other owner")

    def test_concurrent_processes_allocate_unique_ids(self):
        self.memory("one")
        self.memory("two")
        script = "from ellie.store import FileStore; import sys; s=FileStore(); print(s.add_item(sys.argv[1],sys.argv[2],'D',sys.argv[3],{'status':'active','chosen':'files','why':'readable'}))"
        processes = [subprocess.Popen([sys.executable, "-c", script, self.project, ("one" if i % 2 else "two"), "Decision " + str(i)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(8)]
        ids = []
        for process in processes:
            out, err = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, err)
            ids.append(out.strip())
        self.assertEqual(set(ids), {"D" + str(i) for i in range(1, 9)})
        self.assertEqual(sum(len(m.items) for m in self.store.iter_memories(self.project)), 8)

    def test_locked_json_updates_do_not_lose_events(self):
        def append(i):
            self.store.update_sessions(self.project, lambda d: d.update({str(i): {"capture": "done"}}))
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(append, range(20)))
        self.assertEqual(len(self.store.read_sessions(self.project)), 20)

    def test_raw_transcript_archived_exactly_without_touching_source(self):
        source = self.root / "transcript.jsonl"
        raw = b'{"event":"first"}\r\n{"event":"last"}\n'
        source.write_bytes(raw)
        name = "2026-11-17_codex_fixture.jsonl.gz"
        self.assertEqual(self.store.archive_transcript(self.project, source, name), name)
        self.assertEqual(gzip.decompress(self.store.path("projects", self.project, "sessions", name).read_bytes()), raw)
        self.assertEqual(source.read_bytes(), raw)

    def test_paths_cannot_escape_or_write_inside_a_repository(self):
        for name in ("../escape", "/tmp/escape", ".."):
            with self.assertRaises(ValueError):
                self.store.read_memory(self.project, name)
        repo = self.root / "repo"
        repo.mkdir()
        self.git(repo, "init")
        with self.assertRaisesRegex(ValueError, "outside a git repository"):
            FileStore(repo / "memory")
        outside = self.root / "outside"
        outside.mkdir()
        (self.store.root / "projects").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.memory()
        self.assertEqual(list(outside.iterdir()), [])
