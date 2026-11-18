# Ellie v1 acceptance review

Date: 2026-11-18. All eight implementation/review milestones are complete.
The supplied `spec.md` remains unchanged.

**These are automated implementation verdicts, not a claim of completed live
subscription testing.** Model-dependent tests use real subprocesses running
fake codex/claude scripts with canned JSON, as required by §18. They verify
Ellie's inputs, outputs, persistence, safety flags, and orchestration; they do
not verify a live model's judgment or recap. No authenticated model call,
real-home installation, or PyPI publication was performed.

## Spec §19, one criterion at a time

| # | Criterion | Automated result | Evidence and remaining live work |
| --- | --- | --- | --- |
| 1 | Public `uv tool install ellie`, install integration, first start under two minutes | **FAIL: public release pending** | A fresh local wheel/tool install, actual Codex MCP registration, new memory, and dry-run startup took **5.97 seconds** in isolated homes. The installed MCP command answered initialization and listed all 14 tools with PYTHONPATH unset. Public PyPI availability and a live first agent turn were not tested. |
| 2 | Exit Codex without handoff; capture decision and failed result with evidence | **PASS (canned CLI)** | `test_automatic_launcher_capture_and_cross_agent_startup` exercises launcher exit → detached worker → pending discovery → fork extraction → memory/registry/archive → status summary. Merge tests assert options, tradeoff, why, evidence, source session ID, and failed-result wording. Real model extraction/nonpersistence remains unverified. |
| 3 | Claude starts with the previous Codex state and next steps | **PASS (briefing input)** | The cross-agent startup test asserts that Claude receives the Codex-derived current state and next steps. A live Claude-generated recap was not observed. |
| 4 | `--about "token refresh"` selects the failed iframe result and authlib decision | **PASS** | `test_about_with_cross_project_and_prompt_budget` asserts both D1 and R1 are preselected for token refresh, and the prompt contains the authlib decision and Safari evidence. Checklist toggles/search/show/whole-memory rows and a real pseudo-TTY picker are also tested. |
| 5 | Plain Codex sessions appear as uncaptured and can be captured | **PASS (canned CLI)** | External discovery/planning and `capture --dry-run`/`--wait` tests create agent-owned session fixtures without a launcher, capture them, and assert `launched_by: external`. Resumed source changes become uncaptured again. Live native extraction remains unverified. |
| 6 | Backfill past sessions after confirmation | **PASS (canned CLI)** | Tests decline confirmation without creating jobs or invoking extraction, then confirm and assert oldest-first CLI calls and `source: ... · backfill`. CLI tests cover time windows, limit, agent filtering, and --yes. |
| 7 | Import a handoff and keep workstreams separate | **PASS** | CLI tests import Markdown containing section headings, preserve source bytes, keep its text under Current state, and verify that another memory remains separate. Archive/restore retain IDs. |
| 8 | No API keys; models invoked only through user CLIs | **PASS (code/fixture audit)** | Runtime import audit finds only the standard library. Model execution is confined to codex exec/claude -p subprocesses. Extraction removes known API-key/auth-token environment variables; fake CLIs verify none are forwarded. No credentials are read or copied by Ellie. |
| 9 | Uninstall keeps other config and memory files | **PASS** | Install/uninstall tests run twice with temporary homes and assert unchanged other MCP tables, arrays, comments, multiline strings, user instructions, Claude permissions, and memory bytes. A real Codex CLI also parses the fallback TOML. |

Public-release acceptance is therefore not closed. Automated behavior for
criteria 2–9 passes within the scopes above; live model-dependent clauses
remain to be exercised with a deliberately authenticated isolated profile.

## Final validation

- **93 unittest tests pass** on Python **3.10.20**, **3.14.3**, and **3.15.2**.
  The final token-refresh decision/result assertion was additionally rerun on
  all three interpreters. Python 3.15.2 was checked against the
  [official release listing](https://www.python.org/downloads/).
- Installed-wheel smoke test uses a fresh temporary HOME, CODEX_HOME,
  ELLIE_HOME, CLAUDE_CONFIG_DIR, and uv tool directory. PYTHONPATH is unset.
- Package metadata reports **zero runtime dependencies**. Both extraction
  resources are present; the strict schema has 11 required top-level properties.
- Installed MCP registration preserves the virtual-environment interpreter
  path. Its subprocess successfully handles initialize and tools/list.
- Concurrency coverage includes eight simultaneous item writers, eight
  synchronized cache initializers, and competing capture workers.
- Failure coverage includes invalid-then-valid output, invalid twice, timeout,
  missing output, unsupported safety flags, missing parent history, interrupted
  merge retries, malformed session/pending files, failed atomic replacements,
  stale locks, and corrupt-index rebuilding without memory changes.
- Common-secret redaction, UTF-8/byte round-trips, unknown Markdown preservation,
  supersede/resolve, FTS5/LIKE ranking, archives, editor reindexing, passthrough,
  BrokenPipe, selection budgets, and cross-project references are covered.
- No real `~/.ellie` store or agent configuration was modified. Real session
  inspection was limited to the explicitly requested read-only Step 0 check.

## Remaining live integration checks from §21

1. Authenticated native forks produce valid structured output with these exact
   CLI versions and safety settings.
2. Forked/ephemeral extraction creates no resume-history entries and does not
   append to source sessions in a real authenticated run.
3. Actual provider-side strict-schema enforcement and corrective retry work.
4. Installed MCP approval behavior matches the intended Codex/Claude settings.
5. A human verifies the live Claude recap and relevance of captured content.

Use an independently authenticated temporary profile for these checks; do not
copy the user's real login files. The verified CLI versions are Codex 0.169.0
and Claude Code 2.1.278. No unsafe fallback is used when required flags are missing.

## Review findings fixed before the final commit

- Preserved sys.executable's absolute virtual-environment path instead of
  resolving its symlink to a base interpreter that cannot import Ellie.
- Serialized fresh SQLite schema initialization to prevent concurrent workers
  both creating the items table; failed initialization closes its connection.
- Made reindex recover a corrupt cache before normal service startup, retaining
  the damaged cache for diagnosis and leaving Markdown unchanged.
- Counted Claude image-only human inputs while excluding tool-result/meta records.

If a running agent retains an already-corrupt index connection, restart it after
reindex recovery. This concerns only the rebuildable cache; Markdown and the
session registry remain authoritative.
