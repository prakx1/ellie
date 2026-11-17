# Ellie 🐘: project memory for coding agents (v1 spec)

> *Elephants never forget. Now your agent doesn't either.*

> Package: `ellie` (PyPI) · CLI: `ellie` · Language: Python ≥ 3.10, standard library only
> Agents supported: Codex CLI, Claude Code · Storage: local markdown files · No API keys

---

## 1. Summary

Coding agents do a lot of valuable work: they set goals, make decisions, weigh tradeoffs, try
things that fail, and discover how a codebase actually behaves. Today that knowledge disappears
when a session ends, and it gets carried forward by hand through handoff files.

**Ellie makes every agent session part of a project's permanent, searchable memory, and lets you
bring the relevant parts into the next session before work starts.**

It does three things:

1. **Captures** goals, decisions (with options and tradeoffs), results (including failures),
   findings and open questions. Live capture happens through MCP tools during a session, and an
   automatic pass runs after each session, so nothing is lost.
2. **Organises** them per repo: one shared project memory plus any number of named workstream
   memories (`auth-refactor`, `billing-bug`, …), stored as readable markdown outside the repo.
3. **Briefs** the agent at the start of new work: the user picks memories and searches past items
   ("rate limiting"), selects what is relevant, and the agent starts with that context.

---

## 2. Goals and non-goals

### v1 goals
- One-command install, then `ellie install` to wire up Codex CLI and Claude Code.
- Fully local. Plain markdown is the source of truth; a local SQLite index for search can be
  rebuilt at any time.
- Several named memories per repo, selectable when a conversation starts and switchable mid-session.
- The agent writes memory live through MCP tools.
- An automatic post-session extraction pass using the user's **Codex or Claude subscription
  through their CLIs**, never an API key.
- Full transcripts of sessions are archived per project (nothing is lost).
- Search (`recall`) across all items in a project, plus briefings at start.
- Import existing handoff files; backfill memory from past sessions.

### Non-goals for v1 (keep the design ready for them)
- Cloud storage, cross-device sync, team sharing (v2)
- Semantic or embedding search (v1.1+, local only)
- GUI or web dashboard (v1.1+)
- Lifecycle hooks for sessions started without the launcher (v1.1)
- Codex Cloud, IDE extensions

---

## 3. Concepts

| Term | Meaning |
|---|---|
| **Project** | One repository. Identified by its normalised git remote (§5). |
| **Project memory** | `project.md`: repo-wide overview, conventions, decisions and findings. Always loaded. |
| **Workstream memory** | A named memory for one line of work (feature, bug, refactor). A repo has 0..n. |
| **Item** | One unit of knowledge with an ID: Decision `D`, Result `R`, Finding `F`, Question `Q`, Note `N`. |
| **Goal** | What a workstream is trying to achieve, plus what "done" means. One per memory (a section, not an item). |
| **State** | *Current state* + *Next steps*. Overwritten at each handoff. |
| **Log** | Append-only timeline of events in a memory. |
| **Session** | One run of Codex or Claude Code in a repo. Archived and linked to items it produced. |
| **Capture** | Turning a finished session into items, via the agent's headless mode. |
| **Briefing** | The context assembled at start from chosen memories and chosen items. |

---

## 4. Storage

### 4.1 Layout

Root: `~/.ellie/` (override with env `ELLIE_HOME`).

```
~/.ellie/
  extraction.md                     # editable guidance for the capture pass (§11.4)
  projects/
    github.com/you/app/             # project id path (§5)
      project.md                    # shared project memory
      memories/
        auth-refactor.md
        billing-bug.md
      archive/                      # archived workstream memories
      sessions/
        index.json                  # session registry for this project (§4.6)
        2026-11-17_codex_019a3f….jsonl.gz     # archived raw transcript
  .local/                           # per-device; never synced (future sync excludes it)
    config.json
    state.json                      # last-used memories per project, pending captures
    paths.json                      # manual folder → project id links
    index.db                        # SQLite FTS index (rebuildable)
    pending/                        # capture jobs (§11)
    logs/                           # background capture logs
```

### 4.2 Workstream memory file

```markdown
---
name: auth-refactor
description: Move auth to OAuth2 + PKCE
status: active
created: 2026-11-15 14:02
updated: 2026-11-17 23:30
updated_by: codex
---

## Goal
Move login from server sessions to OAuth2 + PKCE.

**Done when:** all clients use PKCE, legacy /login removed, session table dropped.

## Current state
- PKCE flow + refresh endpoint working
- Legacy /login still live for mobile app v3

## Next steps
1. Migrate existing sessions
2. Remove /login after mobile v4 ships

## Decisions

### D1 · Use authlib instead of a custom implementation
- date: 2026-11-15
- status: active
- source: codex · live
- options: authlib · python-jose + custom · Auth0
- chosen: authlib
- tradeoff: less control over token format, but no security code to maintain ourselves
- why: PKCE + refresh built in, actively maintained
- refs: src/auth/oauth.py

## Results

### R1 · Silent refresh in a hidden iframe
- date: 2026-11-16
- outcome: failed
- source: claude-code · auto · session 7c1e…
- what: refresh tokens via hidden iframe to avoid redirects
- evidence: blocked by Safari ITP; works in Chrome only
- refs: commit 4f2a91c

## Findings

### F1 · API gateway strips X-Forwarded-For
- date: 2026-11-16
- scope: project
- source: codex · live
- detail: use X-Real-IP for client IP behind the gateway
- evidence: request dump in staging

## Open questions

### Q1 · Do internal services bypass rate limits?
- date: 2026-11-16
- status: open

## Notes

## Log
- 2026-11-15 14:02 · codex · goal: Started auth refactor
- 2026-11-15 15:40 · codex · decision: D1 Use authlib
- 2026-11-16 11:10 · claude-code · result: R1 failed (silent refresh, Safari ITP)
- 2026-11-17 23:30 · codex · handoff: refresh endpoint done, 14/14 tests green · session 019a3f…
```

### 4.3 project.md

Same format, with `name: project`, plus these sections in order:
`Overview`, `Conventions`, `Decisions`, `Findings`, `Open questions`, `Notes`, `Log`.
It has no Goal or State. Items here have project scope.

### 4.4 Item grammar (the parser must handle exactly this; tolerate extra whitespace)

```
### <ID> · <title>              ← ID = [DRFQN]\d+, separator " · " (also accept " - " and ": ")
- <key>: <value>                ← one per line; unknown keys preserved verbatim
<free text lines>               ← optional; preserved verbatim
```

Fields per type (all items have `date`, `source`, optional `refs`):

| Type | Required | Optional |
|---|---|---|
| Decision `D` | `status` (`active` \| `superseded by Dn` \| `reverted`), `chosen`, `why` | `options`, `tradeoff`, `supersedes` |
| Result `R` | `outcome` (`worked` \| `failed` \| `partial`), `what` | `evidence` |
| Finding `F` | `detail`, `scope` (`workstream` \| `project`) | `evidence` |
| Question `Q` | `status` (`open` \| `resolved`) | `answer` |
| Note `N` | (body text) | |

`source` format: `<agent> · <live|auto|manual|import|backfill>[ · session <id>]`.

**IDs** are unique per project across all its memories (so `D7` means one thing in a repo), assigned
as `max(existing ID of that type in the project) + 1` by scanning the index (fallback: scan files).
IDs are never reused, including after archiving. A cross-repo reference is `<project-id>:<ID>`.

**Superseding:** a new decision with `supersedes: D3` sets D3's status to `superseded by D9`. A
superseded item is never deleted.

**Log line:** `- YYYY-MM-DD HH:MM · <agent|you> · <kind>: <text>[ · session <id>]`, where kind is one of
`goal|decision|result|finding|question|note|progress|issue|handoff|import`.

Write files with `\n` line endings and UTF-8. Rendering a parsed file must reproduce it byte-for-byte
when nothing changed (round-trip test).

### 4.5 Frontmatter
Simple `key: value` lines between `---` markers (no YAML dependency). Unknown keys are preserved. On
duplicate keys the last one wins, and the next save normalises the file.

### 4.6 Sessions registry: `sessions/index.json`

```json
{
  "019a3f…": {
    "agent": "codex",
    "started": "2026-11-17T22:10:00+05:30",
    "ended": "2026-11-17T23:31:12+05:30",
    "cwd": "/Users/me/code/app",
    "memories": ["auth-refactor"],
    "launched_by": "ellie",          // or "external" (found later)
    "capture": "done",              // pending | running | done | skipped | failed
    "items": ["D2", "R3", "F1"],
    "archive": "2026-11-17_codex_019a3f….jsonl.gz"
  }
}
```

### 4.7 Storage interface (needed for v2 cloud)

All file I/O goes through one interface. v1 ships `FileStore`; v2 adds other backends without CLI or
MCP changes.

```python
class Store(Protocol):
    def list_projects(self) -> list[str]: ...
    def list_memories(self, project: str, archived: bool = False) -> list[MemoryMeta]: ...
    def read_memory(self, project: str, name: str) -> Memory: ...
    def write_memory(self, project: str, memory: Memory) -> None: ...   # atomic + locked
    def move_memory(self, project: str, name: str, to_archive: bool) -> None: ...
    def read_sessions(self, project: str) -> dict: ...
    def write_sessions(self, project: str, data: dict) -> None: ...
    def archive_transcript(self, project: str, src: Path, name: str) -> str: ...
```

---

## 5. Project identification

1. Resolve the repo root: `git rev-parse --show-toplevel` from cwd (fallback: cwd itself).
2. If `.local/paths.json` maps that root → id, use it (`ellie link`).
3. Else read `git remote get-url origin` and normalise it: strip scheme, `user@`, port, `.git`; turn
   the scp form `host:path` into `host/path`; lowercase.
   `git@github.com:Me/App.git` → `github.com/me/app`.
4. No remote: `local/<folder-name>`.
5. Sanitise each path segment to `[a-z0-9._-]`; reject `.`/`..`.

Sessions in subfolders and in multiple clones or worktrees of the same remote all map to the same project.

---

## 6. CLI

`ellie` with no arguments is `ellie status`. Everything after `--` is passed to the agent unchanged
(split `argv` before argparse; do not use `argparse.REMAINDER`).

| Command | Behaviour |
|---|---|
| `ellie status` | Project id, repo root, memories (name, description, last updated + by whom, `*` = last used), count of archived memories, count of **uncaptured sessions** with a hint to run `ellie capture`. |
| `ellie start [codex\|claude] [opts] [-- agent args]` | §7. Default agent from config. |
| `ellie brief "<task>"` | Run the briefing selector (§8) and print the briefing; don't launch. `--json` for scripts. |
| `ellie recall <query> [--type D,R,F,Q,N] [--all-projects] [--include-superseded] [-n 10]` | Ranked search (§10). |
| `ellie show [NAME\|ID]` | Print a memory, or one item by ID. Default: `project.md`. |
| `ellie new NAME [-d DESC] [--goal TEXT --done-when TEXT]` | Create a workstream memory. |
| `ellie edit [NAME]` | Open in `$VISUAL`/`$EDITOR` (fallback `vi`, or `notepad` on Windows). Reindex after. |
| `ellie log NAME "text" [-k progress\|issue\|note]` | Manual log entry (`you`). |
| `ellie archive NAME` / `ellie restore NAME` | Move between `memories/` and `archive/`. |
| `ellie import FILE --as NAME [-d DESC]` | Create a memory from a handoff file (§12.1). |
| `ellie capture [--wait] [--session ID] [--since 7d] [--dry-run]` | Process pending and uncaptured sessions for this repo (§11). |
| `ellie backfill [--since 30d] [--limit N] [--agent codex\|claude] [--yes]` | Capture past sessions for this repo (§12.2). |
| `ellie projects` | All projects with memory counts. |
| `ellie link PROJECT_ID` | Map the current folder to an existing project id. |
| `ellie install [--codex] [--claude]` / `ellie uninstall` | §13. |
| `ellie config [KEY [VALUE]]` | §14. |
| `ellie reindex` | Rebuild `.local/index.db` from files. |
| `ellie doctor` | Check: python version, git, codex/claude on PATH and logged in (`codex login status`, `claude` presence), MCP registered for each, instruction blocks present, SQLite FTS5 available, write access to the store. Print fixes. |
| `ellie where` | Print the store path. |
| `ellie mcp` | Run the MCP server on stdio (used by the agents). |

Errors print `ellie: <message>` to stderr and exit 1. Handle `BrokenPipeError` quietly (`ellie | head`).

---

## 7. Starting a session: `ellie start`

### 7.1 Options
```
ellie start [codex|claude]
  -m, --memory NAME        load memory (repeatable); skips the memory picker
  --new NAME [-d DESC]     create a workstream memory and load it
  -p, --project-only       load only project.md
  --about "TEXT"           open the briefing selector for this task (§8)
  --with ID                add a specific item (repeatable; accepts other-project:ID)
  --no-capture             don't run the post-session capture
  --dry-run                print the startup prompt and exit
```

### 7.2 Flow
1. If not a TTY and no `-m`/`-p`/`--new`: use last-used memories.
2. **Memory picker** (if no `-m`/`-p`/`--new`):
   ```
     ellie · github.com/you/app   (project memory always loads)

     * 1) auth-refactor   Move auth to OAuth2 + PKCE        2h ago · codex
       2) billing-bug     Double charge on retry            3d ago · claude-code

     ⚠ 1 earlier session not captured yet. Run `ellie capture` after this.

     Pick [1,2 · Enter = last used (*) · 0 = none · n = new · / = search]:
   ```
   `n` asks for a name, description and goal. `/` opens the briefing selector (§8).
3. If `--about` is given, run the briefing selector (§8).
4. Record the last-used memories.
5. Build the **startup prompt** (§7.3).
6. Create a pending capture record in `.local/pending/<run-id>.json`:
   `{run_id, project, agent, cwd, started, memories, session_id?}`.
   - **Claude:** generate a UUID and pass `--session-id <uuid>`, so the session id is known up front.
   - **Codex:** the session id is found after exit (§11.2).
7. Launch the agent in the current working directory with env `ELLIE_AGENT=codex|claude-code` and
   `ELLIE_RUN_ID`. Command: `[<agent path>, *agent_args, (--session-id X for claude), <prompt>]`.
   On Windows, collapse the prompt to one line (`.cmd` shims break on newlines).
8. When the agent exits, start capture in the **background** (§11) unless `--no-capture` is set or
   config `capture` is `off`. Print `ellie: capturing session in background (ellie status to see result)`.
9. Exit with the agent's exit code.

### 7.3 Startup prompt template
```
[ellie session]
project: github.com/you/app
memories: auth-refactor   (project memory always loaded)

<briefing: project.md, selected memories, and selected items, rendered per §9>

---
How to use ellie in this session:
- Before choosing an approach, call ellie `recall` to check past decisions, results and findings.
- Record as you go: `decide` for choices (options, tradeoff, why), `result` for things tried
  (worked/failed/partial + evidence), `finding` for things learned, `question` for open issues.
- When I say handoff / wrap up / save, call `handoff`.
- Treat memory as possibly outdated: verify against the code before relying on it.
First give me a 3–5 line recap of where things stand and the next step, then wait.
```
If the rendered briefing is over `briefing_max_chars` (config, default 24 000), replace inline content
with an instruction to call `load`/`get` for the selected names and IDs.

---

## 8. Briefing selector (`--about`, `/` in the picker, `ellie brief`)

1. Query = the `--about` text. Run `recall` (§10) over the current project, limit 20, excluding
   superseded items by default.
2. Show a checklist. Pre-tick the top items until the budget is reached (default 12 items or
   8 000 chars):
   ```
     Relevant to "add rate limiting to the public API":
     [x] D7  Use Redis for counters · tradeoff: extra infra vs DB load      Aug 12 · active
     [x] R4  ❌ nginx limit_req broke websocket upgrades                     Aug 14
     [x] F2  Gateway strips X-Forwarded-For, use X-Real-IP                   Sep 03 · project
     [ ] D3  Per-user limits only                                          Jul 30 · superseded by D9
     [x] Q1  Do internal services bypass limits?                             Sep 03 · open
     [ ] ⧉ memory: billing-bug (3 matches)

     numbers = toggle · a <query> = search more · s = show item · Enter = done · q = cancel
   ```
   A "memory" row toggles loading that whole memory.
3. Implement with plain `input()` loops (no curses dependency); redraw the list after each command.
4. Output: selected memories plus selected item IDs, which go into the startup prompt.

---

## 9. Rendering memory for the agent

Order for each memory: Goal → Current state → Next steps → **active** Decisions → Results (most recent
10) → Findings → **open** Questions → last `log_limit` (default 25) Log lines.
Superseded decisions, resolved questions and older log lines are left out of the context but stay in
the file. Skip placeholder-only sections. Selected individual items are rendered under
`## Selected from project history` with their ID, title, all fields, and memory name.

---

## 10. Search: index and `recall`

- SQLite at `.local/index.db`, table `items` (FTS5 virtual table if available, else a regular table
  with `LIKE` fallback). Columns: `project, memory, id, type, title, body, date, status, outcome, scope`.
- Kept up to date by every write path (live tools, capture, CLI). On startup, if any memory file's
  mtime is newer than the index's recorded mtime, reindex that file. `ellie reindex` rebuilds all.
- **Ranking:** `score = bm25_relevance × recency × type_weight`
  - `recency = 0.5 ** (age_days / 120)`, floored at 0.25
  - type_weight: failed/partial result 1.3 · active decision 1.2 · finding 1.2 · open question 1.1 ·
    worked result 1.0 · note 0.8 · superseded/reverted 0.3 · resolved question 0.5
- Results: `id, type, title, date, status/outcome, memory, one-line snippet`.

---

## 11. Capture (post-session extraction)

### 11.1 When it runs
- Automatically, in the background, after `ellie start` sessions (config `capture`: `auto` default,
  `ask`, `off`).
- `ellie capture` processes: pending records, plus **uncaptured external sessions** for this repo
  (sessions started with plain `codex`/`claude`, found through §11.2) since `--since` (default 7d).
- `ellie start` and `ellie status` show the count of uncaptured sessions.

### 11.2 Finding sessions (adapter per agent; isolate in `agents/<name>.py`)
- **Claude Code:** session files live in `~/.claude/projects/<cwd with / and . replaced by ->/<uuid>.jsonl`.
  The id is known for launcher runs. For discovery, list that folder for the repo root (and its subfolders).
- **Codex:** `~/.codex/sessions/YYYY/MM/DD/rollout-*-<uuid>.jsonl` (respect `CODEX_HOME`). The first
  record holds session metadata including `cwd`. Discover by scanning files modified after
  `started`, whose cwd is inside the repo root; the newest one is the launcher's session.
- File formats belong to the agents and may change. Parse defensively, read only metadata (id,
  cwd, timestamps, count of user messages), and if parsing fails, report it in `ellie doctor` and
  continue. **Verify both formats against the installed versions during implementation.**
- Skip sessions with fewer than 2 user messages (mark `skipped`).

### 11.3 Running the extraction (subscription only, through the agent's own CLI)
The extraction **forks the finished session** so the model has its full context. No transcript
parsing or API key is needed. Run the same agent that ran the session, unless config `extract_with`
is set.

**Codex**
```
codex exec fork <SESSION_ID> \
  --ephemeral \
  -c sandbox_mode="read-only" \
  --output-schema <tmp>/schema.json \
  -o <tmp>/out.json \
  "<extraction prompt>"
```
**Claude Code**
```
claude -p --resume <SESSION_ID> --fork-session --no-session-persistence \
  --output-format json --json-schema '<schema json>' \
  --disallowedTools "Bash Edit Write NotebookEdit WebFetch WebSearch" \
  "<extraction prompt>"
```
- Timeout: `extract_timeout_sec` (default 600). Kill the process on timeout and mark it `failed`.
- The forked run must not add to the user's session history (Codex `--ephemeral`, Claude
  `--no-session-persistence`). Verify this during implementation.
- Python validates the JSON against the schema. If it's invalid, retry once with the validation error
  appended to the prompt, then mark `failed`. Keep the pending record so `ellie capture` can retry.
- Check exact flag names against `codex exec fork --help` and `claude --help` at implementation time.

### 11.4 Extraction prompt
Assembled from:
1. The contents of `~/.ellie/extraction.md` (created at install from the default below; the
   user can edit it).
2. Context: project id, memories that were loaded, and for each a list of existing item IDs + titles +
   status (so the model can supersede, resolve and avoid duplicates), plus current Goal/State.
3. "Return only JSON matching the schema."

**Default `extraction.md`**
```markdown
You are reviewing the coding session above to update the project's long-term memory.
Use your judgment. Save what a future session on this project would want to know; skip the rest.

Types:
- goal: what this work is trying to achieve and what "done" means (only if new or changed)
- decision: a choice between options that shapes future work. Give the options, what was chosen,
  the tradeoff, and why. If it replaces an earlier decision, list that ID in `supersedes`.
- result: something was tried and the outcome is known: worked, failed or partial, with evidence
  (test output, error, metric, commit). Failed attempts matter: they stop others repeating them.
- finding: something learned about the code, system or tools that stays true regardless of what we
  decided (gotchas, how something really works). Set scope to "project" if it applies repo-wide.
- question: something unresolved that matters later. Resolve existing questions if answered.
- note: anything clearly worth keeping that fits nothing above. Use sparingly.

Rules:
- Don't duplicate items that already exist (listed below). Update via supersede/resolve instead.
- Skip trivia: routine edits, things obvious from reading the code, anything findable in seconds.
- Point to code (file paths, commits, PRs) instead of pasting it.
- Never include secrets, tokens, passwords or personal data.
- If nothing worth keeping happened, set worthwhile=false and leave the lists empty.
- Write the state as a handoff: where things stand, and concrete ordered next steps.
```

### 11.5 Output schema (must work with strict structured output: every object has
`additionalProperties: false` and **all** properties required; use `null` / empty arrays for
"none"; nullable fields use `["string","null"]`)
```json
{
  "worthwhile": true,
  "target_memory": {"existing": "auth-refactor", "new_name": null, "new_description": null},
  "goal": {"text": "…", "done_when": "…"},
  "decisions": [{"title": "", "options": [""], "chosen": "", "tradeoff": "", "why": "",
                 "supersedes": ["D3"], "refs": [""], "memory": null}],
  "results":   [{"title": "", "outcome": "worked|failed|partial", "what": "", "evidence": "",
                 "refs": [""], "memory": null}],
  "findings":  [{"title": "", "detail": "", "evidence": "", "scope": "workstream|project",
                 "memory": null}],
  "questions": [{"text": "", "memory": null}],
  "resolved_questions": [{"id": "Q1", "answer": ""}],
  "notes":     [{"text": "", "memory": null}],
  "state":     {"current_state": "", "next_steps": ""},
  "session_summary": "one or two sentences"
}
```
`goal`, `state` and `target_memory.new_*` may be `null`. The per-item `memory: null` means "the target
memory". `target_memory.existing: null` + `new_name` set means "create a new workstream memory"
(only allowed when the session had no memory loaded; otherwise ignore it and use the first loaded memory).
If no memory was loaded and the model proposes none, write to `project.md` (findings/decisions only;
drop state).

### 11.6 Merging
1. Lock the affected files (§15).
2. Assign IDs (§4.4). Write items with `source: <agent> · auto · session <id>`.
3. Apply `supersedes` → update the old decision's status. Apply `resolved_questions`.
4. `scope: project` findings go to `project.md`.
5. **State:** if a live `handoff` happened during the session (the memory's `updated` time is after the
   session start and a handoff log line exists for this session), keep the live state. Otherwise
   write the extracted state.
6. Goal: set if the memory has none, or if `goal` differs (log the change as `goal:`).
7. Log: one line per new item, plus `handoff:` with `session_summary` and the session id.
8. Dedupe: skip an item whose normalised title matches an existing item of the same type in the same
   memory (lowercase, collapse whitespace, strip punctuation).
9. Archive the transcript: gzip-copy the session file to `sessions/` (§4.1) and update `index.json`
   (`capture: done`, `items: [...]`).
10. Reindex the touched files. Write a one-line summary to `.local/state.json` for display on the
    next `ellie` command: `Captured auth-refactor: 2 decisions, 1 failed result, 1 finding.`

---

## 12. Bringing in existing work

### 12.1 `ellie import FILE --as NAME`
Create the memory. Put the file contents under **Current state** with the header
`_Imported from <file> on <date>. The next handoff or capture will reorganise this._`, set the description
from the first non-empty line, and log `import:`.

### 12.2 `ellie backfill`
1. Discover past sessions for this repo (§11.2) in the time window, excluding ones already captured.
2. Show a list (date, agent, user-message count, first user message trimmed to 60 chars), an
   estimate ("N extraction runs on your codex/claude plan"), and ask for confirmation (skip with `--yes`).
3. Process oldest → newest (so supersedes work), one at a time, using §11.3–11.6 with
   `source: … · backfill`.
4. Ask which memory each session belongs to only when it's ambiguous. Default: let the model propose
   (`target_memory`), creating new memories when needed.

### 12.3 Current conversation
No special code: the user restarts with `codex resume` / `claude --resume`, so the MCP tools load,
and asks the agent to "create a memory for this and do a handoff". The capture pass also covers it.

---

## 13. Install and agent integration: `ellie install`

Default: Codex always, plus Claude Code if `claude` is on PATH or `~/.claude` exists.

**Codex**
1. If `codex` is on PATH: `codex mcp remove ellie` (ignore errors), then
   `codex mcp add ellie -- <sys.executable> -m ellie mcp`.
   Otherwise, or if that fails, append to `$CODEX_HOME/config.toml` (default `~/.codex`):
   ```toml
   [mcp_servers.ellie]
   command = "<sys.executable>"
   args = ["-m", "ellie", "mcp"]
   default_tools_approval_mode = "approve"
   ```
2. Ensure `default_tools_approval_mode = "approve"` exists in `[mcp_servers.ellie]` (insert after the
   header if missing), so memory writes don't prompt every time.
3. Upsert the instruction block (§13.1) in `$CODEX_HOME/AGENTS.md`.

**Claude Code**
1. `claude mcp remove --scope user ellie` (ignore errors), then
   `claude mcp add --scope user ellie -- <sys.executable> -m ellie mcp`.
2. Upsert the instruction block in `~/.claude/CLAUDE.md`.
3. Print the tip: add `"mcp__ellie"` to `permissions.allow` in `~/.claude/settings.json` to skip approval prompts.

Use the absolute interpreter path (`sys.executable`), because MCP clients may not have the user's PATH.
Create `~/.ellie/extraction.md` if missing. Before the first modification of any user file, save
`<file>.ellie-backup`. Running install twice must not duplicate anything.

**`ellie uninstall`:** `codex mcp remove ellie` (or strip the `[mcp_servers.ellie]` table and its sub-tables
line by line: never use a regex that stops at `[`, because arrays contain `[`), `claude mcp remove --scope user ellie`,
remove the instruction blocks. Never touch memory files.

### 13.1 Instruction block (between markers `<!-- ellie:begin -->` / `<!-- ellie:end -->`)
```markdown
## Project memory (ellie)
A `ellie` MCP server holds this repo's long-term memory: goals, decisions, results, findings,
open questions, shared across sessions and agents (Codex and Claude Code).
- If the conversation starts with a `[ellie session]` block, that memory is loaded.
- Otherwise, at the start of work in a repo, call ellie `status` with cwd=<repo path>. If memories
  exist, ask me which to load (or none / new), then call `load`.
- Before choosing an approach, call `recall` to check what was decided, tried or learned before.
- As you work: `decide` for choices (options, tradeoff, why), `result` for things tried
  (worked/failed/partial with evidence), `finding` for things learned, `question` for open issues.
  Skip trivia. Repo-wide facts go to memory="project".
- When I say handoff / wrap up / save, call `handoff`.
- Memory may be outdated: verify against the code before relying on it.
- Never store secrets.
```

---

## 14. Config (`.local/config.json`, per device)

| Key | Default | Meaning |
|---|---|---|
| `agent` | `codex` | Default agent for `ellie start` |
| `capture` | `auto` | `auto` \| `ask` (prompt after exit) \| `off` |
| `extract_with` | `same` | `same` \| `codex` \| `claude` |
| `extract_timeout_sec` | `600` | Capture timeout |
| `log_limit` | `25` | Log lines included when loading |
| `briefing_max_chars` | `24000` | Above this, the agent loads via tools instead of inline |
| `brief_preselect` | `12` | Items pre-ticked in the selector |
| `backfill_default_since` | `30d` | Default window |

---

## 15. MCP server

- stdio, newline-delimited JSON-RPC 2.0, **stdlib only**. Handle: `initialize` (echo the client's
  `protocolVersion`; capabilities `{tools:{}}`; `serverInfo {name:"ellie"}`; `instructions` = the
  short usage text), `notifications/*` (no reply), `ping`, `tools/list`, `tools/call`, and empty
  `resources/list` / `prompts/list`. Unknown method → error `-32601`. Never crash on a bad call:
  return `isError: true` with a message.
- Agent name: env `ELLIE_AGENT`, else from `clientInfo.name` (`codex` if it contains "codex",
  `claude-code` if it contains "claude").
- Every tool accepts optional `project` (id) and `cwd` (path). Resolve with `project` first, then
  `cwd`, then the server's cwd.

### 15.1 Tools

| Tool | Input | Behaviour |
|---|---|---|
| `status` | — | Project id, memories (name, description, updated), last used, uncaptured session count |
| `load` | `memories: string[]` | Render project.md + named memories (§9); set last-used |
| `get` | `ids: string[]` | Full items by ID (supports `project:ID`) |
| `recall` | `query`, `types?`, `limit? (8)`, `include_superseded? (false)`, `all_projects? (false)` | §10 |
| `create` | `name`, `description`, `goal?`, `done_when?` | New workstream memory |
| `set_goal` | `memory`, `goal`, `done_when` | Set or replace the goal; log it |
| `decide` | `memory`, `title`, `options[]`, `chosen`, `tradeoff`, `why`, `supersedes?[]`, `refs?[]` | New Decision; apply supersedes; returns its ID |
| `result` | `memory`, `title`, `outcome`, `what`, `evidence`, `refs?[]` | New Result; returns its ID |
| `finding` | `memory`, `title`, `detail`, `evidence?`, `scope (workstream\|project)` | New Finding (project scope → project.md) |
| `question` | `memory`, `text` | New open Question |
| `resolve` | `id`, `answer` | Resolve a Question |
| `log` | `memory`, `entry`, `kind (progress\|issue\|note)` | Log line only |
| `update` | `memory`, `section`, `content` | Replace Summary-like sections: Goal, Current state, Next steps, Overview, Conventions. Refuses Log and item sections. |
| `handoff` | `memory`, `current_state`, `next_steps`, `session_summary` | Replace state; log `handoff:` with the session id if known (`ELLIE_RUN_ID` → pending record) |

Tool descriptions matter: the model decides when to call based on them. Keep each one or two
sentences, saying *when* to use it. Live items get `source: <agent> · live`.

Retry safety: if an identical item (same type and normalised title) was added to the same memory in
the last 10 minutes, return the existing ID instead of creating a duplicate.

---

## 16. Concurrency and safety

- Every write: take a lock file `<file>.lock` (`O_CREAT|O_EXCL`; retry for 10 s; break locks older
  than 60 s) → read → modify → write a temp file in the same folder → `os.replace` → unlock.
- `index.db`: SQLite with WAL; a short busy timeout; writers retry.
- Background capture: one process per pending record; a lock prevents capturing the same session twice.
- Secrets: the instructions and the extraction prompt forbid them. Additionally, before writing any
  item, scan for common secret patterns (AWS keys, `sk-…`, `ghp_…`, `-----BEGIN … PRIVATE KEY-----`,
  `password=…`) and replace matches with `[redacted]`.
- Never modify the user's repo. The extraction run is read-only (sandbox / disallowed tools).

---

## 17. Package layout

```
ellie/
  pyproject.toml            # [project.scripts] ellie = "ellie.cli:main"; no dependencies
  README.md
  src/ellie/
    __init__.py  __main__.py
    cli.py                  # argparse, commands
    paths.py                # store root, project id resolution
    model.py                # Memory / Item parse + render (grammar §4.4)
    store.py                # Store protocol + FileStore (locking, atomic writes)
    index.py                # SQLite FTS index + ranking
    briefing.py             # selector UI + rendering (§8, §9)
    launch.py               # ellie start
    capture.py              # pending jobs, merge logic (§11.6)
    extract.py              # running headless agents, schema, validation
    agents/codex.py         # session discovery, fork command
    agents/claude.py
    mcp_server.py           # JSON-RPC + tools
    install.py              # §13
    redact.py               # secret patterns
    resources/extraction.md # default guidance
    resources/schema.json   # extraction schema
  tests/
```

---

## 18. Testing

Use `unittest` (stdlib). Tests must not need a real Codex or Claude login.

- **Model:** parse → render round-trips byte-for-byte; hand-edited files with extra keys or text survive; IDs are
  unique across memories; supersede and resolve work.
- **Project id:** remote normalisation (ssh, https with token, `ssh://host:port`), subfolders, `link`.
- **Index/recall:** ranking order (failed result above old note), superseded items excluded by default, LIKE fallback.
- **MCP:** stdio round-trip in a subprocess (initialize → notification → tools/list → each tool);
  errors return `isError`; retried calls don't duplicate. Optional dev test using the official `mcp` SDK
  client to confirm compatibility.
- **Capture:** fake `codex`/`claude` scripts on PATH that print canned JSON (valid, invalid-then-valid,
  invalid twice, timeout). Check the merge rules (§11.6), live handoff preserved, transcript archived,
  pending kept on failure.
- **Session discovery:** sample Codex/Claude session files in temp `CODEX_HOME` / `HOME`.
- **Install:** temp `HOME`/`CODEX_HOME`; idempotent; uninstall leaves other MCP servers and user text intact;
  the TOML fallback is parsed correctly by a real `codex mcp get ellie` when available (skip otherwise).
- **CLI:** `--` passthrough, picker via scripted stdin on a pseudo-TTY, BrokenPipe.
- Run on Python 3.10 and the latest version.

---

## 19. Acceptance criteria (v1 is done when)

1. Fresh machine: `uv tool install ellie && ellie install` → first `ellie start` in under 2 minutes.
2. Start in Codex with `auth-refactor`, make a decision and a failed attempt, exit **without** saying
   handoff → within a few minutes `ellie status` shows "Captured auth-refactor: 1 decision, 1 failed result",
   and the file contains them with options, tradeoff and evidence.
3. `ellie start claude -m auth-refactor` → Claude's recap reflects the Codex session's state and next steps.
4. A week later: `ellie start --about "token refresh"` pre-ticks the failed iframe attempt and the authlib
   decision; the agent starts informed.
5. A session started with plain `codex` (no launcher) is listed as uncaptured, and `ellie capture` captures it.
6. `ellie backfill --since 30d` turns past sessions into items after confirmation.
7. `ellie import HANDOFF.md --as payments` works; two memories in one repo stay separate.
8. No API key is used anywhere; extraction runs only through `codex exec` / `claude -p`.
9. `ellie uninstall` leaves the user's other config untouched and the memory files intact.

---

## 20. Later versions (don't build now, don't block them)

- **v1.1:** lifecycle hooks (Claude Code SessionEnd / Codex hooks → `ellie capture`) so sessions without the
  launcher are captured automatically; `ellie compact` (summarise old log lines); agent proactively
  suggests items at start; local web dashboard `ellie ui` (decisions with tradeoffs, results board,
  timeline); optional local embeddings (fastembed) for search by meaning.
- **v2:** git sync of `~/.ellie` (exclude `.local/`; `*.md merge=union`; renumber colliding IDs);
  then a cloud `Store` backend and a hosted dashboard; team-shared project memory.

---

## 21. Things to verify during implementation

- Exact headless flags: `codex exec fork --help`, `claude --help` (`--fork-session`,
  `--no-session-persistence`, `--json-schema`, `--session-id`, `--disallowedTools`).
- Codex and Claude session file locations and the metadata record format in the installed versions.
- That forked or ephemeral extraction runs don't appear in the user's resume lists.
- Codex `--output-schema` strictness (all properties required, `additionalProperties: false`).
- MCP tool approval behaviour in both agents after `ellie install`.
