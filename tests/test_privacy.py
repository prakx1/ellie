import gzip
import json

from ellie.service import MemoryService
from ellie.privacy import read_chunk
from tests.support import IsolatedTest


class PrivacyTests(IsolatedTest):
    def test_checkpoint_compacts_binary_and_duplicate_fields_but_archives_original_bytes(self):
        command = "echo " + "x" * 600_000
        records = [
            {"type": "response_item", "payload": {"type": "custom_tool_call_output", "output": [
                {"image_url": "data:image/png;base64," + "A" * 1_100_000},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "C" * 1_100_000}},
                {"text": "Chart shows growth"}]}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {
                "command": ["/bin/sh", "-c", command], "parsed_cmd": [{"type": "unknown", "cmd": command}]}}},
            {"type": "compacted", "payload": {"replacement_history": [
                {"type": "reasoning", "encrypted_content": "B" * 1_100_000},
                {"type": "compaction", "encrypted_content": "D" * 1_100_000},
                {"tool_schema": {"type": ["string", "null"]}},
                {"type": "message", "content": [{"text": "Keep <private>secret</private> this finding"}]}],
                "replacement_history_metadata": [{"tokens": [123] * 500}] * 600}}
        ]
        source = self.root / "large.jsonl"
        lines = [(json.dumps(value) + "\n").encode() for value in records]
        original = b"".join(lines)
        source.write_bytes(original)
        first, end = read_chunk(source, max_bytes=700_000)
        self.assertLess(len(first.encode()), 700_000)
        self.assertEqual(end, len(original))
        projected = [json.loads(line) for line in first.splitlines()]
        self.assertEqual(projected[1]["payload"]["item"]["command"][-1], command)
        self.assertIn("Chart shows growth", first)
        self.assertIn("this finding", first)
        self.assertNotIn("secret", first)
        self.assertNotIn("A" * 1000, first)
        self.assertNotIn("B" * 1000, first)
        self.assertNotIn("C" * 1000, first)
        self.assertNotIn("D" * 1000, first)
        name = self.store.archive_transcript(self.project, source, "binary.jsonl.gz", filter_private=True)
        archived = gzip.decompress(self.store.path("projects", self.project, "sessions", name).read_bytes())
        self.assertIn(("A" * 1_100_000).encode(), archived)
        self.assertIn(("B" * 1_100_000).encode(), archived)
        self.assertEqual(len(json.loads(archived.splitlines()[-1])["payload"]["replacement_history_metadata"]), 600)
        self.assertNotIn(b"secret", archived)
        self.assertEqual(source.read_bytes(), original)

    def test_checkpoint_uses_raw_record_boundaries_and_retains_large_text_failure(self):
        source = self.root / "chunks.jsonl"
        line = (json.dumps({"text": "A useful observation"}) + "\n").encode()
        source.write_bytes(line * 2)
        text, end = read_chunk(source, max_bytes=len(line))
        self.assertEqual(text.encode(), line)
        self.assertEqual(end, len(line))
        with self.assertRaisesRegex(ValueError, "boundary"):
            read_chunk(source, 3)
        source.write_text(json.dumps({"text": "z" * 1_020_000}) + "\n")
        text, end = read_chunk(source)
        self.assertLessEqual(len(text.encode()), 1_048_576)
        self.assertEqual(end, source.stat().st_size)
        source.write_text(json.dumps({"text": "z" * 1_100_000}) + "\n")
        with self.assertRaisesRegex(ValueError, "record exceeds"):
            read_chunk(source)

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
