# Knowledge Compaction & Index-Reference Design

**Date:** 2026-04-08
**Status:** Approved
**Supersedes:** None (new feature)

## Problem

APE's knowledge store grows monotonically. Every new learning adds tokens, but the token budget is fixed (default 3000). The existing `prune` command only catches entries unused for 180+ days — it does not help with actively-used knowledge that accumulates. The `[prune]` statusline warning fires when knowledge exceeds the budget, but there is no automated way to reduce it.

## Goals

1. Keep knowledge token usage under budget automatically, without user intervention.
2. Preserve all knowledge content — nothing is lost, just reorganized.
3. Make full knowledge content available on-demand when session context matches.
4. Operate silently — APE should be invisible infrastructure, not another thing to manage.

## Non-Goals

- LLM-summarized compaction (future work — option 3 from brainstorming).
- Manual consolidation commands (the trigger is automatic).
- Changing the prune command behavior (prune handles staleness, compaction handles growth).

## Design

### Schema Change

Add one nullable column to the `knowledge` table:

```sql
ALTER TABLE knowledge ADD COLUMN ref_path TEXT;
```

- `ref_path = NULL` — content lives in the `content` column (current behavior, unchanged).
- `ref_path = "<relative_path>"` — `content` holds a short summary (~30-50 tokens), full content is in the sync repo at that path relative to the sync repo root.

`token_estimate` is recomputed after compaction to reflect only the summary size.

### Trigger Flow

Compaction is triggered after every `knowledge add` and after `sync pull` imports new entries.

```
knowledge add / sync pull
       |
       v
  Calculate global token total
       |
       v
  Over global budget? ---- No ---- Done
       |
      Yes
       v
  Find partitions over their partition threshold
       |
       v
  Any violating partitions? ---- Yes ---- Compact that partition
       |                                        |
      No                                        v
       |                                   Re-check global budget
       v                                        |
  Global compact: pick largest              Still over? ---- Yes ---- Loop
  partition first, compact it                   |
       |                                       No
       v                                        |
  Re-check global budget                      Done
       |
  Still over? ---- Yes ---- Pick next largest partition
       |
      No
       |
     Done
```

**Priority chain:**
1. Global budget is the trigger (always).
2. Check which partitions exceed their partition threshold — compact those first.
3. If no partition is individually over but global still breaches — compact globally (largest partition first).

**Partition threshold:** New config key `token_budgets.partition` (default: 1000 tokens). Overridable per-partition in config.

**Loop safety:** Max 5 compaction rounds per trigger. If still over after 5, log a warning.

### Config Additions

```yaml
token_budgets:
  preferences: 500
  knowledge: 3000
  partition: 1000       # new: per-partition default
  context_injection: 2000  # new: max tokens injected into sessions
  signals: 200
  total: 5000
```

### Compaction Process

When a partition is selected for compaction:

**Step 1 — Gather entries.**
Collect all non-archived entries in the partition with `ref_path = NULL`. If only 1 entry, skip.

**Step 2 — Write full content to ref file.**
Concatenate entries into a structured markdown file using each entry's title as a section header:

```markdown
# Knowledge: projects/webex-notes

## Project Context
(content from entry 1)

## Key Files
(content from entry 2)

## TUI Keybindings
(content from entry 3)
```

Write to `<sync_repo>/partitions/<partition>/consolidated.md`. If the file exists (re-compaction), overwrite — git history preserves the old version.

**Step 3 — Replace DB entries with one index entry.**
- Archive the original entries (`archived=1`).
- Create one new consolidated entry:
  - `id`: `compact_<partition_slug>_<timestamp>`
  - `partition`: same as originals
  - `title`: `"<Partition Name> (consolidated)"`
  - `content`: one-line summary per original entry, e.g. `"Project context, key files, TUI keybindings, completed features, note network ecosystem"`
  - `ref_path`: relative path to the consolidated markdown file
  - `token_estimate`: `len(content) // 4` (summary only)
  - `tags`: union of all original entry tags
  - `decay_exempt`: `True`
  - `confidence`: max confidence from originals

**Step 4 — Auto-commit sync repo.**
```bash
git -C <sync_repo> add partitions/<partition>/consolidated.md
git -C <sync_repo> commit -m "ape: compact <partition> (N entries -> 1, saved Xt)"
```

### Re-Compaction

When new entries are added to an already-compacted partition:
1. The new entries exist alongside the consolidated entry.
2. If compaction triggers again, the system gathers only `ref_path = NULL` entries (the new ones).
3. It reads the existing `consolidated.md`, appends the new entries as new sections, overwrites the file.
4. Archives the new entries, updates the consolidated entry's `content` summary and `tags`.
5. Commits to sync repo — git diff shows exactly what was added.

### Reading Compacted Entries

**`knowledge show <entry>`** — Detects `ref_path`, reads the file from the sync repo, displays full content. Shows a note: `(loaded from <ref_path>)`.

**`knowledge list`** — Shows summary content and token estimate as usual. Compacted entries display with a `[ref]` indicator next to the title.

**`knowledge search`** — Searches summary content in the DB only. Does not search inside ref files. Fast, O(n) on DB rows.

**`stats --oneline`** — Token budget counts only summaries. `[prune]` disappears once compaction brings totals under budget.

**`sync push/pull`** — JSONL export includes the `ref_path` field. Ref files travel via the sync repo's git push/pull. On `sync pull`, if a JSONL entry has `ref_path` but the file does not exist locally, log a warning.

### Knowledge Context Injection

Currently `load_for_agent` only loads preferences. This design extends it to also load relevant knowledge.

**When:** During `agent-context` generation and the session-start hook.

**Matching:** Compare entry `tags` and `partition` against the session's `context_tags`.

**Loading:**
- Matched entry with `ref_path = NULL` — inject `content` directly.
- Matched entry with `ref_path` set — read the ref file from the sync repo, inject full content.
- Non-matching entries — skipped entirely (zero tokens).

**Token guard:** New config key `token_budgets.context_injection` (default: 2000 tokens). If matched entries exceed this, prioritize by:
1. Partition exactly matches a context tag.
2. Higher confidence.
3. Higher access count.
4. Truncate the rest.

**Output format:** Add a `knowledge` key to the agent context JSON:

```json
{
  "primary_preference": { "..." : "..." },
  "associated_preferences": [ "..." ],
  "knowledge": [
    {
      "title": "Key Files",
      "partition": "projects/webex-notes",
      "content": "...(full content from ref file or DB)...",
      "source": "ref_file"
    }
  ]
}
```

### Safety

- **Git history is the revert mechanism.** Every compaction is a commit. `git revert` restores the previous consolidated file. Archived entries remain in the DB and can be restored via `knowledge restore`.
- **Loop cap:** Max 5 compaction rounds per trigger.
- **No data loss:** Original entries are archived, not deleted. Full content is in the ref file. Both are recoverable.
- **Sync repo required:** Compaction only fires if `sync_repo_path` is configured. If not set, log a warning and skip — the system degrades to current behavior.

### Migration

Existing entries are unaffected. `ref_path` defaults to `NULL`. The `ALTER TABLE ADD COLUMN` is applied on first access (SQLite supports this without data migration). No existing entries are compacted until the next `knowledge add` triggers a budget check.

## Example

Current state (16 entries, 3775 tokens, over 3000 budget):

```
projects/webex-notes/  — 5 entries, 956 tokens  [over 1000? no, but largest]
user/                  — 2 entries, 811 tokens
domains/tools/         — 3 entries, 754 tokens
projects/note-core/    — 2 entries, 477 tokens
projects/ncc-cinc-agent/ — 1 entry, 329 tokens
domains/textual-tui/   — 1 entry, 233 tokens
workflows/develop/     — 1 entry, 164 tokens
projects/skills-marketplace/ — 1 entry, 51 tokens
```

Global budget (3000) breached. No single partition exceeds 1000. Global compact triggers:
1. Compact `projects/webex-notes/` (largest, 956t) → ~40t summary + ref file. Saved ~916t.
2. Re-check: 3775 - 916 = 2859t. Under 3000. Done.

Result: 12 active entries, 2859 tokens. `[prune]` gone. Full webex-notes content accessible via ref file when session context includes `webex-notes`.
