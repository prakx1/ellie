# Decisions

## Conversation labels (2026-11-21)

- The live picker screenshot confirmed the first-reply menu works in Codex,
  but exposed that a casual opening message outranked a saved session summary.
  Conversation catalogs now prefer the existing handoff/capture summary and
  use the opening message only until a summary exists. This changes labels
  across chat pickers, CLI, MCP and the dashboard through list_conversations.
- Derive labels when reading instead of rewriting stored conversations. Old
  captures improve without a migration, changed IDs, or another model call;
  the strict extraction schema remains unchanged. Previously displayed menus
  retain their frozen numbers and labels until a new chat is started.

## Memory picker in ordinary chats (2026-11-21)

- Opening Codex/Claude normally should require no Ellie command in the chat.
  A new unselected session supplies a numbered catalog and asks the agent to
  show it on its first reply to the user's normal message, then wait. A native
  choice control is optional; a numbered text list is the portable fallback.
  Hooks do not open an interactive menu or cause an unsolicited model turn.
- Before selection, the hook supplies catalog labels, not old item bodies or
  shared item titles. Conversation choices use a strict source filter; Start
  fresh uses conversations=[]. Named workstreams retain their existing ordinary
  load semantics. Explicit first-message selections bypass the question.
- The bounded catalog is frozen through Store in the current session registry
  until bind/load records an explicit selection. Parallel saves cannot silently
  renumber displayed choices. A More choice reaches the full catalog; empty
  automatic chat destinations and archived workstreams are omitted.
- bind/load marks context_selected and removes the temporary picker. Launcher
  selections and legacy existing bindings skip the prompt on resume. If there
  is no saved context at startup, the chat proceeds without a later interruption.
- Updated installed instructions and MCP initialization guidance reinforce the
  same behavior. Rendering remains the agent's responsibility; subprocess tests
  verify hook output and scope preservation, not a live model's compliance.

## Conversation selection and automatic capture (approved 2026-11-19)

- The user approved automatic hooks, incremental capture, startup context,
  timeline retrieval, visible capture health, and privacy controls, then added
  project-scoped conversation selection at item granularity. This extends the
  original v1 spec; its text remains unchanged.
- A workstream is a write destination. A conversation is a source of knowledge.
  They are separate concepts: one workstream can contain many conversations,
  and a repo-wide finding can retain its originating conversation in project.md.
- Explicit source selection is strict. Load, recall, get, timeline, startup,
  and dashboard views exclude unselected and unattributed content, including
  the latest global summary sections. Per-session bindings keep parallel chats
  separate and add only the current conversation's own new work to its context.
- sessions/index.json keeps item provenance and historical item/summary
  snapshots through Store. Markdown remains the current document; historical
  snapshots prevent later resolutions or supersedes leaking into an older
  selected conversation. Dedupe retains each contributing conversation. Legacy
  source fields/registries are supported, but missing old versions cannot be
  reconstructed retroactively and are labelled as such.
- Hooks persist metadata and a coalescing job before returning; model work runs
  in a separate CLI child. Checkpoints default to 120 seconds and flush on Stop,
  PreCompact, Interrupt (Codex), and SessionEnd. Worker/source locks, generation
  acknowledgements, and byte cursors protect parallel and resumed sessions.
- Incremental extraction uses fresh ephemeral CLI runs over filtered new source
  records plus only the bound historical context, avoiding reprocessing the full
  transcript. Records are paged at complete JSONL boundaries, with immutable
  gzip parts whose byte ranges reconstruct the captured session (before privacy
  filtering). Parent prefixes remain separately archived. A single oversized
  record fails clearly and leaves its job pending rather than silently dropping
  it. Hook checkpoints can capture useful work after one human prompt; manual
  v1 backfill retains its fewer-than-two-prompts skip rule.
- Private blocks (including nested/unclosed blocks) are removed from future
  Ellie content and owned archive text before persistence/model invocation.
  New capture archives also redact common credential patterns. Unchanged safe
  records retain their exact bytes. The upstream agent transcript and old raw
  archives remain untouched. Filtered manual captures use a fresh CLI instead
  of resuming private source history. Pause/exclude retain existing data and
  pending jobs; they stop future capture and agent writes. Archive mode can be
  filtered or off, with filtered as the new default.
- User-level Codex hooks.json and Claude settings.json are changed narrowly and
  backed up; repo-local hooks are never written. Commands use a quoted absolute
  interpreter. Uninstall removes only exact Ellie-owned handlers. Codex hooks
  were stable/enabled in the installed CLI under a temporary profile; native
  trust review remains the user's choice, never bypassed by the installer.

- The dashboard's source selection is read-only and generates a quoted startup
  command. Its server filters item text and global summaries before returning
  the selected view; it does not rely only on hiding cards in JavaScript.
  A separate catalog lets the user choose sources without changing bindings in
  other active chats. Project switching clears the source filter.
- Agent content calls without session_id fail once bindings exist, rather than
  silently escaping a conversation restriction. Status/catalog/privacy remain
  available for setup. CLI browsing and the local viewer stay user-controlled.
- Dedupe and delayed capture acknowledgement preserve existing historical item
  snapshots; they cannot copy another conversation's later answer/status into
  the earlier snapshot. Worker liveness checks require the owned heartbeat lock
  as well as a live PID. Explicit retry includes incremental jobs even while
  the original conversation is still open.
- Browser preview remains unavailable (untrusted/missing privileged bridge).
  Temporary jsdom tests exercise UI interactions against real isolated HTTP
  endpoints; this is DOM verification, not visual browser verification. The
  test library lives outside the repo and adds no runtime/test-suite dependency.

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

## Milestone 7

- Backfill shows candidates and an extraction-use estimate, requires explicit
  confirmation unless --yes, and runs oldest first through the same durable
  capture pipeline. Default ambiguous external assignments are proposed by the
  model rather than prompting for every session.
- Doctor runs without constructing the index so it can diagnose a corrupt
  cache. It checks CLI help/login status without a model invocation, uses the
  actual Codex MCP get response for registration, inspects session formats,
  reports corrupt pending JSON, and probes real store write access.
- An isolated wheel installation exposed that resolving sys.executable follows
  a virtual-environment symlink to the base interpreter, losing installed Ellie.
  Registration now preserves the absolute interpreter path without resolving
  symlinks. A unit regression and installed-wheel MCP handshake verify this.
- Local wheel installation through dry-run startup was measured separately
  from source imports, with PYTHONPATH unset and temporary homes/tool directories.
  Package metadata reports no runtime dependencies and both resource files ship.
- The full suite reproduced a simultaneous SQLite schema-creation race on both
  Python 3.14 and 3.15. Cache initialization is now serialized under its file
  lock; failed initialization closes the connection and does not attach a store
  callback. An eight-process fresh-cache barrier test exercises this boundary.

## Milestone 8 acceptance review

- A regression reproduced failure to reindex a corrupt cache. Reindex now
  initializes separately from normal service startup and quarantines corrupt
  database/WAL/SHM files before rebuilding from Markdown. Lock-contention errors
  do not trigger quarantine. Memory bytes are asserted unchanged after recovery.
  Already-running clients holding the damaged cache may require a restart.
- Claude image-only user messages count as human prompts; tool results and
  meta/sidechain records remain excluded. Extraction output decoding is UTF-8.
- The complete public Store protocol now includes the logical mutations and
  local support operations actually used by CLI/MCP/capture; root/path describe
  per-device cache/support locations, not a future cloud backend's content.
- Public PyPI publishing and authenticated end-to-end CLI checks are separate
  from the automated fixture verdicts. No live model call or real-home install
  was performed; the acceptance report makes these limits explicit.

## Local dashboard (0.2.0)

- The user's follow-up explicitly requests an HTML UI, bringing forward the
  dashboard deferred in §2 of the original v1 spec. The original spec remains
  unchanged. `ellie ui` serves packaged HTML/CSS/JavaScript through Python's
  standard-library HTTP server; no frontend build or runtime dependency is added.
- This first viewer is read-only. It reads documents, logs, and saved capture
  metadata through Store; search uses the existing ranked index and may rebuild
  its cache. It does not call load/status, discover agent sessions, start models,
  inspect transcript archives, write memory, or modify a user's repository.
- Bind only to 127.0.0.1. Reject foreign Host/Origin and cross-site fetch headers,
  provide no CORS access, and disallow mutation methods. Package a fixed asset
  whitelist and use a restrictive content policy. Saved Markdown is inserted as
  text, never evaluated as HTML. No analytics or external assets are requested.
- Each search opens and closes its own index on the request thread. The server
  handles simultaneous browser requests with a bounded socket timeout; it shares
  the Store interface rather than introducing another content backend.
- Automatic browser preview could not connect: the browser plugin reported
  "privileged native pipe bridge is not available; browser-client is not trusted".
  HTTP/subprocess, asset packaging, and JavaScript syntax checks cover behavior;
  visual and browser-interaction verification remains an explicit limitation.
