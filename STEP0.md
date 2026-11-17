# Step 0 verification

Date: 2026-11-18 (Asia/Kolkata). Implementation is paused pending the user's OK.

## Scope and isolation

Read all 760 lines of the supplied spec and copied it unchanged from
`/Users/prakash.singh/Downloads/spec (4).md` to `spec.md`.
The workspace was empty and is not yet a Git repository. No application code,
tests, package metadata, or agent installation has been created.

Every CLI subprocess used a temporary working directory and temporary HOME,
CODEX_HOME, ELLIE_HOME, CLAUDE_CONFIG_DIR, and XDG config/cache/data directories.
Known API-key/auth-token variables were removed from the subprocess environment.
No model invocation, credential read/copy, or login was performed. Three real
Codex and three real Claude JSONL session files were inspected read-only, as
explicitly requested. Transcript content was not copied into the workspace.
The user's real Ellie store was not accessed.

Raw help output is retained in the temporary probe directory:
`/var/folders/93/djm21yqn3979_wbdq5vpv4_c0000gq/T/ellie-step0-oj3_jlhh`.

## Installed versions and flags

All requested commands exited 0: `codex exec fork --help`, `codex exec --help`,
and `claude --help`. Also checked Codex exec resume and MCP add/get help.
Installed versions: `codex-cli 0.169.0`; `2.1.278 (Claude Code)`.

| Capability | Codex 0.169.0 | Claude Code 2.1.278 |
| --- | --- | --- |
| Headless | `codex exec` | `-p`, `--print` |
| Fork | `codex exec fork <SESSION_ID> [PROMPT]` | `--resume <id> --fork-session` |
| Resume | `codex exec resume [SESSION_ID] [PROMPT]`; `--last`, `--all` | `-r`, `--resume [value]`; `-c`, `--continue` |
| No saved session | `--ephemeral`, also on fork/resume | `--no-session-persistence`, print mode only |
| Schema | `--output-schema <FILE>` | `--json-schema <schema>` |
| Output | `-o`, `--output-last-message <FILE>`; `--json` for JSONL events | `--output-format json` or `stream-json` |
| Read-only controls | Exec exposes `-s`, `--sandbox read-only`; fork exposes `-c`, allowing `-c 'sandbox_mode="read-only"'` | No `--read-only` flag. `--disallowedTools`, alias `--disallowed-tools`; `--tools ""` removes built-in tools |
| Other relevant controls | `-c 'approval_policy="never"'`; `--ignore-user-config`, `--ignore-rules` | `--strict-mcp-config`, `--mcp-config`, `--setting-sources`, `--settings`, `--disable-slash-commands`, `--session-id <uuid>` |

The extraction flags shown in the spec exist in these installed versions.
Their presence does not prove end-to-end isolation or history behavior.
Extraction must fork rather than append to the source session. Use subprocess
argument arrays, with config/schema/prompt values passed as individual arguments.

Claude's `--permission-mode plan` is not a general filesystem sandbox. Its
`--tools ""` does not remove MCP tools. Do not use `--bare` for subscription
extraction: installed help says it disables Anthropic OAuth/keychain auth and
requires API-key or apiKeyHelper authentication.

## Real session files and metadata

### Codex

Found 71 rollout files under:
`~/.codex/sessions/YYYY/MM/DD/rollout-<local-datetime>-<uuid>.jsonl`.
Production discovery must respect CODEX_HOME. Inspected files created by
versions 0.107.0, 0.162.1, and 0.169.0: an old CLI session, a long-lived desktop
session, and the current Ellie session.

All three began with `session_meta`. Representative shape, with identifying
values shortened and unrelated fields omitted:

```json
{
  "timestamp": "2026-11-17T19:22:13.011Z",
  "type": "session_meta",
  "payload": {
    "id": "01a1eaf3-...",
    "session_id": "01a1eaf3-...",
    "timestamp": "2026-11-17T19:19:39.665Z",
    "cwd": "/Users/.../ellie",
    "cli_version": "0.169.0",
    "source": "cli",
    "history_mode": "paginated"
  }
}
```

New records also have top-level `ordinal`. Older records lack that field,
`session_id`, and `history_mode`. Use `payload.id`, `payload.cwd`, and
`payload.timestamp`, with defensive fallbacks. The outer timestamp can be
later than the original session start. Filename dates are local-time strings;
JSON examples use UTC Z. Later records provide activity timestamps; there is
no universal ended field in the metadata header.

Actual human prompts have two observed event representations:

- Legacy: `type=event_msg`, `payload.type=user_message`.
- Paginated: `type=event_msg`, `payload.type=item_completed`,
  `payload.item.type=UserMessage`, with thread/turn/item identifiers.

Do not add those counts to user-role `response_item` counts. The latter are
alternate representations and include injected context. An old sample had
three user-role response items but one human user-message event. Support both
generations and deduplicate actual prompt events by their identifiers.

### Claude Code

Found 13 top-level session files under:
`~/.claude/projects/<encoded-cwd>/<uuid>.jsonl`.
One actual encoded directory is
`-Users-prakash-singh-Documents-repos-ag-gaurd`. Slash/dot replacement agrees
with the supplied examples. Treat the directory name as a candidate-selection
hint; determine project membership from record metadata. Respect HOME and
CLAUDE_CONFIG_DIR when choosing the session root.

There is no fixed first metadata record. Inspected files began with `ai-title`,
`custom-title`, or `last-prompt`, which can lack cwd and timestamps. Relevant
fields occur on user/assistant/attachment/system records. Representative user
record, with shortened values:

```json
{
  "type": "user",
  "sessionId": "6da831f4-...",
  "cwd": "/Users/.../ag-gaurd",
  "timestamp": "2026-10-05T11:11:39.659Z",
  "uuid": "f17af632-...",
  "parentUuid": "4b7068a3-...",
  "isSidechain": false,
  "message": {"role": "user", "content": "..."}
}
```

Some records also have `isMeta` and `version`. User content can be a string or
text/tool-result blocks. One sample had 280 user records, including 227 tool
results and two meta records; only 51 were candidate human text prompts.
Exclude tool-result, meta, and sidechain records and deduplicate UUIDs for the
spec's two-message skip rule. Some files also contained references to other
session IDs and cwd changes into subdirectories. Match message records to the
primary session identity rather than creating a session for every reference.
Timestamps can be out of line order; derive the activity range from parsed
records rather than assuming the first and last line are chronological.

## Corrections proposed for approval

1. **Extraction safety (§11.3, §16).** Claude's finite denylist misses other
   built-in tools, subagents, MCP tools, and hooks. Prefer no built-in tools,
   an empty strict MCP configuration, and disabled customization/hooks for
   extraction. Codex's shell sandbox does not isolate arbitrary external MCP
   tools/hooks; disable those too and forbid approval escalation. Validate
   these controls before enabling extraction; retain the pending job if safe
   isolation cannot be established. Avoid Claude `--bare` because it conflicts
   with subscription auth.
2. **Codex empty MCP override does not clear servers.** In a temporary config
   with one dummy server, `codex -c 'mcp_servers={}' mcp list --json` still
   listed it enabled. The explicit override
   `-c 'mcp_servers.ellie.enabled=false'` listed it disabled. Use explicit
   disabling or a verified isolated configuration instead of assuming an
   empty table replaces inherited configuration.
3. **Claude JSON envelope (§11.3).** Schema output is inside
   `structured_output` in a result envelope, not necessarily in `result` or
   at the top level. Check CLI/envelope errors and field presence, then
   validate the inner object. Missing output is not a successful empty capture.
4. **Discovery and counts (§11.2).** Handle both Codex history generations,
   Claude's distributed metadata, and actual human prompt counts. Preserve
   timestamp offsets. Scan candidate Claude directories and verify record cwd
   rather than constructing only one directory from the repo root: sessions
   can start in subdirectories or other clones of the same project.
5. **Codex launcher matching (§11.2).** The newest modified file can belong to
   a concurrent session. Snapshot identities/activity before launch, compare
   after exit, and match cwd plus the run window. Keep ambiguous jobs pending
   instead of capturing a guess. Resumed sessions can have an original start
   time much older than the launcher run.
6. **Cross-agent extraction (§14).** Native session IDs are not portable
   between Codex and Claude. Keep native fork extraction for matching agents.
   For an explicit cross-agent override, propose a fresh ephemeral run of the
   chosen CLI with source-transcript context. Report oversize/unsupported
   histories rather than silently discarding context.
7. **Archive fidelity (§2, §11.6).** Gzip-copy the available raw JSONL exactly.
   Upstream Codex persistence can truncate command/MCP output, so Ellie cannot
   recover everything originally seen by the agent. Paginated forks can also
   reference parent history prefixes: preserve required ancestry or report an
   incomplete archive rather than describing a child delta as a full transcript.

The supplied spec is unchanged. These are compatibility proposals, not
implemented changes.

## Other checks and verification limits

- The exact §13 Codex MCP TOML table, including
  `default_tools_approval_mode = "approve"`, was accepted by real
  `codex mcp get ellie --json` in temporary CODEX_HOME (exit 0). Current
  official config docs list the field. This proves parsing, not live approval
  behavior. No MCP server process was started by this check.
- `codex --strict-config mcp ...` is explicitly unsupported in this version.
  Use the actual MCP get command for fallback-TOML checks.
- Default `python3` is 3.9.6, below the project minimum. Versioned Python
  3.11/3.12/3.13/3.14 and uv are available. Use a supported interpreter for
  implementation and provision an isolated Python 3.10 for compatibility tests.
- Live authenticated fork/no-history behavior, server-side schema strictness,
  and actual MCP approval prompts were not exercised. Help and canned JSON
  cannot establish those results. They remain explicit isolated integration
  checks. No real login state was accessed to run them. Official Codex source
  supports its ephemeral-persistence guarantee, and Claude documents its
  no-persistence flag; local end-to-end results remain pending.

## Primary references

Installed help and local metadata are the primary evidence above. Current
upstream sources were consulted for behavior beyond the help output:

- [Codex CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
- [Codex persistence policy](https://github.com/openai/codex/blob/main/codex-rs/rollout/src/policy.rs)
- [Codex session persistence](https://github.com/openai/codex/blob/main/codex-rs/core/src/session/session.rs)
- [Codex protocol and ancestry](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs)
- [Claude CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Claude structured-output envelope](https://code.claude.com/docs/en/headless#get-structured-output)
- [Claude hook controls](https://code.claude.com/docs/en/hooks)
