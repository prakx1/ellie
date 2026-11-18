# Handoff

## State

The user approved proceeding. Milestone 1 is committed as 40d6606.
Milestone 2 is committed as 2dce7ec (36 tests passed on both Python versions).
Milestone 3 is committed as d918285 (44 tests passed on both versions).
Milestone 4 is committed as b8c2687 (55 tests passed on both versions).
Milestone 5 is committed as c491ecb (63 tests passed on both versions).
Milestone 6 implements adapters, safe headless extraction, strict schema/retry,
merge/state/dedupe rules, ancestry archives, external capture, durable retries,
and automatic background capture. Targeted tests pass on both versions,
including actual fake-CLI subprocesses, concurrent workers, and launcher exit.
All 84 tests pass on Python 3.10.20 and 3.14.3.
Milestone 6 is ready for its commit.
Read the full supplied spec and copied it unchanged from
`/Users/prakash.singh/Downloads/spec (4).md` to `spec.md`.
`STEP0.md` contains command evidence, session formats, corrections, and limits.
Implemented paths.py, model.py, store.py, redaction, and package metadata.
The milestone 1 suite of 29 tests passed on Python 3.10.20 and 3.14.3. Tests cover real temporary
Git worktrees, byte round-trips, eight concurrent writer subprocesses, IDs,
supersede/resolve, redaction, stale locks, atomic-failure recovery, and archives.
Index tests cover FTS5/LIKE ranking, filtering, superseded exclusion, Unicode,
external edits/deletion, archives, reindex, and callback cleanup.

## Environment and constraints

- Installed CLIs: Codex 0.169.0; Claude Code 2.1.278. Both fork paths exist.
- Default python3 is 3.9.6; versioned Python 3.11/3.12/3.13/3.14 and uv exist.
- No runtime dependencies, API keys, real-home writes, or Ellie-originated
  modifications to a user's repository.
- The only real agent-state access was authorized read-only session inspection.
- CLI probes used temporary HOME/CODEX_HOME/ELLIE_HOME/CLAUDE_CONFIG_DIR/XDG roots.
- Probe evidence:
  `/var/folders/93/djm21yqn3979_wbdq5vpv4_c0000gq/T/ellie-step0-oj3_jlhh`.

## Next steps

1. Commit milestone 6; implement milestone 7: oldest-first
   backfill with confirmation/estimate, doctor, and README/installation docs.
2. Complete milestone 8 acceptance review with honest pass/fail and integration
   limits; fix any implementation gaps found during that review.
3. Keep every subprocess test isolated using tests.support.IsolatedTest and
   temporary HOME/CODEX_HOME/ELLIE_HOME. No subagent work has been requested.

## Open checks

- Authenticated ephemeral fork/no-resume-history behavior, server-side schema
  strictness, and live MCP approval behavior remain unverified. Do not access
  or copy real credentials to test them.
- Required extraction isolation, schema/envelope handling, both history formats,
  live-state protection, concurrency, cross-agent context, and parent archive
  boundaries are implemented and tested with fake CLIs. Actual authenticated
  CLI integration is still intentionally unverified.
