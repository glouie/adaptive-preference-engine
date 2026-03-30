# Adaptive Preference Engine

A Claude Code plugin that learns user coding preferences through implicit feedback (corrections, satisfaction signals).
Data lives at `~/.adaptive-cli/` as plain JSONL files.

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
```

Without `pip install -e .`, use: `python -m scripts.cli <command>` from project root.

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
  storage.py                    # JSONL persistence
  signal_processor.py           # Learning from corrections/feedback
  preference_loader.py          # Option C: diminishing-confidence chain loading
```

## Testing

```bash
python demo.py                        # Full end-to-end workflow demo
python scripts/test_onboarding.py     # Onboarding unit tests (9 tests)
python scripts/test_query_index.py    # Query index tests
```

## Worktrees

Always use git worktrees for coding tasks to avoid collisions with parallel agents.
