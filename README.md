# Adaptive Preference Engine

Adaptive Preference Engine is a local preference-learning runtime for AI-assisted
workflows. It records corrections and feedback, stores learned preferences in a
local SQLite database, and exposes a CLI plus thin Claude/Codex adapters that
read and write to the same shared preference store. JSONL exports are used for
cross-machine sync via git.

## Current Status

- Shared storage path resolution via `ADAPTIVE_PREFS_HOME` or `~/.adaptive-cli`
- CLI entrypoint: `adaptive-cli`
- Runtime package surface: `scripts/`
- Tests: `python3 -m unittest discover -s tests -v`
- Host adapters:
  - Claude Code via [SKILL.md](./SKILL.md)
  - Codex via [plugins/adaptive-preferences](./plugins/adaptive-preferences)

## Key Commands

```bash
adaptive-cli onboard
adaptive-cli pref list
adaptive-cli agent-context --compact --associated-limit 5 --context python
adaptive-cli signal correction --task code_review --context python --proposed A --corrected B --message "..."
adaptive-cli signal feedback --task code_review --context python --preferences A B --response "..."
python3 -m unittest discover -s tests -v
```

## Repo Map

See [docs/REPO_MAP.md](./docs/REPO_MAP.md) for the current source-of-truth
layout. The short version is:

- [scripts](./scripts): runtime, CLI, onboarding, persistence, learning logic
- [tests](./tests): automated test suite
- [plugins](./plugins): Codex plugin/skill assets
- [.agents](./.agents): repo-local marketplace metadata
- [docs](./docs): architecture, implementation, and historical iteration docs
- [reviews](./reviews): local review artifacts; delegated-review snapshots are kept ignored locally

## Cross-Machine Sync

Preferences, signals, and Claude Code config travel between machines via a private git repo.

**First-time setup (any machine):**

```bash
# 1. Clone this repo and install
git clone <this-repo-url>
cd adaptive-preference-engine
pip install -e . --break-system-packages

# 2. Clone your personal sync repo (a private git repo you own)
git clone <your-sync-repo-url> ~/github/your-sync-repo

# 3. Point APE at it
adaptive-cli sync configure --repo-path ~/github/your-sync-repo

# 4. Pull everything down
adaptive-cli sync pull
```

`sync pull` restores:
- All learned preferences and signals (SQLite)
- `~/.claude/settings.json` (statusline, hooks, Claude Code config)
- `~/.claude/statusline-ape.sh` (the statusline script)
- `~/.claude/agents/` definitions

**Pushing updates:**

```bash
adaptive-cli sync push
```

Run this after any session where preferences changed or Claude Code config was updated.

## Notes

- This repo is actively evolving from a script-bundle shape toward a cleaner
  package/runtime boundary.
- Use git worktrees for active implementation work to avoid editable-install and
  parallel-agent collisions across checkouts.
