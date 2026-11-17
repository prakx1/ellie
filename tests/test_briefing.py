from ellie.briefing import render_memory
from ellie.model import Item, Memory
from tests.support import IsolatedTest


class RenderingTests(IsolatedTest):
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
