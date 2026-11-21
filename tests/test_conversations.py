from ellie.service import MemoryService
from tests.support import IsolatedTest


class ConversationTests(IsolatedTest):
    def test_saved_summary_labels_legacy_conversations_instead_of_the_opening_message(self):
        self.memory()
        opener = "Can you make the sample repository public?"
        summary = "Publish the sample app and configure the GitHub repository."
        self.store.update_sessions(self.project, lambda data: data.update({"chat-a": {"title": opener}}))
        service = MemoryService(self.store)
        self.addCleanup(service.close)
        self.assertEqual(service.conversations(self.project)["conversations"][0]["title"], opener)
        with service.in_session("chat-a"):
            service.handoff(self.project, "work", "Repository published", "Build the dashboard", summary)
        before = self.store.read_sessions(self.project)
        row = service.conversations(self.project)["conversations"][0]
        self.assertEqual(row["title"], summary)
        self.assertEqual(row["id"], "chat-a")
        self.assertEqual(self.store.read_sessions(self.project), before)

    def test_historical_versions_do_not_leak_later_answers_or_status(self):
        self.memory()
        id = self.store.add_item(self.project, "work", "Q", "Which provider?", {"status": "open"}, session="chat-a")
        self.store.resolve(self.project, id, "Beta-only answer", session="chat-b")
        self.store.add_item(self.project, "work", "Q", "Which provider?", {"status": "open"}, session="chat-a", dedupe=True)
        service = MemoryService(self.store)
        self.addCleanup(service.close)
        earlier = service.get(self.project, [id], conversations=["chat-a"])["items"][0]
        self.assertEqual(earlier["fields"]["status"], "open")
        self.assertNotIn("Beta-only answer", earlier["text"])
        later = service.get(self.project, [id], conversations=["chat-b"])["items"][0]
        self.assertEqual(later["fields"]["answer"], "Beta-only answer")
        self.assertEqual(service.recall(self.project, "Beta-only", conversations=["chat-a"])["items"], [])

    def test_deduplication_keeps_both_conversation_sources(self):
        from ellie.conversations import list_conversations
        self.memory()
        first = self.store.add_item(self.project, "work", "N", "Shared observation", {}, session="chat-a")
        second = self.store.add_item(self.project, "work", "N", "Shared observation", {}, session="chat-b", dedupe=True)
        self.assertEqual(first, second)
        records = {record["id"]: record for record in list_conversations(self.store, self.project)}
        self.assertEqual(records["chat-a"]["items"], [first])
        self.assertEqual(records["chat-b"]["items"], [first])

    def test_session_bindings_keep_parallel_work_and_retrieval_separate(self):
        self.memory("auth")
        self.memory("billing")
        service = MemoryService(self.store)
        self.addCleanup(service.close)
        with service.in_session("chat-a"):
            service.bind(self.project, ["auth"], conversations=[])
            a = service.question(self.project, "auth", "Alpha question")["id"]
            service.handoff(self.project, "auth", "Alpha state", "Alpha next", "Alpha summary")
        with service.in_session("chat-b"):
            service.bind(self.project, ["billing"], conversations=[])
            b = service.question(self.project, "billing", "Beta question")["id"]
            with self.assertRaises(ValueError):
                service.question(self.project, "auth", "Wrong destination")
            self.assertEqual([hit["id"] for hit in service.recall(self.project, "question")["items"]], [b])
        with service.in_session("chat-a"):
            self.assertEqual([hit["id"] for hit in service.recall(self.project, "question")["items"]], [a])
            self.assertNotIn("Beta", service.load(self.project, ["auth"])["briefing"])
            self.assertIn("Alpha state", service.load(self.project, ["auth"])["briefing"])

    def test_selected_conversation_excludes_other_items_and_global_state(self):
        self.memory()
        a = self.store.add_item(self.project, "work", "N", "Alpha design", {}, session="chat-a", body="Alpha context")
        b = self.store.add_item(self.project, "work", "N", "Beta design", {}, session="chat-b", body="Beta secret context")
        self.store.add_item(self.project, "project", "N", "Unattributed note", {}, body="Unknown source")
        self.store.update_memory(self.project, "work", lambda m: m.set_section("Current state", "Beta private state"))
        service = MemoryService(self.store)
        self.addCleanup(service.close)
        context = service.load(self.project, ["work"], conversations=["chat-a"])["briefing"]
        self.assertIn("Alpha context", context)
        for excluded in ("Beta secret context", "Beta private state", "Unknown source"):
            self.assertNotIn(excluded, context)
        self.assertEqual([hit["id"] for hit in service.recall(self.project, "design", conversations=["chat-a"])["items"]], [a])
        with self.assertRaises(ValueError):
            service.get(self.project, [b], conversations=["chat-a"])
