import unittest

from ellie.model import Item, Memory, normalized_title


SAMPLE = """---
name: work
description: Example 🐘
custom:  Keep This<TWO>
---

## Goal
Build memory.

## Decisions

  ### D7  -  Keep handwritten formatting<THREE>
  - date : 2026-11-17
- status: active
- source: codex · live
- chosen: files
- why: readable
  - unknown:  untouched<TWO>
Free-form **Markdown**, including: punctuation.

## Notes
### N2: Unicode 🐘
- date: 2026-11-17
- source: you · manual
Some free text.

```markdown
## Not a section
### D99 · Not an item
```

## Log
- 2026-11-17 14:01 · you · note: unchanged
""".replace("<TWO>", "  ").replace("<THREE>", "   ")


class ModelTests(unittest.TestCase):
    def test_byte_exact_roundtrips(self):
        for text in (SAMPLE, SAMPLE.rstrip(), SAMPLE.replace("\n", "\r\n"), "", "No frontmatter\n", "\ufeff" + SAMPLE):
            with self.subTest(text=text[:20]):
                self.assertEqual(Memory.parse(text.encode()).to_bytes(), text.encode())

    def test_fields_and_unknown_text_survive_mutation(self):
        memory = Memory.parse(SAMPLE)
        self.assertEqual([item.id for item in memory.items], ["D7", "N2"])
        item = memory.get_item("D7")
        self.assertEqual(item.fields["unknown"], "untouched")
        item.set_field("status", "superseded by D8")
        memory.replace_item(item)
        self.assertEqual(memory.render(), SAMPLE.replace("- status: active", "- status: superseded by D8"))

    def test_frontmatter_last_wins_and_normalizes_only_on_save(self):
        text = SAMPLE.replace("name: work", "name: old\nname: work")
        memory = Memory.parse(text)
        self.assertEqual(memory.name, "work")
        self.assertEqual(memory.render(), text)
        self.assertEqual(memory.normalized_for_save(), SAMPLE.encode())

    def test_all_item_separators(self):
        for sep in (" · ", " - ", ": ", "  ·   "):
            item = Item("### F14" + sep + "a title\n- detail: words\n")
            self.assertEqual((item.id, item.title), ("F14", "a title"))

    def test_setting_section_preserves_other_text(self):
        memory = Memory.parse(SAMPLE)
        memory.set_section("Goal", "New goal")
        self.assertEqual(memory.render(), SAMPLE.replace("Build memory.", "New goal"))

    def test_explicit_summary_replacement_repairs_legacy_duplicate_sections(self):
        raw = Memory.new("work").render().replace("## Current state\n", "## Current state\nOlder state\n\n## Current state\nStale state\n")
        memory = Memory.parse(raw)
        self.assertEqual(memory.render(), raw)
        memory.set_section("Current state", "Latest state")
        self.assertEqual(memory.get_section("Current state").strip(), "Latest state")
        self.assertEqual(memory.render().count("## Current state\n"), 1)
        self.assertIn("## Next steps\n", memory.render())

    def test_unclosed_summary_fence_cannot_hide_other_sections(self):
        memory = Memory.new("work")
        memory.set_section("Current state", "```markdown\n## Example\nUnfinished block")
        memory.set_section("Next steps", "Continue testing")
        self.assertIn("Unfinished block", memory.get_section("Current state"))
        self.assertEqual(memory.get_section("Next steps").strip(), "Continue testing")
        self.assertIn("Decisions", memory.sections)

    def test_new_project_and_workstream_sections(self):
        project = Memory.new("project")
        self.assertNotIn("Goal", project.sections)
        self.assertNotIn("Results", project.sections)
        self.assertEqual(list(project.sections), ["Overview", "Conventions", "Decisions", "Findings", "Open questions", "Notes", "Log"])
        work = Memory.new("work", goal="Ship", done_when="Tests pass")
        self.assertIn("**Done when:** Tests pass", work.get_section("Goal"))

    def test_programmatic_items_validate_but_parser_tolerates_missing_fields(self):
        with self.assertRaisesRegex(ValueError, "missing item fields"):
            Item.create("D1", "Missing", {})
        self.assertEqual(Item("### D1 · Missing\n").id, "D1")
        with self.assertRaises(ValueError):
            Item.create("R1", "Failure", {"date": "2026-11-17", "source": "you · manual", "what": "try", "outcome": "unknown"})
        with self.assertRaises(ValueError):
            Item.create("N1", "bad\nheading", {"date": "today", "source": "you · manual"})

    def test_title_normalization(self):
        self.assertEqual(normalized_title("Use:  REDIS!"), normalized_title("use redis"))
        self.assertEqual(normalized_title("‘Use Redis’"), "use redis")
