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
