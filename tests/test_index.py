from datetime import date
import os
import subprocess
import sys
import time

from ellie.index import Index, recency, type_weight
from ellie.store import FileStore
from tests.support import IsolatedTest


class IndexTests(IsolatedTest):
    def index(self, **kwargs):
        index = Index(self.store, **kwargs)
        self.addCleanup(index.close)
        return index

    def seed(self):
        self.memory()
        old = self.store.add_item(self.project, "work", "N", "Refresh attempt", {"date": "2020-01-01"}, body="refresh attempt old note")
        new = self.store.add_item(self.project, "work", "R", "Refresh attempt", {"outcome": "failed", "what": "refresh attempt"})
        return old, new

    def test_recency_and_weights(self):
        self.assertEqual(recency("2026-01-01", date(2026, 1, 1)), 1)
        self.assertEqual(recency("2026-01-01", date(2026, 5, 1)), 0.5)
        self.assertEqual(recency("2000-01-01"), 0.25)
        self.assertEqual(type_weight("D", "superseded by D2", ""), 0.3)
        self.assertEqual(type_weight("Q", "resolved", ""), 0.5)

    def test_ranking_in_fts_and_like(self):
        old, new = self.seed()
        for force_like in (False, True):
            with Index(self.store, self.store.path(".local", "like.db" if force_like else "fts.db"), force_like=force_like) as index:
                hits = index.recall("refresh", project=self.project)
                self.assertEqual([hit.id for hit in hits], [new, old])
                self.assertGreater(hits[0].score, hits[1].score)
                self.assertNotIn("\n", hits[0].snippet)
                if force_like:
                    self.assertFalse(index.fts)

    def test_write_paths_keep_index_current_and_superseded_is_hidden(self):
        self.memory()
        index = self.index()
        fields = {"status": "active", "chosen": "refresh", "why": "refresh"}
        first = self.store.add_item(self.project, "work", "D", "Refresh old", fields)
        second = self.store.add_item(self.project, "work", "D", "Refresh new", fields, supersedes=[first])
        self.assertEqual([h.id for h in index.recall("refresh", project=self.project)], [second])
        self.assertEqual({h.id for h in index.recall("refresh", project=self.project, include_superseded=True)}, {first, second})

    def test_external_edit_archive_and_removal(self):
        self.seed()
        index = self.index()
        path = self.store.memory_path(self.project, "work")
        path.write_text(path.read_text().replace("Refresh", "Counter"))
        self.assertEqual(len(index.recall("counter", project=self.project)), 2)
        self.store.move_memory(self.project, "work", True)
        self.assertEqual(len(index.recall("counter", project=self.project)), 2)
        self.store.memory_path(self.project, "work").unlink()
        self.assertEqual(index.recall("counter", project=self.project), [])

    def test_filters_all_projects_and_reindex(self):
        self.seed()
        other = "gitlab.com/elsewhere/app"
        self.store.create_memory(other, "else")
        self.store.add_item(other, "else", "F", "Refresh finding", {"scope": "project", "detail": "refresh"})
        index = self.index()
        self.assertEqual(len(index.recall("refresh", project=self.project)), 2)
        self.assertEqual(len(index.recall("refresh", project=self.project, all_projects=True)), 3)
        self.assertEqual([h.type for h in index.recall("refresh", project=self.project, types=["R"])], ["R"])
        self.assertEqual(index.reindex(), 3)
        self.assertEqual(len(index.recall("refresh", all_projects=True)), 3)

    def test_untrusted_search_input(self):
        self.seed()
        for force_like in (False, True):
            with Index(self.store, self.store.path(".local", "query-" + str(force_like) + ".db"), force_like=force_like) as index:
                self.assertEqual(index.recall('" OR * % _ ; DROP TABLE items --', project=self.project), [])
                self.assertEqual(index.recall("", project=self.project), [])
                self.assertEqual(len(index.recall("refresh", project=self.project)), 2)
                with self.assertRaises(ValueError):
                    index.recall("refresh", limit=0)
                with self.assertRaises(ValueError):
                    index.recall("refresh", types=["invalid"])

    def test_like_unicode_and_index_lifecycle(self):
        self.memory()
        index = Index(self.store, force_like=True)
        self.store.add_item(self.project, "work", "N", "ÉLÉPHANT", {}, body="Memory")
        self.assertEqual(len(index.recall("éléphant", project=self.project)), 1)
        index.close()
        # A closed index must not leave a callback attached to the store.
        self.store.add_item(self.project, "work", "N", "New note", {}, body="After close")

    def test_simultaneous_initialization_of_fresh_cache(self):
        self.memory()
        barrier = self.root / "barrier"
        barrier.mkdir()
        script = """from pathlib import Path
import sys,time
from ellie.store import FileStore
from ellie.index import Index
barrier=Path(sys.argv[1]); (barrier/sys.argv[2]).touch()
while not (barrier/'go').exists(): time.sleep(.005)
with Index(FileStore()) as index: print(index.reindex())
"""
        workers = [subprocess.Popen([sys.executable, "-c", script, str(barrier), str(i)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(8)]
        try:
            deadline = time.monotonic() + 15
            while len(list(barrier.iterdir())) < 8 and time.monotonic() < deadline:
                time.sleep(.01)
            (barrier / "go").touch()
            results = [(worker, *worker.communicate(timeout=30)) for worker in workers]
            for worker, out, err in results:
                self.assertEqual(worker.returncode, 0, err)
        finally:
            for worker in workers:
                if worker.poll() is None:
                    worker.kill()
                worker.communicate()
