import io

from ellie.briefing import pick_conversations, pick_memories, render_memory, select_history
from ellie.model import Item, Memory
from ellie.service import MemoryService
from tests.support import IsolatedTest


class RenderingTests(IsolatedTest):
    def test_conversation_picker_explains_saved_contents_before_selection(self):
        self.memory()
        self.store.add_item(self.project, "work", "N", "Configure deployment", {}, session="chat-a")
        service = MemoryService(self.store)
        self.addCleanup(service.close)
        with service.in_session("chat-a"):
            service.handoff(self.project, "work", "Deploy is ready", "Publish the homepage", "Work completed")
        output = io.StringIO()
        self.assertEqual(pick_conversations(service, self.project, input_fn=lambda _: "1", output=output), ["chat-a"])
        self.assertIn("Covers: Configure deployment", output.getvalue())
        self.assertIn("Next: Publish the homepage", output.getvalue())

    def test_filtered_items_log_limit_and_order(self):
        memory = Memory.new("auth", goal="Ship", done_when="Tests pass")
        memory.set_section("Current state", "In progress")
        memory.set_section("Next steps", "Migrate")
        for id, status in (("D1", "active"), ("D2", "reverted"), ("D3", "superseded by D1")):
            memory.add_item(Item.create(id, id, {"date": "2026-01-01", "source": "codex · live", "status": status, "chosen": "yes", "why": "reason"}))
        for i in range(1, 13):
            memory.add_item(Item.create("R" + str(i), "Attempt " + str(i), {"date": "2026-01-01", "source": "codex · live", "outcome": "failed", "what": "Try"}))
        for i in range(3):
            memory.append_log("codex", "progress", "Step " + str(i))
        text = render_memory(memory, 2)
        self.assertIn("### D1", text)
        self.assertNotIn("### D2", text)
        self.assertNotIn("### D3", text)
        self.assertNotIn("### R1 ·", text)
        self.assertNotIn("### R2 ·", text)
        self.assertIn("### R12", text)
        self.assertNotIn("Step 0", text)
        self.assertLess(text.index("## Goal"), text.index("## Current state"))
        self.assertLess(text.index("## Next steps"), text.index("## Decisions"))

    def test_project_overview_and_placeholders(self):
        memory = Memory.new("project")
        memory.set_section("Overview", "An agent memory tool")
        memory.set_section("Conventions", "TBD")
        text = render_memory(memory)
        self.assertIn("An agent memory tool", text)
        self.assertNotIn("## Conventions", text)

    def test_history_toggle_show_search_and_whole_memory(self):
        self.memory()
        self.store.add_item(self.project, "work", "N", "Refresh", {}, body="Refresh")
        self.store.add_item(self.project, "work", "N", "Counters", {}, body="Counters")
        service = MemoryService(self.store)
        self.addCleanup(service.close)
        answers = iter(["s 1", "a counters", "2 3", ""])
        output = io.StringIO()
        chosen = select_history(service, self.project, "refresh", interactive=True, input_fn=lambda _: next(answers), output=output)
        self.assertEqual(chosen.ids, ["N1", "N2"])
        self.assertEqual(chosen.memories, ["work"])
        self.assertIn("### N1", output.getvalue())
        self.assertEqual(select_history(service, self.project, "refresh", interactive=True, input_fn=lambda _: "q", output=output).ids, [])

    def test_preselection_budget_and_new_picker(self):
        self.memory()
        self.store.add_item(self.project, "work", "N", "Large", {}, body="Large " * 2000)
        service = MemoryService(self.store)
        self.addCleanup(service.close)
        self.assertEqual(select_history(service, self.project, "large", interactive=False).ids, [])
        answers = iter(["n", "draft", "Description", "Build", "Green"])
        selection = pick_memories(service, self.project, input_fn=lambda _: next(answers), output=io.StringIO(), dry_run=True)
        self.assertEqual(selection.memories, ["draft"])
        self.assertIn("Green", selection.drafts["draft"].get_section("Goal"))
        self.assertNotIn("draft", [meta.name for meta in self.store.list_memories(self.project)])
