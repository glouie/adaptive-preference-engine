# Project Structure

This file is a lightweight pointer. The current source-of-truth repo map lives
at [docs/REPO_MAP.md](./docs/REPO_MAP.md).

## Top-Level Layout

```text
adaptive-preference-engine/
├── README.md
├── QUICKSTART.md
├── PROJECT_STRUCTURE.md
├── pyproject.toml
├── SKILL.md
├── CLAUDE.md
├── scripts/
├── tests/
├── plugins/
├── .agents/
├── docs/
└── reviews/
```

## Directory Roles

- `scripts/`: runtime implementation, CLI, onboarding, persistence, learning
- `tests/`: automated tests
- `plugins/`: Codex plugin and skill assets
- `.agents/`: repo-local plugin marketplace metadata
- `docs/`: architecture, implementation, and historical iteration docs
- `reviews/`: local review artifacts; delegated-review snapshots are locally ignored

## Important Caveat

The runtime still lives under `scripts/`, which is one of the active structural
issues in the repo. The target direction is a cleaner library-first package
boundary.
