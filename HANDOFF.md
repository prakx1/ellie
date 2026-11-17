# Handoff

## State

The user approved proceeding. Milestone 1 is committed as 40d6606.
Milestone 2 is committed as 2dce7ec (36 tests passed on both Python versions).
Milestone 3 is committed as d918285 (44 tests passed on both versions).
Milestone 4 implements CLI, launcher, picker, history selector, --about/--with,
and the startup template. Its 13 targeted CLI/briefing tests pass on both
versions, including fake agents, a real pseudo-TTY, and BrokenPipe handling.
All 55 tests pass on Python 3.10.20 and 3.14.3.
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

1. Commit milestone 4; implement milestone 5: safe,
   idempotent Codex/Claude install/uninstall, backups, and targeted TOML edits.
2. Continue milestones 6-8 in order, testing and committing each.
3. Keep every subprocess test isolated using tests.support.IsolatedTest and
   temporary HOME/CODEX_HOME/ELLIE_HOME. No subagent work has been requested.

## Open checks

- Authenticated ephemeral fork/no-resume-history behavior, server-side schema
  strictness, and live MCP approval behavior remain unverified. Do not access
  or copy real credentials to test them.
- Extraction must exclude inherited MCP tools/hooks as well as enforce
  read-only/no-tool access.
- Validate Claude's inner `structured_output` rather than its result envelope.
- Add fixtures for both Codex history generations and Claude prompt/tool-result
  distinctions.
- Handle concurrent/resumed-session matching and paginated fork archive ancestry.
- Cross-agent extraction requires transcript context, not native resume IDs.
