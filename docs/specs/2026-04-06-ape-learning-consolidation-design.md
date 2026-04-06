# APE + Learning Plugin Consolidation — Design Spec

**Date:** 2026-04-06
**Author:** George Louie + Claude
**Status:** Approved

## Summary

Consolidate the learning-agent plugin into the Adaptive Preference Engine (APE). APE gains a knowledge store for factual knowledge (project context, conventions, decisions), enhanced sync using the glouie-assistant git repo, pruning/staleness lifecycle management, token budgets with statusline indicators, and a workflow engine for reusable multi-phase process templates.

After consolidation:
- The learning-agent plugin is deleted
- `/ape` becomes the single unified skill (replacing `/learning` and `/adaptive-preferences`)
- `~/learning/glouie-assistant/` becomes APE's sync repo
- APE handles both behavioral preferences and factual knowledge

## Decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Decay config location | Defaults in `~/.adaptive-cli/config.json`, user overrides in sync repo `config.yaml` |
| 2 | Old partitions cleanup | `git tag pre-ape-migration`, then delete. Clean repo, tag as breadcrumb. |
| 3 | Skill consolidation | `/ape` unified skill. `/learning` and `/adaptive-preferences` removed. |
| 4 | Token budget | Per-domain budgets (lower for prefs, higher for knowledge). Soft gate with warnings. Statusline pruning icon. Auto-archive on prune confirmation. |
| 5 | Partitions | Drop `people/`. Keep `workflows/` for reusable process templates. |

## Phase 1: Knowledge Store

### Schema

New SQLite table in `storage.py`:

```sql
CREATE TABLE IF NOT EXISTS knowledge (
    id              TEXT PRIMARY KEY,
    partition       TEXT NOT NULL,
    category        TEXT NOT NULL,
    title           TEXT NOT NULL,
    tags            TEXT NOT NULL,
    content         TEXT NOT NULL,
    confidence      REAL DEFAULT 1.0,
    source          TEXT DEFAULT 'explicit',
    machine_origin  TEXT,
    decay_exempt    INTEGER DEFAULT 0,
    access_count    INTEGER DEFAULT 0,
    token_estimate  INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL,
    last_used       TEXT NOT NULL,
    archived        INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_know_partition ON knowledge(partition);
CREATE INDEX IF NOT EXISTS idx_know_category  ON knowledge(category);
CREATE INDEX IF NOT EXISTS idx_know_archived  ON knowledge(archived);
```

- `partition`: free-form path string. Valid prefixes: `user/`, `projects/`, `domains/`, `workflows/`
- `category`: one of `preference`, `pattern`, `decision`, `convention`, `context`
- `tags`: JSON array of strings
- `content`: markdown body
- `source`: `explicit` (user added), `implicit` (auto-detected), `migrated` (from learning plugin)
- `archived`: soft-delete flag (0 = active, 1 = archived)

### CLI Commands

New subcommand group `adaptive-cli knowledge`:

| Command | Purpose |
|---------|---------|
| `knowledge add <title>` | Interactive entry creation (partition, category, content, tags) |
| `knowledge search <query>` | Keyword search across titles, tags, content |
| `knowledge show <id\|title>` | Display full entry with metadata |
| `knowledge list` | List non-archived entries (filterable by `--partition`, `--category`) |
| `knowledge archive <query>` | Soft-delete (sets `archived=1`) |
| `knowledge restore <id>` | Un-archive an entry |
| `knowledge prune` | Surface stale entries, interactive confirm, then archive |

### Partition Auto-Detection

Based on cwd when adding entries:
- Known project paths map to `projects/<name>`
- Unknown paths prompt the user
- Topics about tools/frameworks suggest `domains/<topic>`
- User preferences suggest `user/`
- Process templates suggest `workflows/`

## Phase 2: Sync Enhancement

### Repo Structure

`~/learning/glouie-assistant/` becomes APE's sync repo:

```
~/learning/glouie-assistant/
+-- all_preferences.jsonl
+-- associations.jsonl
+-- contexts.jsonl
+-- signals.jsonl
+-- knowledge.jsonl          # NEW
+-- agents/
+-- claude_scripts/
+-- config.yaml              # user overrides (decay thresholds, token budgets)
+-- README.md
```

Configure via:
```bash
adaptive-cli sync configure --repo-path ~/learning/glouie-assistant
```

### knowledge.jsonl Format

One JSON object per line, matching the knowledge table schema:

```json
{"id": "2dfd2512-...", "partition": "user", "category": "preference", "title": "User Preferences", "tags": ["skills-marketplace"], "content": "...", "confidence": 1.0, "source": "migrated", "machine_origin": "glouie-macbook", "decay_exempt": true, "access_count": 0, "token_estimate": 187, "created_at": "2026-03-26T19:08:01+00:00", "last_used": "2026-03-26T19:08:01+00:00", "archived": false}
```

### New Command: sync diff

```bash
adaptive-cli sync diff
```

- Runs `git fetch` without merging
- Compares local SQLite row counts to remote JSONL line counts
- Shows new/changed entries per table with machine origin where available
- Recommends `sync pull` if remote has changes

### Config Resolution

1. APE defaults in `~/.adaptive-cli/config.json` (shipped with install)
2. Sync repo `config.yaml` overrides (version-controlled, travels between machines)

On `sync pull`, APE reads `config.yaml` from the repo and merges overrides into active config.

## Phase 3: Pruning, Staleness & Token Budgets

### Token Budget Defaults

In `~/.adaptive-cli/config.json`:

```json
{
  "token_budgets": {
    "preferences": 500,
    "knowledge": 3000,
    "signals": 200,
    "total": 5000
  },
  "pruning": {
    "preference": 180,
    "pattern": 90,
    "decision": 60,
    "convention": 120,
    "context": 30
  }
}
```

Overridable in sync repo `config.yaml`.

### Warning Behavior

When a domain exceeds its token threshold:
- `adaptive-cli stats` and `/ape status` show a warning line per over-budget domain
- `agent-context` output includes a `"budget_warnings"` field
- Low-confidence + over-budget entries flagged as prune candidates

### Statusline Pruning Indicator

`statusline-ape.sh` checks token totals. When any domain exceeds its threshold, a pruning icon appears in the terminal statusline. Disappears after `adaptive-cli prune` or `adaptive-cli knowledge prune` brings totals under threshold.

### Schema Additions

| Table | Column | Purpose |
|-------|--------|---------|
| `preferences` | `decay_exempt INTEGER DEFAULT 0` | Protect core preferences from pruning |
| `signals` | `machine_origin TEXT` | Track which machine recorded the signal |

Both added via schema migration (bump `schema_version`).

### Prune Command

`adaptive-cli prune` scans both preferences and knowledge:

- **Knowledge entries:** Uses `category` field to look up threshold from pruning config (e.g., `convention` -> 120 days). Formula: `days_since_last_used > category_threshold * (1 + confidence)`
- **Preferences:** Uses `last_updated` age with a flat threshold (defaults to the `preference` threshold: 180 days). Only non-exempt preferences are candidates.
- Surfaces candidates grouped by domain with staleness info
- User confirms with `y` (archive all), `n` (skip), or `select` (pick individual entries)
- On confirmation, archives entries immediately (sets `archived=1` for knowledge, removes preference from active set)

## Phase 4: Data Migration

### Migration Script

`scripts/migrate_learning.py`

**Input:** `~/learning/glouie-assistant/` (21 entries, YAML + markdown)

**Process:**
1. Read `index.yaml` for entry metadata
2. Read each markdown file from `partitions/<partition>/<slug>.md`
3. Extract content body (after YAML frontmatter)
4. Insert into APE knowledge table with `source = 'migrated'`
5. Preserve original UUIDs, timestamps, all metadata
6. Export `knowledge.jsonl` to sync repo
7. Verify round-trip: export, import, compare counts and content hashes

### Post-Migration Cleanup

In glouie-assistant repo:
1. `git tag pre-ape-migration`
2. Delete: `partitions/`, `index.yaml`, `src/`, old `config.yaml`
3. Keep: `README.md` (rewrite to describe APE sync repo)
4. Add: APE JSONL exports, new `config.yaml` with APE override format
5. Commit: `"migrate: convert learning plugin data to APE knowledge store"`
6. Push

### Verification

- 21 entries in knowledge table
- `knowledge.jsonl` has 21 lines
- Content matches original markdown bodies
- `adaptive-cli knowledge list` shows all 21
- `adaptive-cli knowledge search` finds entries by keyword

## Phase 5: Deprecation & Removal

### Remove Learning Plugin

1. Delete `~/.claude/plugins/marketplaces/gskills/plugins/learning-agent/`
2. Remove from gskills source repo if present, update `marketplace.json`

### Create /ape Unified Skill

Single entry point replacing `/learning` and `/adaptive-preferences`:

| Command | Maps to |
|---------|---------|
| `/ape status` | Combined overview: preferences, knowledge, sync, budget warnings |
| `/ape pref list/show/create` | Preference commands |
| `/ape knowledge search/show/add/list` | Knowledge commands |
| `/ape sync/diff/push/pull` | Sync commands |
| `/ape prune` | Combined pruning across both domains |
| `/ape stats` | Storage stats with token budget indicators |

### Remove /adaptive-preferences Skill

SessionStart and PreCompact hooks call `adaptive-cli` directly. Removing the skill does not break background operation.

### Update References

- Memory files: remove learning plugin references
- APE SKILL.md: rewrite for unified `/ape` skill
- APE README.md: document knowledge store and sync repo

## Phase 6: Workflow Engine

### Workflow Templates

Stored as knowledge entries with `partition: workflows/` and `category: convention`.

Example template (the "develop this" workflow):

```markdown
## Trigger Phrases
- "develop this"
- "build this out"

## Scope
- personal: glouie/* repos (full workflow with SME gates)
- production: shared repos (adds compliance checks, stricter review)

## Phases

1. Plan — AI builds implementation plan from the request
2. Plan Review — Present to user, iterate until 95% confidence
3. Spec — Write detailed spec document
4. SME Spec Review — Dispatch domain subagents, exit gate: all rate A
5. Implement — Subagent-driven development in worktrees
6. Code SME Review — Dispatch code subagents, exit gate: all rate A
7. Commit & Push
8. Create MR
9. MR Feedback Loop — exit gate: merged or pending human approval only
```

### Runtime Engine

New module `scripts/workflow_engine.py`:

1. **Trigger detection:** Search `workflows/` knowledge entries for matching trigger phrases
2. **Context scoping:** Check current repo namespace against workflow's Scope section
3. **Plan generation:** Pass template + user request to AI for concrete plan generation
4. **Phase orchestration:** Track current phase, execute action, check exit gate, advance or loop
5. **SME subagent dispatch:** At review phases, identify relevant agent types, dispatch in parallel, collect ratings
6. **State persistence:** Save progress to `~/.adaptive-cli/workflow_state.json` for session restart survival

### Per-Repo Customization

Optional `.ape-workflows.yaml` in repo root:

```yaml
develop:
  insert_after_implement:
    - name: "Security Scan"
      action: "Run skill-scanner with custom rules"
      exit_gate: "No critical or high findings"
  scope_override: production
```

### Implementation Note

Phase 6 is the largest phase and will go through its own full brainstorm, spec, plan, implement cycle when reached. This section establishes the architecture; detailed implementation is deferred.

## Implementation Approach

- All work in git worktrees for isolation
- Subagent-driven development throughout
- Phases 1-5 are the consolidation (core deliverable)
- Phase 6 is a follow-on project building on Phase 1's knowledge store
- Each phase produces testable, committable increments

## Success Criteria

- `/ape status` shows unified view of preferences + knowledge + sync
- All 21 learning entries accessible via `adaptive-cli knowledge search`
- Learning plugin fully removed, `/learning` no longer resolves
- `sync push/pull` round-trips knowledge alongside preferences
- `prune` surfaces and archives stale entries across both domains
- Statusline shows pruning indicator when budget exceeded
- Workflow template for "develop this" stored and retrievable
