# Adaptive Preference Engine

Adaptive Preference Engine is a local preference-learning runtime for AI-assisted
workflows. It records corrections and feedback, stores learned preferences as
JSONL data, and exposes a CLI plus thin Claude/Codex adapters that read and
write to the same shared preference store.

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

## Notes

- This repo is actively evolving from a script-bundle shape toward a cleaner
  package/runtime boundary.
- Use git worktrees for active implementation work to avoid editable-install and
  parallel-agent collisions across checkouts.
