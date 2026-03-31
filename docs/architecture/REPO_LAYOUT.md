# Repo Layout

This is the canonical layout note for the current repository state.

## Purpose

The repo mixes three concerns:

1. Core preference-learning runtime
2. Host adapters for Claude/Codex
3. Historical evaluation and implementation material

The goal of this doc is to make the current boundaries explicit even though the
repo still needs more cleanup.

## Current Layout

```text
scripts/                 Active runtime package and CLI
tests/                   Regression tests
plugins/                 Codex-facing plugin wrapper
.agents/                 Repo-local marketplace metadata
docs/architecture/       Canonical current architecture/layout notes
docs/ITERATION*/         Historical evaluation material
reviews/                 Local review artifacts (ignored)
```

## Current Source Of Truth

- Runtime behavior: `scripts/`
- Tests: `tests/`
- Packaging/entrypoint: `pyproject.toml`
- Current repo map: `PROJECT_STRUCTURE.md`
- Current architecture/layout note: `docs/architecture/REPO_LAYOUT.md`

## What This Repo Is Not Yet

This repo is not yet a clean `src/adaptive_preference_engine/` package. The
runtime still lives under `scripts/`, and some documentation/historical
material still creates more surface area than the product core needs.

## Next Structural Target

The likely A-grade target layout is:

```text
src/adaptive_preference_engine/
tests/
docs/architecture/
plugins/ or integrations/
```

At that point, `scripts/` would become thin entrypoints or disappear entirely.
