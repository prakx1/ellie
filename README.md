# Ellie 🐘

Local project memory for Codex CLI and Claude Code. Keep goals, decisions,
failed attempts, findings, and open questions across sessions and agents.
Markdown is the source of truth; SQLite search is a rebuildable cache.

Ellie requires Python 3.10 or later and has **no runtime dependencies**.
Model calls use your installed `codex exec` or `claude -p` and their existing
CLI login. Ellie never reads credentials or uses an API key. Extraction runs
consume your CLI plan's normal usage.

## Install

You need Git, [uv](https://docs.astral.sh/uv/getting-started/installation/),
Python 3.10 or later, and Codex CLI or Claude Code installed and signed in.
Ellie uses that CLI's existing login; no API key is required.

For a new checkout:

```sh
git clone https://github.com/prakx1/ellie.git
cd ellie
uv tool install --python 3.10 .
ellie install
ellie --version
ellie doctor
```

If you already cloned the repo, run the commands starting with `uv tool install`
from the Ellie checkout.

There are two setup steps: `uv tool install` installs the `ellie` executable;
`ellie install` configures the agents. The second command registers **both MCP
and automatic capture hooks** together. You do not register or invoke hooks by
hand. By default it configures Codex and also Claude Code when detected.

To choose the agents explicitly, use one of these instead of `ellie install`:

```sh
ellie install --codex            # Codex only
ellie install --claude           # Claude Code only
ellie install --codex --claude   # both agents
```

**Restart each configured agent after installation.** In Codex, open `/hooks`
and review and trust Ellie's commands. Hook trust is a Codex permission step;
Ellie does not bypass it. Older clients may need an update. `ellie doctor`
checks registration and support; registration alone does not prove that hooks
have fired or that capture has completed.

On its first run, uv may download the requested Python version. To use a Python
you already have, replace `--python 3.10` with its path, for example
`--python /opt/homebrew/bin/python3.14` on a Mac with that interpreter installed.
Keep the install command running until it finishes; Ctrl-Z suspends it.

Alternatively, install the checkout with `python3.10 -m pip install .`.
Then run `ellie install` and restart the agents as above. Setuptools is only a
build dependency. These instructions install from this repository; a public
PyPI release is a separate publishing step.

The agent setup uses a stdio MCP server with an absolute Python interpreter path,
adds a marked instruction block, and creates editable extraction guidance.
Existing files get a one-time `.ellie-backup` before modification. Reinstalling
does not duplicate blocks or overwrite your extraction guidance.

For Claude, the installer prints an optional permissions.allow setting. It
does not grant blanket permissions automatically.

### Upgrade an existing installation

From the Ellie checkout:

```sh
git pull --ff-only
uv tool install --force --reinstall --python 3.10 .
ellie install
ellie --version
ellie doctor
```

Run **both** the package update and `ellie install`: an updated executable does
not refresh an older agent configuration by itself. The setup command updates
MCP, hooks, and instructions while preserving existing memories and unrelated
settings. Restart the agents and review any changed Codex hooks afterward.

### Uninstall agent integration

```sh
ellie uninstall
```

Uninstall removes Ellie's MCP registrations, owned hooks, and instruction blocks.
It keeps project memories, transcripts, and unrelated agent configuration.

## Quickstart

After setup, open your project and start an agent normally:

```sh
cd /path/to/your-project
codex
# Or run: claude
```

If this project already has saved context, send your normal first message, such
as “Let's work on login.” Ellie asks the agent to show a picker in its first reply:

```text
Ellie 🐘 — Which memory should I use?
0) Start fresh — no past memory
1) Conversation: Set up deployment · Codex · Nov 20 · 8 items
   Covers: GitHub deployment setup; Publish the product website
   State: Deployment pipeline configured
   Next: Add the homepage
2) Workstream: billing-bug · Double charge on retry
m) More choices
```

The labels above are examples from a project with saved memory. Reply with a
number, several numbers, or a name. Each choice shows what the memory covers,
up to three saved topics, and its state and next step when available. These
previews use that conversation's own saved goal, summary and item titles,
including historical snapshots. Generic summaries such as “Work completed”
do not become the topic. The opening chat message is never used as its topic;
when there is no useful saved content, Ellie says no description is saved yet.
A conversation label is separate from its workstream name. Previews are fixed
for an already displayed picker; start a new chat for updated previews.
Conversation choices load only those source
chats; other conversations stay excluded. Start fresh excludes past memory while
keeping the current chat's write destination. Workstream choices continue the
named workstream with its usual shared project context. The agent then continues
your original task. Existing selections, explicit choices in your first message,
and resumed bindings skip this question; projects without saved context skip it
too. Empty automatic chat workstreams and archived workstreams aren't offered.

This is an agent-rendered chat picker: it can use a native choice control when
available or a numbered text list. Hooks supply the catalog and instructions;
the agent follows them on its first turn. Nothing appears before your first
message. Use `ellie start` below for a terminal picker before launching the agent.
After upgrading an older installation, rerun `ellie install` and restart the
agents to refresh their startup instructions.

To choose a new write workstream explicitly in the chat, say:

> Use Ellie for this project. Create and load a workstream called `auth-refactor`
> for this task, bind this conversation to it, and save important decisions,
> results, and findings as we work.

With trusted hooks and capture set to `auto` (the default), Ellie queues capture
in the background as you work. You can also ask the agent to “save a handoff” to
record the current state and next steps immediately through its memory tools.
Use a different workstream in each chat when working on parallel tasks.

`status` reports the memory inventory and capture health. To answer a question
about the latest work, the agent reloads the selected memory with `load` while
keeping your source selection. Saves from a parallel chat are available to a
fresh load; they are not pushed into a briefing the agent already read. If
capture health reports failures, background extraction has not completed even
when live tool saves are working. Failed jobs stay available for retry.

For a new task that needs specific past context, say:

> Use only conversation CONVERSATION_ID for context. Create and load a new
> workstream called `retry-fix`, and bind this conversation to it.

You can find conversation IDs in `ellie conversations` or the UI's
**Conversations** tab. See [Selecting context](#selecting-context) for examples.

### Start with the CLI picker instead

In your project, create a workstream and launch with selected context:

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

## Browse your memory

Start the dashboard in a separate terminal, preferably from your project:

```sh
ellie ui
```

It prints `Ellie dashboard: http://127.0.0.1:8767` and opens your browser.
If the browser does not open, visit [the local dashboard](http://127.0.0.1:8767/).

**Keep that terminal running.** Closing it, pressing Ctrl-C, or suspending it
with Ctrl-Z stops the page from being served. Installing Ellie or enabling
capture hooks does not start the dashboard automatically. Memory capture works
without the dashboard open.

To browse saved knowledge:

1. Pick a project in the sidebar.
2. Use **Overview** for goals, current state, and next steps.
3. Use **All memories**, search, and the workstream/type filters to find items.
   Click a card for its full fields and conversation source. Enable **Archived**
   to include archived workstreams.
4. Use **Activity** for saved logs and capture records.
5. Use **Conversations** to choose historical context for your next task.

Open **Conversations** to see which chat produced each item. Select one or more
conversations and choose **Use selected conversations**, or **Use only this
conversation**. Overview, search, full details, and Activity then use only those
sources. Set a new workstream name and copy the startup command to begin new
work with that context. **Start with no past history** produces a `--no-history`
command. Project switching resets the source filter.

The dashboard distinguishes the last memory save from the last extraction and
shows pending/failed captures. Page refresh does not imply that memory was saved.

The page refreshes every 15 seconds while visible. It reads your existing
`ELLIE_HOME` and uses the same ranked search as `ellie recall`. It does not edit
memories, scan agent session folders, or make model calls. Search may update
the rebuildable SQLite cache. Keep recording memory through your agent or CLI.
The server binds only to this machine; no hosting or extra packages are needed.
Press Ctrl-C in the terminal to stop it.

```sh
ellie ui --no-open           # print the URL without opening a browser
ellie ui --port 0            # choose a free port
ellie ui --port 9000         # choose a specific port
```

### If the UI does not open or looks empty

- **Connection refused:** run `ellie ui` and keep that terminal running, then
  refresh the browser. Opening the URL alone does not start a server.
- **Port already in use:** run `ellie ui --port 0` and open the URL it prints;
  that address will use a different port from 8767.
- **No memories yet:** the UI displays saved knowledge, not every raw chat.
  Work in an agent with Ellie enabled, or use `ellie backfill` to review older
  sessions. Check `ellie status` from the project and `ellie where` to confirm
  the memory root. The UI and agents must use the same `ELLIE_HOME` if overridden.
- **Blank capture timestamps:** check `ellie doctor`, restart the agents after
  `ellie install`, and review Codex `/hooks`. A running dashboard does not prove
  that capture hooks are active. Use `ellie capture --wait` for an explicit retry;
  it is separate from verifying automatic capture.

## Selecting context

To reuse knowledge from specific conversations in the same project:

```sh
ellie conversations
ellie start codex --from-conversation CONVERSATION_ID --new next-task
ellie start claude --pick-conversations
ellie start codex --no-history --new unrelated-task
ellie recall 'refresh' --conversation CONVERSATION_ID
ellie brief 'add retries' --conversation CONVERSATION_ID --json
ellie timeline R4 --conversation CONVERSATION_ID
```

Repeat `--from-conversation` to combine selected sources. Choosing a conversation
excludes all other conversation history, unattributed items, and global summary
sections. A workstream remains the destination for new work; it can receive
items from multiple conversations. Older conversations may lack historical
versions; new saves retain snapshots so later edits in another conversation do
not change the earlier conversation's view.

In chat, ask: “Use only conversation ID for context, create/load workstream NAME,
and bind this session to it.” The agent uses `conversations`, `bind`, and `load`.
Include the current `session_id` in every MCP call so parallel chats keep their
bindings. `recall`, `get`, and `timeline` retain a bound conversation restriction.
Once bindings exist, agent calls without a current session ID are rejected for
content reads/writes instead of silently using unrestricted history. Status,
conversation discovery and privacy controls remain available for setup.

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
| `ellie ui [--port 8767] [--no-open]` | Local read-only HTML dashboard for projects, memory, search, and activity |
| `ellie conversations [--json]` | Project-scoped conversation catalog, source item IDs and capture state |
| `ellie timeline [ID] [--conversation ID]` | Nearby historical items within the chosen source context |
| `ellie privacy [pause\|resume\|exclude\|include] [ID]` | Capture controls; `--archives filtered\|off` controls future owned archives |
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
| `ellie hook AGENT EVENT` | Lifecycle handler used by installed agent hooks |

Time windows accept a positive number followed by `h`, `d`, or `w`.
Expected errors use `ellie:` on stderr and exit 1; closed output pipes are quiet.
The launcher returns the agent's exit code.

## How capture works

With hooks installed and capture set to `auto`, you can start plain `codex` or
`claude`. SessionStart binds a separate workstream to each conversation and
provides a compact memory index. Choose historical conversations through chat
or the launcher. Include the hook's native session_id in each Ellie tool call.
Loading a workstream changes only that conversation's binding.

Tool events queue durable metadata; model calls run in a background worker.
Checkpoints default to 120 seconds and flush when the agent finishes a turn,
before compaction, or when the session ends. A checkpoint reviews only new
complete transcript records through a fresh ephemeral CLI run. Large sessions
are processed in batches; gzip parts record their source byte ranges. Jobs
queued during extraction remain pending for the next batch. Automatic workers
attempt a failed job at most three times, then retain it for explicit retry.
Capture set to `ask` keeps the launcher's exit prompt; hooks do not launch models
in that mode. `--no-capture` on the launcher also disables hook extraction.

The launcher's final review and manual capture/backfill use this pipeline:

1. The launcher records a pending run outside the repo. Claude gets a UUID
   up front; Codex is matched after exit using cwd, time, and a before/after
   transcript snapshot. An ambiguous match stays pending.
2. Adapters inspect metadata and count human prompts. Codex's legacy and
   paginated histories are supported. Claude metadata can appear throughout
   the file; tool results, injected context, and subagents are excluded.
3. Available JSONL is gzip-archived. Codex parent-history prefixes are archived
   at their recorded byte boundaries and linked in the session registry.
   New Ellie-owned archives filter private blocks and common credential
   patterns. Safe unchanged records preserve their original bytes. Existing
   archives and the upstream agent's session files are not modified.
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

Without active/trusted hooks, use `ellie capture` or `ellie backfill` for ordinary
sessions. Resumed sessions become uncaptured again when their source changes.
Manual captures with fewer than two human prompts are archived and skipped;
hook checkpoints can capture useful work from a single prompt. Filtered private
history uses fresh extraction rather than a native resume of unfiltered content.

Upstream transcript truncation cannot be undone. Missing Codex parent history
or partially written JSONL is reported; the job remains available for retry.
A single JSONL record over 1000000 bytes also stays pending with a clear error;
it is not silently skipped.

## Privacy and save status

```sh
ellie privacy                  # current project's controls
ellie privacy pause            # stop future automatic capture and agent writes
ellie privacy resume
ellie privacy exclude CONVERSATION_ID
ellie privacy include CONVERSATION_ID
ellie privacy --archives off    # future captures retain extracted memory only
ellie privacy --archives filtered
ellie status                   # last saved time, pending work, failures
ellie capture --wait            # explicitly retry pending captures
```

Wrap private text in `<private>...</private>` within a prompt or tool text. Ellie
filters it from future memory, historical snapshots, owned archives and fresh
extraction input. Nested blocks and unclosed blocks are filtered conservatively.
These controls do not delete old data, scrub existing archives, or alter the
agent's own transcript. Pause/exclusion do not erase already queued work; resume
or include the conversation before retrying it. Explicit file editing remains
available while automatic saving is paused.

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

Shared memory is loaded in ordinary workstream mode; explicit conversation-only
selection excludes unrelated shared content. Workstreams contain Goal, Current state,
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
| `checkpoint_interval_sec` | `120` |

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
Corrupt index files are quarantined before rebuilding; memory files are preserved.
Restart an already-running agent if it still holds the damaged cache open.

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
