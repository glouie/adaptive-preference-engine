# Temporal Support, Memory Consolidation & Confidential Store Design

**Date:** 2026-04-14
**Status:** Draft (rev 3 -- addressing Codex adversarial review findings)
**Supersedes:** None (extends existing knowledge and sync systems)

## Problem

APE has three gaps that prevent it from being the single persistence layer for AI agent sessions:

1. **No temporal support.** Knowledge entries have no expiry mechanism. Facts tied to dates ("merge freeze until April 5") or events ("10.5 release testing") persist indefinitely until manually pruned. The category-based TTL in the pruning config handles staleness but not explicit temporal boundaries.

2. **Memory is a separate system.** Claude Code has a built-in memory system (`~/.claude/projects/*/memory/`) that operates independently from APE. This creates duplicate persistence, conflicting sources of truth, and entries that don't benefit from APE's signal tracking, pruning, compaction, or confidential routing. We experienced this directly: a notes-vault commit preference was stored in APE (where it was silently rejected by a conflicting high-confidence rule) and then duplicated in memory as a fallback.

3. **Confidential store is a second-class citizen.** The confidential store (`~/gitlab/gskills/.ape-confidential/knowledge.yaml`) is a flat YAML file with no temporal support, no pruning, no compaction, and no context-aware loading. Machine-specific data (local paths, internal URLs, org-specific references) needs the same features as public data but must sync to a private repo.

## Goals

1. Add per-entry temporal expiry to knowledge entries -- both calendar-based and event-based.
2. Make the confidential store a full peer of the public store with identical features.
3. Consolidate memory into APE so APE is the single source of truth for all non-code persistence.
4. Keep all APE writes outside the main session agent (hooks and subagents only).
5. Commit and push to sync repos frequently -- at minimum on every session end.

## Non-Goals

- Temporal fields on preferences, associations, or contexts (these have confidence decay and context scoping already).
- LLM-based summarization of expired entries (future work).
- Encrypting confidential entries at rest in SQLite (threat model is about sync destinations, not local storage).
- Replacing Claude Code's built-in memory reading mechanism (we generate files it can read).

## Design

### 1. Schema Changes & Dual-Database Architecture

#### Why Two Databases

A single SQLite database with a `confidential` flag creates coupling: the sync layer must filter every query, the PostToolUse hook and session-end hook race on the same file, and a lock acquired during session-end push blocks the memory intercept hook. Separating into two databases eliminates these issues:

- **No cross-store locking.** Public and confidential writes never contend on the same WAL.
- **Independent sync.** Each database has its own JSONL export and git repo. Push to one repo can fail without blocking the other.
- **Simpler queries.** No `WHERE confidential=X` filter on every read path.
- **Clean compaction.** Each database compacts to its own repo without routing logic.

#### Database Layout

```
~/.adaptive-cli/
  ape.db                  # Public store (existing, extended)
  ape-confidential.db     # Confidential store (new, same schema)
```

Both databases share the same schema. The `KnowledgeStorage` class accepts a `db_path` parameter. A new `ConfidentialStorage` factory returns a `KnowledgeStorage` pointed at `ape-confidential.db`.

#### Schema (Applied to Both Databases)

Three new nullable columns on the `knowledge` table:

```sql
ALTER TABLE knowledge ADD COLUMN expires_at TEXT;
ALTER TABLE knowledge ADD COLUMN expires_when TEXT;
ALTER TABLE knowledge ADD COLUMN expires_when_tag TEXT;
```

| Column | Type | Purpose |
|---|---|---|
| `expires_at` | TEXT (ISO date) | Hard calendar expiry. Auto-archive when `today > expires_at`. |
| `expires_when` | TEXT | Human-readable trigger description (e.g., "10.5 GA ships"). Informational, not automated. |
| `expires_when_tag` | TEXT | Signal tag to watch. During pruning, if a signal with this tag exists after the entry's `created_at`, the entry is surfaced for review. |

No `confidential` column needed -- the database file itself determines confidentiality.

KnowledgeEntry dataclass updated:

```python
@dataclass
class KnowledgeEntry:
    # ... existing fields ...
    expires_at: Optional[str] = None
    expires_when: Optional[str] = None
    expires_when_tag: Optional[str] = None
```

Migration: `ALTER TABLE ADD COLUMN` applied on first access to each database. Existing entries get `NULL` defaults. No data migration needed for the public store. The confidential store is created fresh (see Section 2).

### 2. Confidential Routing (Dual-Database)

#### Classification

Confidential classification happens at write time. The classification determines which database receives the entry.

Config additions:

```yaml
confidential:
  db_path: ~/.adaptive-cli/ape-confidential.db
  repo_path: ~/gitlab/gskills
  store_dir: .ape-confidential
  patterns:
    - "~/notes-vault"
    - "~/learning/"
    - "/Users/"
    - "cd.splunkdev.com"
    - "@cisco.com"
  auto_classify: true
```

When `auto_classify: true`, every knowledge entry's `content` field is scanned against `confidential.patterns` at write time. If any pattern matches, the entry is written to `ape-confidential.db` instead of `ape.db`. Entries can also be explicitly routed via `--confidential` flag on CLI commands.

#### Write Path

```
cli.py knowledge add
       |
       +-- scan content against confidential.patterns
       |
       +-- match?  --> ape-confidential.db (confidential store)
       +-- no match --> ape.db (public store)
```

#### Sync Push (Modified)

`SyncRunner.push()` operates on each database independently:

```
ape.db          --> ~/learning/glouie-assistant/knowledge.jsonl
                    git add + commit + push

ape-confidential.db --> ~/gitlab/gskills/.ape-confidential/knowledge.jsonl
                        git add + commit + push
```

Other tables (preferences, associations, contexts, signals) live only in `ape.db` and sync to the public repo. They contain behavioral patterns, not factual data.

**Split-brain detection:** Because the two repos push independently, a crash between the first and second push leaves one repo ahead of the other. On session-start, after pulling both repos, the sync runner compares the last-push timestamp stored in each database's `sync_meta` table. If the timestamps differ by more than 60 seconds, a warning is logged: `"ape: split-brain detected -- public last pushed <T1>, confidential last pushed <T2>"`. No automatic repair is attempted (the data is not corrupted, just out of sync). The next session-end push brings both repos current. The `sync_meta` table is a new single-row table: `CREATE TABLE IF NOT EXISTS sync_meta (last_push_at TEXT, last_pull_at TEXT)`.

#### Sync Pull (Modified)

Pull imports into each database from its paired repo:

1. `git pull` in public repo, import `knowledge.jsonl` into `ape.db`.
2. `git pull` in confidential repo, import `knowledge.jsonl` into `ape-confidential.db`.
3. Other tables imported from public repo into `ape.db` only (unchanged).

**Conflict resolution:** Both repos use `git pull --rebase`. If rebase fails (diverged history), fall back to `git stash && git pull && git stash pop`. If that also fails, log a warning and skip the pull -- local state is authoritative, and the next push will reconcile. JSONL import uses upsert (match on `id`), so duplicate entries from a messy merge are idempotent.

**Repo operation serialization:** All git operations on a given repo are serialized via a lockfile (`~/.adaptive-cli/<repo-name>.lock`) using `fcntl.flock()`. This prevents concurrent Claude Code sessions (multiple terminals) from interleaving pull/stash/push operations on the same repo. Lock acquisition uses `LOCK_EX | LOCK_NB` (non-blocking) -- if the lock is held, the operation is skipped with a log warning rather than blocking the session.

#### Confidential Store Migration

CLI subcommand (not a separate script):

```bash
adaptive-cli knowledge migrate-confidential
```

1. Read existing `.ape-confidential/knowledge.yaml` entries.
2. Convert to `KnowledgeEntry` objects.
3. Save to `ape-confidential.db`.
4. Write `.ape-confidential/knowledge.jsonl` (new format).
5. Delete `.ape-confidential/knowledge.yaml`.
6. Commit: `ape: migrate confidential store from YAML to JSONL`.

#### Compaction

Each database compacts to its paired repo -- no routing logic needed:

- `ape.db` entries: `~/learning/glouie-assistant/partitions/<partition>/consolidated.md`
- `ape-confidential.db` entries: `~/gitlab/gskills/.ape-confidential/partitions/<partition>/consolidated.md`

The compaction engine takes a `storage` parameter; the caller passes the appropriate database.

### 3. Temporal Expiry

Temporal fields are checked at two points:

#### Session-Start Hook (Every Session, Fast)

```
Load knowledge entries for context
       |
       v
For each entry with expires_at set:
  today > expires_at? --> auto-archive, skip loading
       |
       v
Remaining entries loaded into session
```

Only checks `expires_at` (calendar-based). No external queries, no user interaction.

#### Pruning (On-Demand or Scheduled)

```
For each non-archived entry (in both ape.db and ape-confidential.db):
  1. expires_at past?            --> auto-archive
  2. expires_when_tag set?       --> query signal table (in ape.db only):
     |                               SELECT COUNT(*) FROM signals
     |                               WHERE ',' || context_tags || ',' LIKE '%,' || tag || ',%'
     |                               AND timestamp > entry.created_at
     |
     +-- signal found?           --> surface for review:
     |                               "Entry X has trigger 'Y', matching signal received.
     |                                Archive? [y/n]"
     +-- no signal?              --> leave alone
  3. Category TTL exceeded?      --> existing decay behavior (unchanged)
```

**Tag matching:** Tags are stored comma-delimited. The query wraps `context_tags` in commas (`',' || context_tags || ','`) and searches for `,%tag,%` to prevent partial matches (e.g., tag `10.5` won't match `10.50` or `210.5`).

**Tag validation:** Tags must match `^[a-zA-Z0-9][a-zA-Z0-9.-]*$` (alphanumeric start, then alphanumeric plus `.` and `-`). Underscores (`_`) and percent signs (`%`) are excluded because they are LIKE wildcards in SQLite. Validation is enforced at write time in `cli.py` and `storage.py`. Tags containing invalid characters are rejected with an error message.

**Cross-database signals:** Signal tags live in `ape.db` only (signals are behavioral, not confidential). When pruning `ape-confidential.db`, the pruner queries the signal table from `ape.db`. This is a read-only cross-database access -- no write contention.

Non-interactive mode (`prune --auto`): archives `expires_at` entries, skips review prompts for tagged entries. Tagged entries wait for an interactive session.

**Performance budget:** Session-start expiry check targets <200ms added latency. This is O(n) over knowledge entries with `expires_at` set -- acceptable for hundreds of entries. If entry count exceeds 1000, add an index: `CREATE INDEX IF NOT EXISTS idx_knowledge_expires ON knowledge(expires_at) WHERE expires_at IS NOT NULL`. Implementation must include a timing acceptance test: seed both databases with 500 entries each (100 with `expires_at`), measure archive pass, assert <200ms on a cold cache.

#### CLI Surface

```bash
# Calendar-based expiry
adaptive-cli knowledge add --title "Merge freeze" \
  --content "No merges to main until release cut" \
  --expires-at "2026-04-20"

# Event-based expiry
adaptive-cli knowledge add --title "10.5 release testing" \
  --content "Testing cadence for 10.5 branch" \
  --expires-when "10.5 GA ships" \
  --expires-when-tag "10.5-shipped"

# Pruning output
adaptive-cli prune
#   Auto-archived: "Merge freeze" (expired 2026-04-20)
#   Review: "10.5 release testing" -- trigger tag "10.5-shipped" has matching signal.
#     Archive? [y/n]
```

### 4. Memory Consolidation

#### Architecture

APE becomes the single source of truth for all non-code persistence. Claude Code's built-in memory loading continues to work via generated `.md` files.

**Key principle:** All APE writes happen outside the main session agent -- in hooks, subagents, or CLI subprocesses. The main agent only reads.

```
Main Session Agent (reads only)
       |
       +-- reads ~/.claude/projects/*/memory/*.md  (Claude Code built-in)
       +-- reads APE preferences via session-start hook output
       |
       +-- User corrects agent --> agent runs cli.py signal (Bash subprocess)
       |                           signal processing happens in CLI, not agent
       |
       +-- Agent writes to memory/ --> PostToolUse hook queues to inbox
                                       (copy, not move -- agent sees success)

Hooks & Subagents (writes)
       |
       +-- SessionStart hook
       |     +-- Check expires_at, auto-archive expired entries (both DBs)
       |     +-- Ingest any pending inbox files into appropriate DB
       |     +-- Load preferences + knowledge for context
       |     +-- Generate memory .md files from relevant knowledge entries
       |
       +-- PostToolUse hook (Write|Edit targeting memory/ paths)
       |     +-- Detect write target is a memory directory
       |     +-- Copy file to inbox (~/.adaptive-cli/memory-inbox/)
       |     +-- Do NOT move or delete the original (agent may read it back)
       |     +-- Do NOT ingest immediately (avoid rapid-fire DB writes)
       |
       +-- SessionEnd hook (Stop event)
             +-- Ingest any pending inbox files into appropriate DB
             +-- Export both SQLite DBs to JSONL
             +-- Regenerate memory .md files from current knowledge
             +-- Git commit + push both repos
             +-- Clear memory inbox
```

#### Path Separation

Two directories, never mixed:

| Path | Owner | Purpose |
|---|---|---|
| `~/.claude/projects/*/memory/` | APE (generated) | Canonical memory files, read by Claude Code |
| `~/.adaptive-cli/memory-inbox/` | Agent (writes land here) | Staging area, ingested by APE at session boundaries |

**Batched ingestion:** The PostToolUse hook copies (not moves) the written file to the inbox. It does NOT ingest into APE immediately. Ingestion happens at two points: session-start (for files left from a crashed session) and session-end. This avoids race conditions where rapid sequential writes to memory files (e.g., writing a memory `.md` then updating `MEMORY.md`) would contend on the database.

**Project hash discovery:** Claude Code stores memory at `~/.claude/projects/<hash>/memory/` where `<hash>` is derived from the working directory path. The session-start hook discovers the active project memory path by scanning `~/.claude/projects/*/memory/` directories and matching the one whose parent symlink or path component corresponds to the current `$PWD`. The hook caches the discovered path in `$CLAUDE_PROJECT_MEMORY_DIR` for use by other hooks in the same session.

#### PostToolUse Hook (Memory Intercept)

Added to `hooks.json` (runs alongside existing signal detector -- both are independent):

```json
{
  "PostToolUse": [
    {
      "matcher": "Write|Edit",
      "hooks": [
        {
          "type": "command",
          "command": "$CLAUDE_PLUGIN_ROOT/scripts/posttool-memory-intercept.py"
        }
      ]
    }
  ]
}
```

`posttool-memory-intercept.py` logic:

1. Read tool result from stdin (JSON with `file_path`).
2. If `file_path` does not contain `/memory/`, exit 0 (not a memory write).
3. If `file_path` ends with `MEMORY.md`, exit 0 (index file, skip).
4. Derive a unique inbox filename: `<project-hash>_<basename>` where `<project-hash>` is extracted from the file path (`~/.claude/projects/<hash>/memory/<basename>`). This prevents collisions when multiple projects have memory files with the same name (e.g., `feedback_testing.md`).
5. Write to inbox using atomic temp-file + rename: write to `~/.adaptive-cli/memory-inbox/.<unique-name>.tmp`, then `os.rename()` to final path. This prevents partial files from a crash mid-copy.
6. Exit 0. No database writes, no moves, no classification. Fast path (<50ms).

The actual ingestion logic (parsing frontmatter, classifying confidential, writing to DB) runs during session boundary hooks:

1. Parse the `.md` file: extract YAML frontmatter (`name`, `description`, `type`) and body content.
2. Map memory type to APE knowledge fields:
   - `type: feedback` --> `category: preference`
   - `type: user` --> `category: context`, `partition: user`
   - `type: project` --> `category: context`, `partition: projects/<project>`
   - `type: reference` --> `category: reference`
3. Scan content against `confidential.patterns` to route to correct DB.
4. Run upsert (match on SHA-256 of `title + content + type + partition` to avoid duplicates and detect metadata changes).
5. Delete the inbox file after successful ingestion.

#### Memory .md Generation

During session-start and session-end hooks, APE generates memory files from its knowledge store:

1. Query non-archived knowledge entries from both databases relevant to the current project context. Relevance is determined by matching entry `partition` and `tags` against the session's `context_tags` (derived from the working directory in `session-start-hook.sh`). Same matching logic as the existing knowledge compaction context injection.
2. **External edit detection (v1: disabled, documented for v2).** Comparing file mtime to entry `updated_at` introduces a TOCTOU race: an editor could modify a file between the check and the overwrite. Additionally, coarse filesystem timestamps (1-second resolution on HFS+) make same-second edits undetectable. For v1, APE always overwrites memory files from the database -- the inbox is the only ingest path. External edits outside Claude Code must be routed through `adaptive-cli knowledge add` or placed in the inbox manually. V2 can add inotify/fsevents watching for a race-free solution.
3. For each entry, generate a `.md` file with frontmatter using atomic writes (temp-file + rename to prevent partial reads by Claude Code):

```markdown
---
name: <title>
description: <first line of content or partition context>
type: <mapped from category>
---

<content>
```

4. Write to `~/.claude/projects/<project-hash>/memory/` (using cached `$CLAUDE_PROJECT_MEMORY_DIR`).
5. Generate `MEMORY.md` index from all active entries.

#### Migration of Existing Memory

CLI subcommand (not a separate script):

```bash
adaptive-cli knowledge import-memory --scan
```

1. Scans all `~/.claude/projects/*/memory/*.md` files (excluding `MEMORY.md`).
2. Parses frontmatter and content.
3. **Deduplication:** For each entry, compute a content hash (SHA-256 of `title + content + type + partition`). Skip if an entry with the same hash already exists in either database. Including type and partition in the hash ensures that metadata-only changes (e.g., reclassifying from `user` to `project`, or moving to a different partition) are detected as new entries. This makes the import idempotent -- safe to run multiple times.
4. Creates knowledge entries with appropriate partition, category, and confidential classification (routed to the correct DB via pattern matching).
5. After import, APE takes ownership of the memory directories.

#### CLAUDE.md Changes

The `Before Persisting Anything` checklist simplifies to:

```
IF code/project artifact (specs, design docs, TODOs, config)
  --> Write to the relevant REPO. STOP.

ELSE
  --> APE handles it. Behavioral preferences are recorded as signals.
      Factual knowledge is stored via hooks/subagents.
      Do NOT write to ~/.claude/projects/*/memory/ directly.
```

### 5. Commit Frequency & Sync Strategy

#### Push Triggers

| Trigger | What happens | Where |
|---|---|---|
| SessionEnd (Stop hook) | Export both DBs + commit + push both repos | `session-end-hook.sh` |
| After knowledge add | If 5+ unpushed changes, auto-push affected repo | Built into `cli.py knowledge add` |
| After signal batch | If 10+ unpushed signals, auto-push public repo | Built into signal processing |
| Manual | `adaptive-cli sync push` | Unchanged (pushes both repos) |

#### SessionEnd Hook

New hook in `hooks.json`:

```json
{
  "Stop": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "$CLAUDE_PLUGIN_ROOT/scripts/session-end-hook.sh"
        }
      ]
    }
  ]
}
```

`session-end-hook.sh`:

1. Ingest any pending inbox files (batched ingestion from Section 4).
2. Regenerate memory `.md` files from current knowledge entries (both DBs).
3. Export `ape.db` to `~/learning/glouie-assistant/knowledge.jsonl`.
4. Export `ape-confidential.db` to `~/gitlab/gskills/.ape-confidential/knowledge.jsonl`.
5. Git commit + push public repo.
6. Git commit + push confidential repo.
7. Clear `~/.adaptive-cli/memory-inbox/`.

**Stop hook reliability:** Claude Code's `Stop` event does not fire on `kill -9`, terminal close, or crash. To mitigate data loss from ungraceful exits:

- The auto-push threshold (5 changes) ensures most data reaches the remote during normal operation.
- Session-start hook checks for stale inbox files and ingests them (crash recovery).
- A periodic push can be added later via cron (`adaptive-cli sync push --quiet` every 15 minutes) but is not required for v1 -- the auto-push threshold is sufficient.

#### Config Additions

```yaml
sync:
  auto_push_threshold: 5
  session_end_push: true
  memory_generation: true

memory:
  inbox_path: ~/.adaptive-cli/memory-inbox
  intercept_writes: true
```

#### Push Failure Handling

If push fails (network, auth, etc.):

1. Commit succeeds locally (data is safe in the local git repo).
2. Log a warning to stderr, do not block the session.
3. Next session's sync push retries (local is ahead of remote, push will include all pending commits).
4. Public and confidential pushes are independent -- one failing does not block the other.

#### Pull Failure Handling

If `git pull --rebase` fails during session-start:

1. Attempt `git stash && git pull && git stash pop`.
2. If that also fails, log a warning and skip the pull.
3. Local state is authoritative for the current session.
4. The next push will force-reconcile (JSONL import uses upsert by `id`).

#### Git Commit Message Convention

```
ape: sync <N> prefs, <M> signals, <K> knowledge (session end)
ape: sync 2 knowledge (auto-push threshold)
ape: compact <partition> (N entries -> 1, saved Xt)
ape: migrate confidential store from YAML to JSONL
```

### 6. Summary of All Changes

#### Schema

| Table | Database | Change |
|---|---|---|
| `knowledge` | Both (`ape.db`, `ape-confidential.db`) | Add columns: `expires_at`, `expires_when`, `expires_when_tag` |

#### Files Modified

| File | Change |
|---|---|
| `src/adaptive_preference_engine/knowledge.py` | Add 3 temporal fields to KnowledgeEntry dataclass |
| `scripts/storage.py` | Schema migration, `db_path` parameter, `ConfidentialStorage` factory |
| `scripts/sync.py` | Dual-database export, dual-repo push/pull with conflict resolution |
| `scripts/cli.py` | New flags: `--expires-at`, `--expires-when`, `--expires-when-tag`, `--confidential`; new subcommands: `knowledge import-memory`, `knowledge migrate-confidential` |
| `scripts/session-start-hook.sh` | Add expires_at check (both DBs), inbox ingestion, memory .md generation, project hash discovery |
| `scripts/compaction.py` | Accept `storage` parameter, compact to paired repo |
| `hooks/hooks.json` | Add Stop hook, add second PostToolUse entry for memory intercept (runs alongside existing signal detector, both are independent) |

#### Files Created

| File | Purpose |
|---|---|
| `scripts/session-end-hook.sh` | SessionEnd: ingest inbox, export both DBs, generate memory, push both repos |
| `scripts/posttool-memory-intercept.py` | Copy memory writes to inbox (fast path, no DB writes) |
| `scripts/memory_generator.py` | Generate `.md` files from knowledge entries for Claude Code, using atomic writes (temp-file + rename) |

Migration logic (`migrate-confidential`, `import-memory`) is implemented as CLI subcommands in `cli.py`, not separate scripts.

#### Config Additions

```yaml
confidential:
  db_path: ~/.adaptive-cli/ape-confidential.db
  repo_path: ~/gitlab/gskills
  store_dir: .ape-confidential
  patterns: [...]
  auto_classify: true

sync:
  auto_push_threshold: 5
  session_end_push: true
  memory_generation: true

memory:
  inbox_path: ~/.adaptive-cli/memory-inbox
  intercept_writes: true
```

### 7. Safety & Rollback

- **Schema migration is additive.** New columns are nullable with defaults. Existing code that doesn't read the new fields continues to work.
- **Dual-database is backward-compatible.** The public `ape.db` retains its existing path and schema. Code that only reads `ape.db` is unaffected. The confidential database is new and additive.
- **Confidential store migration preserves the YAML.** The YAML file is deleted only after successful JSONL write and SQLite import. Git history preserves the YAML.
- **Memory import is non-destructive and idempotent.** Existing `.md` files are read, not deleted. Deduplication via content hash (title + content + type + partition) prevents duplicates on re-run and detects metadata-only changes. APE takes ownership by generating files on top of them. If APE breaks, the original files still exist in git history or the inbox.
- **Memory intercept is copy-not-move with atomic writes.** The PostToolUse hook copies to inbox via temp-file + rename. The agent's view of the filesystem is never disrupted. Inbox filenames include the project hash to prevent cross-project basename collisions. Partial files from a crash mid-copy are never visible to the ingestion logic.
- **Push failure is non-blocking.** Local commits succeed regardless of push status. Public and confidential pushes are independent. No data loss on network failure. Split-brain (one repo ahead) is detected on next session-start and resolved by the next full push.
- **Pull failure is non-blocking.** Session-start pull uses rebase with stash fallback. If both fail, local state is authoritative. The next push reconciles.
- **Repo operations are serialized.** `fcntl.flock()` lockfiles prevent concurrent sessions from interleaving git operations. Non-blocking acquisition means a locked-out session skips rather than deadlocks.
- **Temporal auto-archive is reversible.** Archived entries remain in SQLite. `knowledge restore <id>` un-archives them.
- **Crash recovery.** If a session dies before the Stop hook fires, the inbox retains unprocessed files (intact, due to atomic writes). The next session's start hook ingests them. No data loss.
- **Memory regeneration uses atomic writes.** Generated `.md` files are written via temp-file + rename, so Claude Code never reads a partial file. External edits to memory files are not auto-detected in v1 -- use the inbox or CLI to ingest changes.
- **Tag validation at write time.** Tags matching `^[a-zA-Z0-9][a-zA-Z0-9.-]*$` are accepted; others are rejected. Underscores and percent signs are excluded as LIKE wildcards.
