# ~/.ape-confidential Local Confidential Store Design

**Date:** 2026-04-18
**Status:** Draft
**Supersedes:** `~/gitlab/gskills/.ape-confidential/` reference in 2026-04-14 temporal-memory-consolidation design

## Problem

The 2026-04-14 design introduced a confidential store backed by `~/gitlab/gskills/.ape-confidential/` — a subdirectory inside a private GitLab repo. That repo was never created on this machine. As a result:

- `ape-confidential.db` does not exist
- No confidential knowledge has ever been persisted
- The `is_confidential()` classifier routes entries correctly at write time, but they are silently dropped because there is no backing store configured
- `cmd_sync_push` / `cmd_sync_pull` never call `ConfidentialSync` — the confidential repo is not wired into the sync commands

## Goals

1. Create `~/.ape-confidential` as a local-only git repo — the confidential store for this machine.
2. Update `confidential.repo_path` in config from `~/gitlab/gskills` → `~/.ape-confidential`, and `store_dir` from `.ape-confidential` → `.`.
3. Wire `ConfidentialSync` into `cmd_sync_push` and `cmd_sync_pull` so both stores are synced in one command.
4. Initialize the repo with the same full-schema JSONL structure as `glouie-assistant` so the format is consistent and ready for any future table routing.

## Non-Goals

- Adding a remote to `~/.ape-confidential`. It is local-only. No `git push` to a remote.
- Routing preferences/signals/associations to the confidential store. The current 21 preferences contain no PII. Preference-level routing is deferred until there is actual private preference data.
- Encrypting `ape-confidential.db` at rest. Threat model is sync destination (remote repos), not local disk.

## Design

### 1. Repo Structure

`~/.ape-confidential` is a standalone git repo. It mirrors the glouie-assistant format so the same tooling handles both stores.

```
~/.ape-confidential/
  all_preferences.jsonl    # reserved — empty today, available for future private prefs
  associations.jsonl       # reserved — empty today
  contexts.jsonl           # reserved — empty today
  signals.jsonl            # reserved — empty today
  knowledge.jsonl          # active — confidential knowledge entries
  config.yaml              # machine-local APE config overrides (not overriding today)
  index.yaml               # entry catalog matching glouie-assistant format
  .gitignore               # ignore *.db, *.tmp, *.lock
```

No `remote` is configured. `git log` serves as the audit trail. Every push to the public `glouie-assistant` is paired with a local commit here for the confidential side.

### 2. Config Changes

`~/.adaptive-cli/config.json` gains a `confidential` override block:

```json
{
  "buddy_enabled": true,
  "sync_repo_path": "/Users/glouie/github/glouie-assistant",
  "confidential": {
    "repo_path": "~/.ape-confidential",
    "store_dir": "."
  }
}
```

`APEConfig.load()` already deep-merges `config.json` over `_DEFAULTS`, so these keys override the `~/gitlab/gskills` defaults without touching any Python code.

`store_dir: "."` means `ConfidentialSync.export()` writes directly to the repo root — no `.ape-confidential/` subdirectory needed since the whole repo is dedicated to this purpose.

### 3. Sync Wiring

`cmd_sync_push` and `cmd_sync_pull` in `cli.py` currently only call `SyncRunner` (public store). Both commands need a second pass for the confidential store.

**Push flow (extended):**
1. `SyncRunner(public_mgr, sync_repo_path).push()` — existing behavior, unchanged
2. Read `confidential.repo_path` from `APEConfig`
3. If repo exists: `ConfidentialSync.export(conf_mgr, conf_repo)` → git add + commit in `conf_repo` (no push — local-only)
4. Report counts for both stores

**Pull flow (extended):**
1. `SyncRunner(public_mgr, sync_repo_path).pull()` — existing behavior, unchanged
2. If confidential repo exists: `ConfidentialSync.import_from(conf_mgr, conf_repo)` (no git pull — local-only, nothing to pull from)

The git operations (add + commit) for the confidential repo are inlined in `cmd_sync_push` after `ConfidentialSync.export()` — the same subprocess calls `SyncRunner` uses, but targeting `~/.ape-confidential` and skipping `git push`. If this grows complex, extract a `ConfidentialSyncRunner` mirroring `SyncRunner` — but the current scope does not require it.

### 4. Initialization Steps

These are one-time setup steps executed as part of the implementation:

1. `git init ~/.ape-confidential` with initial commit containing empty JSONL files, `config.yaml`, `index.yaml`, and `.gitignore`.
2. Write `confidential` block into `~/.adaptive-cli/config.json`.
3. Touch `~/.adaptive-cli/ape-confidential.db` by instantiating `ConfidentialStorageManager` once — this creates the SQLite schema.
4. Run `adaptive-cli sync push` to verify the confidential export path works end-to-end.

### 5. index.yaml Format

Matches the glouie-assistant structure exactly:

```yaml
entries: []
```

Populated at export time when there are knowledge entries to catalog. Each entry in the catalog mirrors the glouie-assistant shape:

```yaml
entries:
  - id: <entry id>
    partition: <partition>
    category: <category>
    title: <title>
    tags: [...]
    confidence: 1.0
    created_at: <ISO timestamp>
    last_used: <ISO timestamp>
    access_count: 0
    decay_exempt: false
    file_path: knowledge.jsonl
    token_estimate: <n>
```

The `file_path` field always points to `knowledge.jsonl` since all confidential entries live in one file (no partitioned subdirectory needed at this scale).

`index.yaml` is regenerated by `ConfidentialSync.export()` on every push — it reflects the full catalog of entries currently in `ape-confidential.db`. It is not hand-edited.

### 6. config.yaml

Minimal stub — exists so APEConfig can load machine-local overrides from this repo if needed in the future:

```yaml
# Machine-local APE config overrides for ~/.ape-confidential
# Add overrides here as key: value pairs matching APEConfig structure.
# This file is merged over ~/.adaptive-cli/config.json at load time.
```

No active overrides today.

## Data Flow

```
write knowledge entry
  └─ is_confidential(content)?
       ├─ yes → ConfidentialStorageManager → ape-confidential.db
       └─ no  → PreferenceStorageManager  → adaptive.db (ape.db future)

adaptive-cli sync push
  ├─ SyncRunner.push()         → glouie-assistant/ (git push to remote)
  └─ ConfidentialSync.export() → ~/.ape-confidential/ (git commit, no push)

adaptive-cli sync pull
  ├─ SyncRunner.pull()               → import from glouie-assistant/
  └─ ConfidentialSync.import_from()  → import from ~/.ape-confidential/ (local read only)
```

## Confidential Classification Patterns

Current patterns from `confidential_classifier.py` and `config.py` defaults:

| Pattern | Rationale |
|---|---|
| `~/notes-vault` | Personal notes vault — local path |
| `~/learning/` | Local learning directory |
| `/Users/` | Any absolute macOS home path |
| `cd.splunkdev.com` | Splunk internal domain |
| `@cisco.com` | Cisco email addresses |

These are unchanged. The `~/.ape-confidential` repo is the destination for entries matching any of these patterns.

## Testing

```bash
# Verify confidential DB is created
adaptive-cli knowledge add --title "test" --content "/Users/glouie/local-path" --partition test
sqlite3 ~/.adaptive-cli/ape-confidential.db "SELECT title FROM knowledge;"

# Verify sync push commits to confidential repo
adaptive-cli sync push
git -C ~/.ape-confidential log --oneline -3

# Verify knowledge.jsonl is populated
cat ~/.ape-confidential/knowledge.jsonl
```
