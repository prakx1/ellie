import gzip
import json

from ellie.service import MemoryService
from tests.support import IsolatedTest


class PrivacyTests(IsolatedTest):
    def test_pause_and_exclude_stop_agent_writes_and_are_reversible(self):
        self.memory()
        service = MemoryService(self.store)
        self.addCleanup(service.close)
        with service.in_session("chat-a"):
            service.bind(self.project, ["work"])
            service.privacy(self.project, "pause")
            with self.assertRaisesRegex(ValueError, "paused"):
                service.question(self.project, "work", "Do not save")
            service.privacy(self.project, "resume")
            service.privacy(self.project, "exclude", "chat-a")
            with self.assertRaisesRegex(ValueError, "excluded"):
                service.question(self.project, "work", "Do not save")
            service.privacy(self.project, "include", "chat-a")
            service.question(self.project, "work", "Save this")
        self.assertEqual(len(self.store.read_memory(self.project, "work").items), 1)

    def test_private_blocks_are_filtered_from_items_and_owned_archives(self):
        self.memory()
        text = "Keep this <private>hidden <private>nested</private> still hidden</private> and this"
        id = self.store.add_item(self.project, "work", "N", "Private fixture", {}, body=text, session="chat-a")
        raw = self.store.get_item(self.project, id)[1].raw
        self.assertIn("Keep this", raw)
        self.assertNotIn("hidden", raw)
        source = self.root / "session.jsonl"
        source.write_text(json.dumps({"message": text}) + "\n")
        original = source.read_bytes()
        name = self.store.archive_transcript(self.project, source, "fixture.jsonl.gz", filter_private=True)
        with gzip.open(self.store.path("projects", self.project, "sessions", name), "rt") as stream:
            archived = json.load(stream)
        self.assertNotIn("hidden", archived["message"])
        self.assertEqual(source.read_bytes(), original)
        self.assertNotIn("hidden", json.dumps(self.store.read_sessions(self.project)))
