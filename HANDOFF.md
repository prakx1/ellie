# Handoff

## State

All eight requested implementation/review milestones are complete. The original
spec.md is unchanged. See ACCEPTANCE.md for every §19 criterion and its scope.
93 unittest tests pass on Python 3.10.20, 3.14.3, and 3.15.2; the final token-refresh
assertion was also rerun on all three. No automation failures remain.

The final wheel was installed into an isolated uv tool environment with
PYTHONPATH unset. Fresh local install through dry-run startup took 5.97 seconds;
the registered installed MCP command successfully lists all 14 tools. Wheel
metadata has no runtime dependencies, and its modules/resources match source.
Artifact: dist/ellie-0.1.0-py3-none-any.whl (ignored build artifact).

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
read-only. No real agent configuration, real Ellie store, or credentials were
modified. No live model calls or API keys were used.
