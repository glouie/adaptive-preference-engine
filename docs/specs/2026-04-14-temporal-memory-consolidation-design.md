# Temporal Support, Memory Consolidation & Confidential Store Design

**Date:** 2026-04-14
**Status:** Draft
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

### 1. Schema Changes

Four new nullable columns on the `knowledge` table:

```sql
ALTER TABLE knowledge ADD COLUMN expires_at TEXT;
ALTER TABLE knowledge ADD COLUMN expires_when TEXT;
ALTER TABLE knowledge ADD COLUMN expires_when_tag TEXT;
ALTER TABLE knowledge ADD COLUMN confidential INTEGER DEFAULT 0;
```

| Column | Type | Purpose |
|---|---|---|
| `expires_at` | TEXT (ISO date) | Hard calendar expiry. Auto-archive when `today > expires_at`. |
| `expires_when` | TEXT | Human-readable trigger description (e.g., "10.5 GA ships"). Informational, not automated. |
| `expires_when_tag` | TEXT | Signal tag to watch. During pruning, if a signal with this tag exists after the entry's `created_at`, the entry is surfaced for review. |
| `confidential` | INTEGER (0/1) | 0 = public (syncs to glouie-assistant), 1 = confidential (syncs to private repo). |

KnowledgeEntry dataclass updated:

```python
@dataclass
class KnowledgeEntry:
    # ... existing fields ...
    expires_at: Optional[str] = None
    expires_when: Optional[str] = None
    expires_when_tag: Optional[str] = None
    confidential: bool = False
```

Migration: `ALTER TABLE ADD COLUMN` applied on first access. Existing entries get `NULL`/`0` defaults. No data migration needed.

### 2. Confidential Routing

#### Classification

Confidential classification happens at write time via pattern matching.

Config additions:

```yaml
confidential:
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

When `auto_classify: true`, every knowledge entry's `content` field is scanned against `confidential.patterns` at write time. If any pattern matches, `confidential=1` is set automatically. Entries can also be explicitly marked confidential via `--confidential` flag on CLI commands.

#### Sync Push (Modified)

The existing `SyncRunner.push()` method splits knowledge entries by the `confidential` flag:

```
SQLite knowledge table
       |
       +-- confidential=0 --> ~/learning/glouie-assistant/knowledge.jsonl
       |                      git add + commit + push
       |
       +-- confidential=1 --> ~/gitlab/gskills/.ape-confidential/knowledge.jsonl
                               git add + commit + push
```

Other tables (preferences, associations, contexts, signals) continue to sync only to the public repo. They contain behavioral patterns, not factual data -- no confidential routing needed.

#### Sync Pull (Modified)

Pull imports from both repos:

1. `git pull` in public repo, import `knowledge.jsonl` (entries get `confidential=0`).
2. `git pull` in confidential repo, import `knowledge.jsonl` (entries get `confidential=1`).
3. Other tables imported from public repo only (unchanged).

#### Confidential Store Migration

On first push after this change:

1. Read existing `.ape-confidential/knowledge.yaml` entries.
2. Convert to `KnowledgeEntry` objects with `confidential=1`.
3. Save to SQLite.
4. Write `.ape-confidential/knowledge.jsonl` (new format).
5. Delete `.ape-confidential/knowledge.yaml`.
6. Commit: `ape: migrate confidential store from YAML to JSONL`.

#### Compaction

Confidential entries with `ref_path` write their consolidated markdown files to the confidential repo:

- Public: `~/learning/glouie-assistant/partitions/<partition>/consolidated.md`
- Confidential: `~/gitlab/gskills/.ape-confidential/partitions/<partition>/consolidated.md`

The compaction engine checks the `confidential` flag to determine the destination.

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
For each non-archived entry:
  1. expires_at past?            --> auto-archive
  2. expires_when_tag set?       --> query signal table:
     |                               SELECT COUNT(*) FROM signals
     |                               WHERE context_tags LIKE '%' || tag || '%'
     |                               AND timestamp > entry.created_at
     |
     +-- signal found?           --> surface for review:
     |                               "Entry X has trigger 'Y', matching signal received.
     |                                Archive? [y/n]"
     +-- no signal?              --> leave alone
  3. Category TTL exceeded?      --> existing decay behavior (unchanged)
```

Non-interactive mode (`prune --auto`): archives `expires_at` entries, skips review prompts for tagged entries. Tagged entries wait for an interactive session.

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
       +-- Agent writes to memory/ --> PostToolUse hook intercepts
                                       ingests into APE, redirects to inbox

Hooks & Subagents (writes)
       |
       +-- SessionStart hook
       |     +-- Check expires_at, auto-archive expired entries
       |     +-- Load preferences + knowledge for context
       |     +-- Generate memory .md files from relevant knowledge entries
       |
       +-- PostToolUse hook (Write|Edit targeting memory/ paths)
       |     +-- Detect write target is a memory directory
       |     +-- Move written file to inbox (~/.adaptive-cli/memory-inbox/)
       |     +-- Ingest content into APE knowledge via cli.py
       |     +-- Classify confidential if content matches patterns
       |     +-- Original write succeeded (agent not confused)
       |
       +-- SessionEnd hook (Stop event)
             +-- Export SQLite to JSONL (split public/confidential)
             +-- Regenerate memory .md files from current knowledge
             +-- Git commit + push both repos
             +-- Clear memory inbox
```

#### Path Separation

Two directories, never mixed:

| Path | Owner | Purpose |
|---|---|---|
| `~/.claude/projects/*/memory/` | APE (generated) | Canonical memory files, read by Claude Code |
| `~/.adaptive-cli/memory-inbox/` | Agent (writes land here) | Staging area, ingested by APE then cleared |

APE generates the canonical memory directory. If the agent writes to memory directly, the PostToolUse hook moves the file to the inbox and ingests it into APE. The agent sees a successful write. APE regenerates the canonical files on next session start or sync.

#### PostToolUse Hook (Memory Intercept)

Added to `hooks.json`:

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
2. If `file_path` does not contain `/memory/`, exit (not a memory write).
3. If `file_path` ends with `MEMORY.md`, exit (index file, skip).
4. Parse the `.md` file: extract YAML frontmatter (`name`, `description`, `type`) and body content.
5. Map memory type to APE knowledge fields:
   - `type: feedback` --> `category: preference`
   - `type: user` --> `category: context`, `partition: user`
   - `type: project` --> `category: context`, `partition: projects/<project>`
   - `type: reference` --> `category: reference`
6. Run `cli.py knowledge add --from-memory <inbox_path>` to ingest.
7. Move the file from the memory directory to `~/.adaptive-cli/memory-inbox/`.

#### Memory .md Generation

During session-start and session-end hooks, APE generates memory files from its knowledge store:

1. Query non-archived knowledge entries relevant to the current project context.
2. For each entry, generate a `.md` file with frontmatter:

```markdown
---
name: <title>
description: <first line of content or partition context>
type: <mapped from category>
---

<content>
```

3. Write to `~/.claude/projects/<project-hash>/memory/`.
4. Generate `MEMORY.md` index from all active entries.

#### Migration of Existing Memory

One-time command:

```bash
adaptive-cli knowledge import-memory --scan
```

1. Scans all `~/.claude/projects/*/memory/*.md` files (excluding `MEMORY.md`).
2. Parses frontmatter and content.
3. Creates knowledge entries with appropriate partition, category, and confidential classification.
4. After import, APE takes ownership of the memory directories.

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
| SessionEnd (Stop hook) | Export + commit + push both repos | `session-end-hook.sh` |
| After knowledge add | If 5+ unpushed changes, auto-push | Built into `cli.py knowledge add` |
| After signal batch | If 10+ unpushed signals, auto-push | Built into signal processing |
| Manual | `adaptive-cli sync push` | Unchanged |

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

1. Regenerate memory `.md` files from current knowledge entries.
2. Export SQLite to JSONL (split public entries to public repo, confidential to private repo).
3. Git commit + push public repo.
4. Git commit + push confidential repo.
5. Clear `~/.adaptive-cli/memory-inbox/`.

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

1. Commit succeeds locally (data is safe).
2. Log a warning, do not block the session.
3. Next session's sync push retries (local is ahead of remote, push will include all pending commits).

#### Git Commit Message Convention

```
ape: sync <N> prefs, <M> signals, <K> knowledge (session end)
ape: sync 2 knowledge (auto-push threshold)
ape: compact <partition> (N entries -> 1, saved Xt)
ape: migrate confidential store from YAML to JSONL
```

### 6. Summary of All Changes

#### Schema

| Table | Change |
|---|---|
| `knowledge` | Add columns: `expires_at`, `expires_when`, `expires_when_tag`, `confidential` |

#### Files Modified

| File | Change |
|---|---|
| `src/adaptive_preference_engine/knowledge.py` | Add 4 fields to KnowledgeEntry dataclass |
| `scripts/storage.py` | Schema migration, confidential-aware queries |
| `scripts/sync.py` | Split push/pull by confidential flag, dual-repo support |
| `scripts/cli.py` | New flags: `--expires-at`, `--expires-when`, `--expires-when-tag`, `--confidential`, `knowledge import-memory` |
| `scripts/session-start-hook.sh` | Add expires_at check, memory .md generation |
| `scripts/compaction.py` | Route ref files to correct repo based on confidential flag |
| `hooks/hooks.json` | Add Stop hook, update PostToolUse matcher |

#### Files Created

| File | Purpose |
|---|---|
| `scripts/session-end-hook.sh` | SessionEnd: export, generate memory, push both repos |
| `scripts/posttool-memory-intercept.py` | Intercept memory writes, ingest into APE, redirect to inbox |
| `scripts/memory_generator.py` | Generate `.md` files from knowledge entries for Claude Code |
| `scripts/migrate_confidential.py` | One-time YAML to JSONL migration for confidential store |
| `scripts/import_memory.py` | One-time import of existing memory `.md` files |

#### Config Additions

```yaml
confidential:
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
- **Confidential store migration preserves the YAML.** The YAML file is deleted only after successful JSONL write and SQLite import. Git history preserves the YAML.
- **Memory import is non-destructive.** Existing `.md` files are read, not deleted. APE takes ownership by generating files on top of them. If APE breaks, the original files still exist in git history or the inbox.
- **Push failure is non-blocking.** Local commits succeed regardless of push status. No data loss on network failure.
- **Temporal auto-archive is reversible.** Archived entries remain in SQLite. `knowledge restore <id>` un-archives them.
