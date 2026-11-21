# Handoff

## Required commit attribution (2026-11-20)

All commits made for this project must be attributed to the user's personal
GitHub account, prakx1. Use the repository's configured Git identity. Never
override the author or committer with Codex, codex@localhost, or another bot
identity. If a fresh checkout has no identity, resolve the user's authenticated
GitHub profile instead of inventing an author; keep any configuration local to
the intended repository.

The original 13 commits were repaired to use the user's GitHub-linked identity,
preserving each commit's files, message, author date, and commit date. This
changes commit IDs, so milestone hashes recorded below predate that repair.
A verified original-history bundle and old-to-new mapping are kept locally
under .git; they are not pushed. The repair was published with an explicit
force-with-lease check against the original remote tip. Runtime code and
private memory are unchanged by this attribution correction.

## Capture transport fix and fresh reads (0.3.4, 2026-11-21)

A read-only operational check found live memory writes continuing while
background extraction failed before a model could run. The generated Codex
command ignored user configuration and then created disabled MCP entries with
no transport. Codex still validates those entries. Quoted dotted CLI override
keys also produced incorrect names, so an initial transport-only repair did
not handle server names containing dots. A real CLI regression reproduced
both failures under temporary profiles before the final fix passed.

Codex overrides now use an inline TOML server map with exact quoted names,
enabled=false and inert commands pointing to nonexistent paths in the temporary
extraction directory. External MCP remains disabled, with read-only sandbox,
no shell/hooks/plugins/apps, ephemeral sessions and no API keys. No user
configuration is rewritten. Tests cover ordinary, hyphenated, dotted and
quote-containing server names using real Codex mcp list without model/auth.

The operational check also found an existing briefing older than a subsequent
live save. Hook/install guidance now requires a fresh load for latest-progress
questions while preserving the user's source selection. status's tool
description clarifies that it returns inventory/health, not current work.

All 53 relevant session/capture/hook/MCP/install tests pass on Python 3.10.20
(112.2s) and 3.15.0a7 (114.4s). The original red/green config-parser regression
and fake extraction subprocess also pass on 3.14.3. No unrelated runtime/UI
code changed; the 132-test 0.3.3 baseline remains recorded below. Real failed
jobs were not retried, memory/bindings were not changed, and no authenticated
extraction was run during this read-only check. Provider/auth/schema success
and recovery of those jobs still require operational verification.
The isolated Python 3.10 installed wheel passes real Codex config validation,
both hook entrypoints, scoped no-history loading and MCP initialization with
zero model calls. The user executable was separately upgraded to 0.3.4 using
isolated profiles; all 31 runtime files match the tested wheel. A subsequent
read-only health check still reports the old failed jobs: updating code alone
does not claim or acknowledge a capture retry. No private project content,
session identifiers or user configuration is included in the regression tests.

## Memory content previews (0.3.3, 2026-11-21)

The user clarified that the picker must explain what each memory is about;
preferring a summary over an opening message did not meet that requirement.
Choices now show a Covers description, up to three saved topics, state and
next step where present. Chat instructions explicitly require the preview to
remain visible even if native choice controls hide option descriptions. The
terminal conversation picker and dashboard cards show the same fields.

preview.py derives small redacted excerpts from saved goals, useful summaries,
historical item titles and per-conversation state. Generic completion text is
ignored, missing summaries fall back to saved topics, state-only handoffs are
described, and the raw chat opener is never the topic. No useful saved content
produces an explicit missing-description label rather than an invented topic.
Conversation state comes only from its own session snapshots, never another
chat's newer global workstream state. Shared-project picker text stays general.
All reads use Store; no migration, extra model call or extraction-schema change.

Regression loops reproduced the generic-summary and missing-preview failures
before implementing the fixes. Tests cover own-session provenance, state-only
handoffs, chat hooks for both agents, terminal selection and actual HTTP data.
All 132 tests pass on Python 3.10.20 (207.7s) and 3.15.0a7 (218.3s), following
34 focused passes on 3.14.3. JavaScript syntax checks pass. The isolated 3.10
installed wheel's real hooks produce Covers/State/Next previews for both
agents from a generic-summary fixture, keep full bodies unloaded, preserve a
subsequent no-history selection, and pass MCP initialization. No model calls
or runtime dependencies were added. Live agent rendering of these new preview
lines and visual dashboard layout remain unverified. Existing frozen menus
need a new chat after restarting the agent; real profiles/memory are not edited.
The user tool was separately upgraded to 0.3.3 with isolated profile/cache
directories; its 31 runtime files match the tested wheel. No real-profile
ellie install was run. Existing installed hook paths remain valid.

## Conversation label fix (0.3.2, 2026-11-21)

The user's screenshot shows the first-reply picker in Codex 0.171.0 after a
normal greeting, confirming that the agent displayed the menu. It
also exposes an old conversation's casual opening message as its label. No
selection/load action or automatic extraction was demonstrated by that image.

The cause is list_conversations preferring the stored opening-message title
over a saved handoff/capture summary. It now prefers the summary and retains
the opener only as a fallback. The shared catalog fixes chat, CLI, MCP and UI
labels without rewriting old memory or changing IDs, bindings, extraction
schema or model calls. An already displayed picker keeps its frozen labels;
start a new chat to receive the improved ones. README explains this distinction
between a conversation label and a workstream name.

The regression reproduced the exact label-precedence failure before the fix,
then passed through MemoryService.conversations with unchanged session data.
The real hook subprocess regression checks summary labels for both agents.
All 126 tests pass on Python 3.10.20 (217.1s) and 3.15.0a7 (227.6s); the final
synthetic-label regressions also pass on 3.14.3. The isolated installed 3.10
wheel passes both hook entrypoints and MCP initialization with no model calls
or runtime dependencies. The user's executable was separately upgraded to
0.3.2 with isolated profiles; all 30 runtime files match the tested wheel.
No real agent configuration or private memory was changed. Tests use invented
conversation content, not the user's session files or copied memory.

## Chat memory picker (0.3.1, 2026-11-21)

The user wants a picker inside ordinary Codex/Claude chats without typing an
Ellie command. New unselected sessions now inject a numbered catalog and ask
the agent to show it on its first reply to a normal message, then wait before
starting the task. Conversation titles/dates/counts, named workstreams, Start
fresh, shared project memory when present, and More choices are available.
Old memory bodies are not injected before the choice. The client can render
a native choice control or a numbered text list; hooks do not start a model
turn before the user's first message.

Choices are frozen through Store so parallel captures cannot renumber the
displayed catalog. bind/load marks the context selected and removes the
temporary picker. Strict conversation filters and no-history remain intact.
Launcher choices, existing legacy bindings, and resumed selections skip the
question. Projects with no saved context skip it; empty automatic destinations
and archived workstreams are omitted. Catalog rows stay within the hook budget
and a More option reaches the full catalog. Updated install/MCP guidance and
README describe this behavior. The original spec remains unchanged.

Validation: 32 focused hook/install/conversation/MCP tests passed on Python
3.14.3. The clean Python 3.10 installed wheel passed real hook subprocesses for
both agents, source exclusion/selection checks and an MCP initialize round-trip
with isolated profiles and no model calls. Its metadata has zero runtime deps.
All 125 tests pass on Python 3.10.20 (166.9s) and 3.15.0a7 (177.6s). Live model
compliance with the prompt and a native choice widget remain unverified.

Current isolated development runner and wheel are under
/private/var/folders/93/djm21yqn3979_wbdq5vpv4_c0000gq/T/ellie-picker-gozwbkpb.
The older development temp root below has expired. run.py isolates all agent,
memory, XDG and uv directories; smoke.py checks the installed wheel using -I.
No real agent configuration or private memory files were changed by this work.
The existing user tool executable was upgraded separately to 0.3.1 using the
same Python 3.14 interpreter and isolated configuration/cache directories;
all 30 installed runtime files match the tested wheel. Existing hook command
paths remain valid. Restart agents for new MCP guidance; ellie install can
refresh the expanded instruction block, but was not run against real profiles.

## README update (2026-11-20)

Expanded installation prerequisites, clone/setup commands, agent-specific setup,
and upgrade steps. The guide now distinguishes installing the executable from
registering MCP/hooks, explains restart and Codex hook trust, supports starting
agents normally, and walks through the local UI and conversation selection.
Troubleshooting covers a stopped/suspended UI server, occupied ports, empty
memory views, ELLIE_HOME mismatches, and missing capture timestamps.

Documentation-only change. Verified the documented CLI/uv flags using help
commands with temporary HOME/CODEX_HOME/ELLIE_HOME/Claude/XDG/uv-cache paths;
no memory was created. Markdown fences and git diff whitespace checks pass.
The application version and runtime behavior remain 0.3.0. The previous full
119-test Python 3.10/3.15 results remain the runtime baseline; no full rerun was
needed for prose changes. No real agent profiles or private memory were read
or changed for this documentation task.

## Active extension: conversations and automatic capture (2026-11-19)

User approved the claude-mem-inspired improvements and specifically requires
selecting source conversations per project, at item granularity, while excluding
others. Implementation is complete in 0.3.0.

First slice: conversation provenance and historical versions are stored through
Store in sessions/index.json. New source filters cover load/get/recall/timeline,
briefings, startup flags and the picker. Explicit session_id bindings isolate
parallel MCP chats. Added conversations, bind and timeline tools (17 total).
47 focused tests pass, including real MCP subprocess and CLI exclusion checks.

Second slice: native Codex/Claude lifecycle commands now bind normal sessions,
inject compact context, and queue durable checkpoints. Background workers batch
complete new JSONL records, preserve newly queued generations during extraction,
and retry CLI failures at most three times. Hooks never call a model directly.
Installation/uninstall preserve other hooks and permissions. Private text and
common secrets are filtered from new Ellie-owned archives and model input; pause,
exclude/include, and archive-off controls are available. Existing raw archives
are not retroactively changed. Capture health includes observed/saved/captured
times, pending work and errors. 116 tests pass on Python 3.14.3.

Third slice: the dashboard has conversation selection, server-side source
filtering, historical details, per-item source labels, save/capture health, and
a startup-command copier. --no-history starts without old context. Agent content
calls missing session_id fail closed once bindings exist. Historical snapshot
replay and active-session explicit retry have regression coverage.

Final validation: 119 unittest tests pass on Python 3.10.20 and 3.15.2. The clean
Python 3.10 wheel serves its packaged UI, registers 18 MCP tools, preserves strict
conversation versions and scope, and runs the installed hook entrypoint with no
model calls. Fresh install to dry-run startup took 3.29 seconds. Metadata has no
runtime dependencies; schema remains 11 top-level properties. Node syntax and
temporary DOM tests passed project switching, source choice, search, historical
details, clipboard, timeline, no-history and empty state without DOM errors.
Visual layout remains unverified because the browser bridge is unavailable.

No authenticated model run or real agent-profile edit has been performed. Codex
hooks were stable/enabled under a temporary profile. The installed user CLI is
updated separately; the user must run ellie install, restart the client, and
review/trust Codex hooks with /hooks to activate automatic capture. Only source,
tests and development docs are committed/pushed; never the user's real memory.

Extension commits: fc03930 (provenance/selection), 6d8d0bc (hooks/privacy/capture),
and the following dashboard/integration commit. Wheel: dist/ellie-0.3.0-py3-none-any.whl.
Isolated smoke: temporary-root/package-smoke-conversations-final/result.json.
DOM smoke: temporary-root/ui-dom/smoke.cjs (temporary jsdom; not a runtime dep).
Remaining limits: legacy untracked sources/versions cannot be reconstructed;
single JSONL records over 1000000 bytes remain pending; live authenticated
extraction/provider behavior and browser layout need separate verification.

## State

All eight requested implementation/review milestones are complete. The original
spec.md is unchanged. See ACCEPTANCE.md for every §19 criterion and its scope.
The original 93 unittest tests passed on Python 3.10.20, 3.14.3, and 3.15.2.
The 0.2.0 dashboard brings the suite to 100 tests: all pass on 3.10.20 and
3.15.2, and the seven dashboard tests also pass on 3.14.3. No automation failures
remain.

The final wheel was installed into an isolated uv tool environment with
PYTHONPATH unset. Fresh local install through dry-run startup took 5.97 seconds;
the registered installed MCP command successfully lists all 14 tools. Wheel
metadata has no runtime dependencies, and its modules/resources match source.
Artifact: dist/ellie-0.1.0-py3-none-any.whl (ignored build artifact).

## Local dashboard (0.2.0)

The user's follow-up requested an HTML UI. `ellie ui` now opens a loopback-only
dashboard with project navigation, workstream/type/archive filters, ranked
search, goals/state/next steps, complete item fields and memory text, copy,
and saved log/capture activity. It refreshes every 15 seconds while visible.
Use `--no-open` to print the URL or `--port 0` to select a free port.

The server uses stdlib only and Store for saved data. It never loads agent
context, scans agent session roots, starts extraction, or writes memory. Search
uses the existing SQLite cache. Foreign Host/Origin/cross-site requests and
mutation methods are rejected. User text never becomes HTML. Packaged assets
make the installed tool self-contained and require no network.

Verification: real HTTP requests and CLI subprocesses cover content, search
ranking, archives, capture records, empty stores, path/method/origin boundaries,
unchanged document/repo bytes, and graceful shutdown. A clean Python 3.10 wheel
installation serves HTML/CSS/JS/JSON with PYTHONPATH unset; its MCP registration
still lists 14 tools and package metadata has no runtime dependencies. Node's
JavaScript syntax check passes. The browser plugin could not connect because
its privileged bridge was unavailable/untrusted, so browser interactions and
visual layout remain unverified. Do not describe this as browser-tested.

Wheel: dist/ellie-0.2.0-py3-none-any.whl (ignored build artifact).
Isolated installed-wheel smoke record: temporary-root/package-smoke-ui/result.json.

## Milestone commits

1. 40d6606 — paths, lossless model, locked file store, IDs, supersede/resolve.
2. 2dce7ec — FTS5/LIKE index, ranking, external edits, reindex.
3. d918285 — stdio MCP and all 14 tools, subprocess protocol tests.
4. b8c2687 — CLI, launcher, picker, history checklist, startup template.
5. c491ecb — idempotent safe install/uninstall and backups.
6. 7b27d54 — adapters, safe extraction, strict schema/retry, merge/background jobs.
7. 6394135 — backfill, doctor, README, interpreter and startup-race fixes.
8. This commit — acceptance report, corrupt-index recovery, final regressions.

## Next steps / open issues

- Public PyPI publishing was not requested/performed. Criterion 1 is not closed;
  local-wheel installation is verified, but public uv tool install ellie is not.
- Real authenticated native extraction, no-resume-history behavior, provider
  schema enforcement, live approval behavior, and Claude-generated recap remain
  unverified. Automated model-dependent verdicts use canned CLI processes.
- Use a separately authenticated isolated profile for live checks. Never copy
  the user's real credentials or run development/tests against real agent roots.
- If an already-running client retains a corrupt cache connection, restart it
  after ellie reindex quarantines/rebuilds the damaged cache. Markdown is intact.
- No known failing automated checks. Store is ready for another backend through
  its protocol; cloud, sync, and semantic search remain outside this release.
  Hooks for ordinary sessions are included in the 0.3.0 extension above.
- Visually check the dashboard in a browser when browser access is available,
  including narrow screens, search/filter combinations, and the details dialog.

## Development environment

Temporary root:
/var/folders/93/djm21yqn3979_wbdq5vpv4_c0000gq/T/ellie-dev-l1b5i_i2

run.py in that root runs commands with isolated HOME/CODEX_HOME/ELLIE_HOME,
CLAUDE_CONFIG_DIR/XDG/uv directories and source PYTHONPATH. The installed-wheel
smoke helper deliberately unsets PYTHONPATH and uses a separate tool directory.
Python 3.10 and 3.15 are under python/cpython-<version>-macos-aarch64-none/bin/;
Python 3.14 is /opt/homebrew/bin/python3.14. README also documents a fresh test
home setup that does not depend on these temporary paths.

Only the explicitly requested Step 0 session inspection used real agent state,
read-only. No development/tests modified real agent configuration, the real
Ellie store, or credentials. The user's installed CLI was upgraded separately
from tests; integration config and existing memories remain intact. No live
model calls or API keys were used.
