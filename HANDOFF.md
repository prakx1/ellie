# Handoff

## Active extension: conversations and automatic capture (2026-11-19)

User approved the claude-mem-inspired improvements and specifically requires
selecting source conversations per project, at item granularity, while excluding
others. Implementation is in progress; do not treat the whole extension as done.

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

Next: finish conversation selection and health in the dashboard (API filter
tracer is in progress), run the full suite on Python 3.10/latest, package smoke,
update docs, commit and push only code/tests/development docs. Never inspect or
push the user's real memory. No authenticated model run or real profile edit has
been performed; Codex's hook feature was checked in an isolated profile and is
stable/enabled. Hook trust must still be reviewed by the user in the client.

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
  its protocol; cloud, sync, hooks for plain sessions, and semantic search remain
  out of v1 scope.
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
