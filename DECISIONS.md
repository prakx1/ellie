# Decisions

## Step 0 compatibility decisions (approved 2026-11-18)

The user approved proceeding after Step 0. `spec.md` remains unchanged.
See `STEP0.md` for evidence and verification limits.

- Strengthen extraction isolation to exclude inherited write-capable tools,
  MCP servers, and hooks. An empty Codex MCP table does not clear servers;
  disable them explicitly or use a verified isolated configuration.
- Unwrap Claude's `structured_output` envelope before schema validation.
- Support legacy/paginated Codex prompt events and Claude's distributed
  metadata. Count human prompts rather than raw user-role records.
- Match launcher sessions with a before/after snapshot and run window;
  keep ambiguous jobs pending.
- For explicit cross-agent extraction, propose a fresh ephemeral CLI run
  with transcript context because native session IDs are not portable.
- Preserve available raw transcripts and required fork ancestry; report
  upstream truncation/missing history instead of promising recovery.
- Use supported versioned Python interpreters, isolated homes, and fake
  agent scripts in tests.

## Milestone 1

- Parsing/rendering is byte-exact, including an absent final newline and CRLF
  input. An explicit store save normalizes line endings to LF and removes
  earlier duplicate frontmatter keys, retaining the last value. This separates
  the round-trip promise from the explicit save normalization in §4.5.
- Hand-edited incomplete items remain readable; programmatically created items
  validate their required fields and enumerated values before allocation.
- A project-wide lock serializes ID allocation and cross-memory mutations;
  file locks protect individual replacements. Locks refresh their mtime while
  alive so long operations do not become falsely stale after 60 seconds.
- IDs scan active/shared/archived memories. A per-device high-water mark in
  state.json also prevents reuse after manual deletion or a failed write.
  Failed writes can leave ID gaps; reusing reserved IDs would be less safe.
- Store extends the spec's minimal interface with locked mutations and local
  JSON operations so callers do not perform unsafe read/modify/write sequences.
- Store roots inside Git repositories and symlinks inside the store are
  rejected, preventing memory writes from reaching a user's repository.
- Common-secret redaction is implemented at the storage boundary now because
  milestone 1 already introduces item write paths. Raw transcript archives
  remain exact copies of the available source, as specified.

## Milestone 2

- SQLite bm25 returns negative relevance values, with more relevant matches
  more negative. Negate it before applying the recency/type multipliers and
  sort scores descending; multiplying raw negatives would reverse the weights.
- Natural-language queries match any word, with title weight 5 and body weight
  1. Escape FTS terms and LIKE wildcard characters rather than accepting SQL or
  FTS query syntax. LIKE applies Python Unicode casefolding.
- Search includes archived memories, preserving project history and IDs.
  Missing/invalid dates receive a neutral recency multiplier; future ages clamp
  to zero. The index records mtime nanoseconds, size, and archive location.
- Write callbacks update the cache immediately. Startup/search checks also
  detect external edits, moves, and deletions. Closing an index detaches its
  callback; Markdown remains the source of truth.

## Milestone 3

- A shared MemoryService routes MCP operations through Store mutations and
  keeps the search cache current. Protocol includes these mutation/cache/local
  operations so callers do not depend on FileStore-specific implementation.
- Briefing rendering was brought forward from milestone 4 to meet the MCP
  load contract. Shared memory includes Overview and Conventions; workstreams
  use Goal/State. Both apply the specified active/open/recent-item filters.
- MCP returns text content plus structuredContent for successful object
  results; tool errors return isError without terminating the process. Invalid
  transport JSON returns standard JSON-RPC errors. Notifications have no reply.
- Handoffs also mark the pending launcher record under a lock. This preserves
  live state for Codex runs whose session ID is not known until after exit.

## Milestone 4

- Argument splitting happens before argparse; only start accepts the suffix
  after --. Argument errors follow the spec's ellie: prefix and exit code 1.
- Dry-run renders draft memories without saving them, recording last-used
  state, creating pending captures, or invoking an agent. The rebuildable
  index can still be initialized. Non-TTY selection uses valid last-used names.
- Imported Markdown is fenced under Current state with a fence longer than
  any source fence. This keeps imported headings/IDs from becoming Ellie
  sections or items while preserving the text for subsequent capture.
- Explicit Claude --session-id passthrough is preserved and validated rather
  than duplicated; otherwise the launcher generates a UUID.
- The selector supports show/search-more/toggle/cancel and whole-memory rows.
  Automatic preselection stops at 12 items or 8000 item characters. Explicit
  choices can exceed that budget; startup's total briefing limit still applies.
- Background extraction and external uncaptured-session discovery are connected
  in milestone 6, after the agent adapters exist; launcher tests use fake agents
  with --no-capture and already verify durable pending records.

## Milestone 5

- Installation backs up existing config before invoking either agent's MCP
  mutation commands. Backups are never overwritten; memory files and Claude
  permission settings are not modified by uninstall/integration setup.
- A small lexical TOML scanner targets only Ellie's table/subtables and tracks
  arrays, quotes, multiline strings, and comments. It rejects unsafe inline or
  dotted Ellie assignments in fallback mode rather than risk unrelated config.
- Installed Claude 2.1.278 writes user MCP config to HOME/.claude.json normally,
  or CLAUDE_CONFIG_DIR/.claude.json when the override is set (verified with the
  actual CLI in a temporary home). Instruction files respect that override too.
- Claude also has a JSON fallback when its CLI is unavailable or unsuccessful;
  registration is verified from config before success is reported. Other JSON
  keys/servers are preserved. The user explicitly opts into blanket approvals.
- Agent-config targets inside a Git repo or symlinked config files are refused,
  consistent with the no-repository-modifications constraint.

## Milestone 6

- Discovery reads agent-owned formats only through their adapters, filters by
  project identity (including subfolders/clones), and reports malformed files
  rather than guessing. Codex matching uses snapshot changes and exact launch
  cwd; ambiguous jobs stay pending. Active known launcher runs are excluded.
- Capture uses source mtime/size versions, so resumed sessions with new records
  become uncaptured again. Job and session locks prevent duplicate extraction.
- Codex extraction ignores user config/rules, disables hooks/plugins/apps/shell
  and multi-agent tools, disables configured MCP servers explicitly, and forces
  read-only/never-escalate policy from a temporary cwd. Claude uses safe mode,
  no built-in tools, an empty strict MCP config, and disabled permission prompts;
  its native resume runs from the source project cwd for history lookup. Old
  clients missing required safety flags fail before model invocation.
- API-key/auth-token environment variables are removed from extraction children.
  Subscription credentials remain the CLI's responsibility; Ellie never reads
  or copies login files. Live authenticated behavior remains unverified here.
- Every schema object is strict with all properties required and explicit nulls.
  Python validates shape and references before merge; invalid JSON/schema gets
  one retry. CLI failures/timeouts retain pending records for explicit retry.
- Archives are saved before model invocation so failed extraction does not lose
  the available source snapshot. Paginated parent prefixes are archived at their
  recorded byte boundary under distinct names, and linked from the registry.
  Missing parent history fails the job. Cross-agent input uses these snapshots,
  with an explicit 2000000-character limit; native forks avoid that transfer.
- Live tool items are tracked in pending records even before a Codex session ID
  is known. Their IDs join the final registry. Auto handoff log entries carry a
  capture marker so subsequent extraction does not mistake them for live state.
- Duplicate decision retries also repair supersede statuses, allowing recovery
  from an interrupted multi-file save. Summaries count associated items and
  distinguish failed/partial/worked results; they are displayed on the next CLI
  project command (JSON output remains machine-readable).
