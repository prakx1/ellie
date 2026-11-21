# Ellie 0.3.5 verification

Date: 2026-11-22. This report covers the current implementation, including the
conversation picker, content previews, dashboard and automatic checkpoints.
It supplements the historical v1 review in [ACCEPTANCE.md](ACCEPTANCE.md).

## Result and scope

All exercised checks pass after fixing four reproducible bugs. This is not a
claim that every possible input or live provider behavior is bug-free.

Every development test uses temporary HOME, CODEX_HOME, ELLIE_HOME,
CLAUDE_CONFIG_DIR and XDG directories. No real agent configuration, session
files or private memory was used, changed or copied into fixtures. No API keys
or authenticated external model calls were used. Fixtures contain invented
project data. The normal installed executable was updated separately.

## Test runs

| Runtime / installation | Result | Time |
| --- | --- | --- |
| Python 3.10.20, source | 141 passed | 176.1 seconds |
| Python 3.15.0a7 preview, source | 141 passed | 185.0 seconds |
| Python 3.10.20, clean installed wheel | 141 passed | 174.4 seconds |
| Python 3.14.3, installed user executable with temporary profiles | 141 passed | 86.3 seconds |

The wheel suite runs with PYTHONPATH unset and the installed interpreter;
source layout cannot accidentally supply missing package modules/resources.
These runs were performed on macOS arm64; Linux and Windows were not executed.
The build has 31 runtime files, zero runtime dependencies and the unchanged
strict extraction schema. JavaScript syntax and Git whitespace checks pass.
Native versions: Codex CLI 0.171.0 and Claude Code 2.1.278. Final strengthened
native-session parsing and MCP privacy assertions were additionally rerun.

## Feature coverage

| Area | Result | Evidence |
| --- | --- | --- |
| Projects and paths | PASS | Remote normalization, folder aliases, subfolders, clones, worktrees and rejection of unsafe paths/store roots. |
| Markdown and items | PASS | Byte-exact parsing, Unicode/CRLF, unknown fields, IDs, concurrent writes, superseding, resolving, locks and atomic failure recovery. New checks cover nested headings, duplicate state and incomplete fences. |
| Search | PASS | FTS5, LIKE fallback, ranking, superseded filters, external edits, corrupt-cache recovery and reindexing. |
| CLI | PASS | Status/new/show/edit/log/archive/restore/import/recall/brief/projects/link/config/where/reindex, launch picker, history checklist, passthrough, cancellation and BrokenPipe. |
| MCP | PASS | Real stdio subprocesses, initialization, 18 tools, invalid requests, retry deduplication and interleaved conversation bindings. |
| Conversation history | PASS | Provenance, historical item versions, selected-source exclusion, no-history, timeline, previews, per-chat goals/state and fresh reads after parallel saves. |
| Hooks and checkpoint workers | PASS | Both agent entrypoints, durable/coalesced jobs, incremental byte cursors, generation races, worker ownership, startup recovery and explicit retries. Canned CLI outputs drive extraction. |
| Extraction and merge | PASS within test scope | Valid/invalid/retried JSON, timeout/missing output, read-only flags, environment filtering, live handoff preservation, archives and pending-job retention. |
| Native Codex startup and fork | PASS with local responder | The actual Codex binary completes fresh ephemeral extraction outside Git, submits the strict schema, writes JSON, and forks a native temporary session without changing its source transcript or adding a rollout file. |
| Native Claude flags | PASS | The installed CLI accepts the full extraction flag set. Actual Claude-generated JSON remains unverified; canned Claude subprocess tests cover Ellie's parsing/merging/retry paths. |
| Install/uninstall | PASS | Real Codex and Claude registrations in fresh temporary profiles, idempotent repeated install, absolute interpreter, backups, owned-hook removal and preservation of other servers/memory. |
| Backfill and doctor | PASS | Confirmation, oldest-first capture, limits, agent filtering with another agent's failed jobs, diagnostic success/failure cases, malformed state and write errors. |
| Privacy | PASS | Secret/private-block filtering, pause/resume, conversation exclusion, archive-off, source restrictions and no repository mutations. |
| Dashboard HTTP | PASS | Packaged assets, API/search, read-only methods, loopback/origin/path boundaries, historical versions, empty state and graceful shutdown. |
| Dashboard browser | PASS | Real Chrome: previews, selected history, open historical question details, scoped search, no-history, startup commands, actual copy-button success, project switching, activity and refreshing saved changes without widening scope. |
| Responsive/visual checks | PASS for exercised views | Inspected desktop and narrow screenshots; real emulated 390×844 mobile viewport and 1440px desktop have no page overflow. No application console errors/warnings were observed. |

Real install → repeated integration setup → first dry-run launch took
**7.04 seconds**. The checkout sentinel, stored memory and unrelated MCP
registrations were preserved through uninstall. The viewer's Markdown/session
registry hashes remained unchanged after browser interaction; a separate
synthetic writer was used to verify refresh of newly saved state.

## Bugs fixed by this audit

1. **Native capture stopped before reaching a provider.** Extraction uses a
   temporary working directory, but Codex required `--skip-git-repo-check`.
   Added the flag and its compatibility check. The new real-Codex/local-SSE
   regression failed with the exact startup error before passing after the fix.
2. **Agent-filtered backfill reported unrelated pending jobs as failures.**
   Pending jobs now follow the requested agent filter, including the
   claude-code alias; other agents' jobs remain untouched.
3. **Previews could show a Markdown section label as the topic.** They now
   skip generic Goal/Current state/Next steps labels and use the content below.
4. **Markdown handoffs could leave stale current state.** Summary writes now
   remove redundant wrapper headings, contain nested headings, close unfinished
   code fences, and replace legacy duplicate summary blocks on explicit writes.
   Parsing alone remains byte-exact; historical conversation snapshots remain
   available and unrelated sections/items are preserved.

## Native CLI testing boundary

The native Codex tests run the real CLI against a loopback-only canned Responses
server with authentication disabled. They test startup, flags, streaming,
schema submission, output files and history behavior. The responder does not
call a model. This closes the earlier configuration-only test gap without
using anyone's login or credentials. See [test_native_codex.py](tests/test_native_codex.py).
The provider configuration is described in the
[official Codex reference](https://learn.chatgpt.com/docs/config-file/config-reference).

## Still unverified or outside this release

- Actual authenticated Codex/Claude provider extraction, provider-side schema
  enforcement, extraction quality and live Claude recaps require a separately
  authenticated temporary profile. Existing private capture jobs were not
  replayed by this audit, so their recovery is not certified here.
- The chat picker is rendered by the agent. A previous user screenshot proves
  the first-reply picker appeared; live model compliance with every updated
  preview instruction is not guaranteed by the hook/browser tests.
- A public PyPI release was not performed. Installation from this repository
  or a local wheel passes; v1 acceptance criterion 1's public-package clause
  remains open.
- Existing limits remain: missing legacy historical versions cannot be
  reconstructed, and a single transcript record above the checkpoint size
  limit remains pending with an explicit error.

Restart existing agents and a running UI server to load the updated code.
