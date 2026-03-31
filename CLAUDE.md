# Adaptive Preference Engine

A Claude Code plugin that learns user coding preferences through implicit feedback (corrections, satisfaction signals).
Data lives at `~/.adaptive-cli/` as a SQLite database at `~/.adaptive-cli/preferences/adaptive.db`.

## Installation

```bash
pip install -e . --break-system-packages   # macOS system Python requires this flag
```

After install, `adaptive-cli` is available as a system command.

## CLI

```bash
adaptive-cli onboard          # Interactive setup tutorial (~2 min)
adaptive-cli pref list        # List learned preferences
adaptive-cli agent-context --context python  # Output JSON for agent use
adaptive-cli signal correction --task X --context Y --proposed A --corrected B --message "..."
adaptive-cli signal feedback  --task X --context Y --preferences A B --response "..."
adaptive-cli stats            # Engine statistics
adaptive-cli decay            # Apply time-decay to stale prefs
adaptive-cli recalculate      # Recalculate all preference strengths
adaptive-cli reset            # Wipe all preferences

# Sync commands (backup/restore preferences via a git repo)
adaptive-cli sync configure --repo-path <path>   # Set git repo path for sync
adaptive-cli sync push                            # Export SQLite → JSONL and git push
adaptive-cli sync pull                            # git pull and import JSONL → SQLite
adaptive-cli sync status                          # Show git status of sync repo
```

Without `pip install -e .`, use: `python -m scripts.cli <command>` from project root.

## Migration

If you have existing JSONL data from the old storage format, run the migration script to import it into SQLite:

```bash
adaptive-cli-migrate
```

This migrates old JSONL files from `~/.adaptive-cli/preferences/` into the SQLite database at `~/.adaptive-cli/preferences/adaptive.db`. The migration is idempotent — running it twice produces no duplicates.

## Gotchas

- **First run intercept**: `pref list` and `stats` trigger interactive onboarding on first use (before `~/.adaptive-cli/` exists). Run `adaptive-cli onboard` explicitly to initialize.
- **macOS pip**: `pip install ... --break-system-packages` required on Homebrew Python setups.
- **Import path**: `scripts/cli.py` inserts the project root (not `scripts/`) into `sys.path` so `from scripts.X import` resolves correctly. Fix is `Path(__file__).parent.parent`.

## Plugin Structure

```
SKILL.md                        # Claude Code skill definition (auto-loads prefs, records signals)
agents/
  signal-auditor.md             # Audit signal quality
  preference-health-checker.md  # Detect stale/conflicting preferences
  drift-detector.md             # Find shifting preferences over time
  coverage-auditor.md           # Identify contexts with no preference data
scripts/
  cli.py                        # Entry point (adaptive-cli)
  agent_hook.py                 # Python API for agent integration
  models.py                     # Core data models
  storage.py                    # SQLite persistence
  signal_processor.py           # Learning from corrections/feedback
  preference_loader.py          # Option C: diminishing-confidence chain loading
  sync.py                       # Export/import preferences to/from a git repo
  config.py                     # Persistent configuration (sync repo path, etc.)
  migrate.py                    # JSONL → SQLite migration script
```

## Testing

```bash
pytest tests/ -q                      # Full test suite (36 tests)
python demo.py                        # Full end-to-end workflow demo
python scripts/test_onboarding.py     # Onboarding unit tests (9 tests)
python scripts/test_query_index.py    # Query index tests
```

## Worktrees

Always use git worktrees for coding tasks to avoid collisions with parallel agents.
