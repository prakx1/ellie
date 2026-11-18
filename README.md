# Ellie 🐘

Local project memory for Codex CLI and Claude Code. Keep goals, decisions,
failed attempts, findings, and open questions across sessions and agents.
Markdown is the source of truth; SQLite search is a rebuildable cache.

Ellie requires Python 3.10 or later and has **no runtime dependencies**.
Model calls use your installed `codex exec` or `claude -p` and their existing
CLI login. Ellie never reads credentials or uses an API key. Extraction runs
consume your CLI plan's normal usage.

## Install

From this checkout:

```sh
uv tool install --python 3.10 .
ellie install
ellie doctor
```

Alternatively, install the checkout with `python3.10 -m pip install .`.
Setuptools is only a build dependency. The public PyPI release is a separate
publishing step; this repository does not publish itself.

Install configures Codex and, when detected, Claude Code. Select an agent with
`ellie install --codex` or `ellie install --claude`; both flags may be combined.
It registers a stdio MCP server using an absolute Python interpreter path,
adds a marked instruction block, and creates editable extraction guidance.
Existing files get a one-time `.ellie-backup` before modification. Reinstalling
does not duplicate blocks or overwrite your extraction guidance.

For Claude, the installer prints an optional permissions.allow setting. It
does not grant blanket permissions automatically.

```sh
ellie uninstall
```

Uninstall removes Ellie's MCP registrations and instruction blocks. It keeps
project memories, transcripts, and unrelated agent configuration.

## Quickstart

In a Git repository:

```sh
ellie new auth-refactor -d 'Move auth to PKCE' \
  --goal 'Migrate login to PKCE' --done-when 'Legacy login removed; tests pass'
ellie start codex -m auth-refactor
```

The agent receives shared project memory and the selected workstream. It first
recaps the state and next step, then waits. During work, its MCP tools record
decisions, results, findings, questions, and handoffs.

Exit normally. Unless capture is disabled, Ellie reviews the finished session
in the background even if you did not request a handoff.

```sh
ellie status
ellie start claude -m auth-refactor
ellie start --about 'token refresh'
ellie recall 'iframe refresh'
```

The first status after capture displays its summary. Claude loads the same
memory as Codex. Always verify remembered facts against current code.

## Selecting context

`ellie start` offers a numbered memory picker. Enter uses the starred last
selection, `0` loads only shared memory, `n` creates a workstream, and `/`
searches history. With non-interactive stdin it uses valid last-used memories.

`--about 'task'` opens a history checklist. Numbers toggle rows, `a QUERY`
searches more, `s ID` or `s NUMBER` shows a result, Enter accepts, and `q`
cancels the history selection. Memory rows load the whole workstream.
The initial selection is capped at 12 items and 8000 item characters.

```sh
ellie start -p                         # shared project memory only
ellie start --new billing -d 'Retry bug'
ellie start -m auth-refactor -m billing
ellie start --with R4 --with github.com/you/other:D2
ellie start --about 'rate limits' --dry-run
ellie start codex -m billing -- --model YOUR_MODEL
ellie brief 'rate limits' --json
```

Everything after `--` passes to the agent unchanged. `--dry-run` prints the
startup prompt without launching, saving draft memories, or creating capture
jobs. When selected context exceeds the configured total budget, the prompt
names the `load`/`get` calls the agent should make instead of inlining it.

## Commands

| Command | Purpose |
| --- | --- |
| `ellie` / `ellie status` | Project, memories, last selection, archives, uncaptured sessions |
| `ellie start [codex\|claude]` | Launch with selected context; `--no-capture` disables automatic extraction |
| `ellie brief TASK [--json]` | Select and render relevant history without launching |
| `ellie recall QUERY` | Ranked search; `--type D,R,F,Q,N`, `--all-projects`, `--include-superseded`, `-n N` |
| `ellie show [NAME\|ID]` | Raw memory or complete item; defaults to shared project memory |
| `ellie new NAME [-d TEXT]` | Create a workstream; supports `--goal` and `--done-when` |
| `ellie edit [NAME]` | Edit outside the repo using VISUAL/EDITOR, then reindex |
| `ellie log NAME TEXT [-k progress\|issue\|note]` | Append a manual timeline entry |
| `ellie archive NAME` / `ellie restore NAME` | Archive or restore a workstream; retain its IDs |
| `ellie import FILE --as NAME [-d TEXT]` | Preserve a handoff under Current state for later reorganization |
| `ellie capture [--wait] [--session ID] [--since 7d] [--dry-run]` | Process pending jobs and uncaptured external sessions |
| `ellie backfill [--since 30d] [--limit N] [--agent codex\|claude] [--yes]` | Preview historical sessions, confirm usage, capture oldest first |
| `ellie projects` / `ellie link PROJECT_ID` | List projects or associate a folder with an existing one |
| `ellie config [KEY [VALUE]]` | Read or change per-device settings |
| `ellie reindex` | Rebuild search from memory files |
| `ellie doctor` | Check tools, authentication status, MCP integration, formats, and store health |
| `ellie where` | Print the memory root |
| `ellie install` / `ellie uninstall` | Manage agent integration |
| `ellie mcp` | Run the stdio server; normally started by the agent |

Time windows accept a positive number followed by `h`, `d`, or `w`.
Expected errors use `ellie:` on stderr and exit 1; closed output pipes are quiet.
The launcher returns the agent's exit code.

## How capture works

1. The launcher records a pending run outside the repo. Claude gets a UUID
   up front; Codex is matched after exit using cwd, time, and a before/after
   transcript snapshot. An ambiguous match stays pending.
2. Adapters inspect metadata and count human prompts. Codex's legacy and
   paginated histories are supported. Claude metadata can appear throughout
   the file; tool results, injected context, and subagents are excluded.
3. Available JSONL is gzip-archived. Codex parent-history prefixes are archived
   at their recorded byte boundaries and linked in the session registry.
   The raw archives preserve what the upstream CLI recorded, including any
   existing secrets; item writes separately redact common credential patterns.
4. A headless fork reviews the original conversation. Codex runs ephemeral,
   read-only, with no approval escalation, shell, hooks, plugins, apps, or
   configured MCP servers. Claude uses a nonpersistent fork, safe mode, no
   built-in tools, and an empty strict MCP configuration. Unsupported safety
   flags cause failure rather than an unsafe fallback.
5. Python validates strict structured output and its references. Invalid
   output receives one corrective retry. Timeouts kill the extractor. Failed
   jobs stay pending for `ellie capture --wait`.
6. Merge assigns project-wide IDs, deduplicates titles, applies supersedes and
   resolved answers, routes repo-wide findings to shared memory, and preserves
   live handoff state. Search is updated and a summary is queued.

Native extraction uses the source agent's saved conversation. An explicit
`extract_with` override starts a fresh ephemeral run with archived transcript
context, capped at 2000000 characters. Native session IDs cannot cross agents.

Plain `codex`/`claude` sessions are discovered by status/capture but do not have
automatic exit hooks in v1. Use `ellie capture` or `ellie backfill`. Resumed
sessions become uncaptured again when their source file changes. Sessions with
fewer than two user messages are archived and marked skipped without a model call.

Upstream transcript truncation cannot be undone. Missing Codex parent history
or partially written JSONL is reported; the job remains available for retry.

## Storage and editing

Default root is `~/.ellie`; override it with `ELLIE_HOME`.

```text
projects/<normalized-remote>/
  project.md
  memories/<name>.md
  archive/<name>.md
  sessions/index.json
  sessions/*.jsonl.gz
extraction.md
.local/                 # device config/state/index, jobs, locks and logs
```

SSH/HTTPS remotes for the same repo map to one lowercase project ID. Subfolders,
clones, and worktrees share it. Without a remote, the ID is `local/<folder>`;
use `ellie link` to correct associations when necessary.

Shared memory is always loaded. Workstreams contain Goal, Current state,
Next steps, Decisions, Results, Findings, Open questions, Notes, and Log.
IDs such as D7 are unique across the project's active and archived memories.
Superseded decisions remain in the files and are hidden from ordinary recall.

Hand-editing unknown fields/text is supported. Unchanged parse/render is
byte-exact; explicit saves normalize LF endings and duplicate frontmatter
keys. Writes use locks, temporary files, and atomic replacement. Store roots
inside Git repositories and symlinks within the store are refused. Ellie code
does not edit project repositories or write project instruction files there.

## Configuration

| Key | Default |
| --- | --- |
| `agent` | `codex` (`claude` also supported) |
| `capture` | `auto` (`ask`, `off`) |
| `extract_with` | `same` (`codex`, `claude`) |
| `extract_timeout_sec` | `600` |
| `log_limit` | `25` |
| `briefing_max_chars` | `24000` |
| `brief_preselect` | `12` |
| `backfill_default_since` | `30d` |

```sh
ellie config capture ask
ellie config log_limit 15
ellie config extract_with same
```

Edit `extraction.md` to change capture guidance. It is never overwritten by
reinstall. Codex integration respects `CODEX_HOME`; Claude integration/session
discovery respects `CLAUDE_CONFIG_DIR` as well as HOME.

## Troubleshooting and development

Run `ellie doctor` for missing tools, login/integration problems, changed
session formats, failed captures, or store permissions. Upgrade an agent if
required extraction controls are missing. Check `.local/logs` for background
results, retry with `ellie capture --wait`, and rebuild search with `ellie reindex`.

The verified development CLIs are Codex 0.169.0 and Claude Code 2.1.278.
Automated tests use fake CLI executables and canned JSON; they need no login.
Authenticated no-history behavior, provider schema enforcement, and actual
agent approval prompts remain separate live integration checks. See
[the acceptance report](ACCEPTANCE.md) for their status.

Use an outer temporary home for development, in addition to each test's own
isolated home/store. For example:

```sh
ellie_test_root=$(mktemp -d)
mkdir -p "$ellie_test_root/home" "$ellie_test_root/codex" "$ellie_test_root/store"
env HOME="$ellie_test_root/home" CODEX_HOME="$ellie_test_root/codex" \
  ELLIE_HOME="$ellie_test_root/store" PYTHONPATH=src:. \
  python3.10 -m unittest discover -v
```

The suite is also run on Python 3.14 and 3.15. Runtime imports use only the standard
library. The backend is behind a Store protocol so a future cloud backend can
replace local Markdown persistence without changing CLI/MCP operations.
