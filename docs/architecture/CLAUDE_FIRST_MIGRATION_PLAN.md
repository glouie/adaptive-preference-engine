# Claude-First Migration Plan

Repository target: Claude Code plugin first, Codex support second, one shared runtime.

## Goal

Restructure the repo so the real product is a host-agnostic Python library,
with Claude Code as the primary host adapter and Codex as a thinner secondary
adapter over the same runtime and storage contracts.

The main architectural outcome should be:

```text
src/adaptive_preference_engine/
  models/
  storage/
  services/
  onboarding/
  host_adapters/
    claude_code/
    codex/
  cli/
tests/
docs/architecture/
plugins/
```

## Principles

1. One core runtime, many host adapters.
2. Claude Code is the primary operating path.
3. Codex stays thin and compatibility-focused.
4. The CLI is a wrapper over core services, not the center of the architecture.
5. Docs are split by audience: architecture, operator, Claude host, Codex host.

## Current To Target Mapping

### Core model layer

- `scripts/models.py`
  -> `src/adaptive_preference_engine/models/core.py`

### Core storage layer

- `scripts/storage.py`
  -> `src/adaptive_preference_engine/storage/jsonl.py`
- `scripts/distributed_lock.py`
  -> `src/adaptive_preference_engine/storage/locking.py`
- `scripts/query_index.py`
  -> `src/adaptive_preference_engine/storage/indexing.py`
- `scripts/paths.py`
  -> `src/adaptive_preference_engine/storage/paths.py`
- `scripts/concurrency_control.py`
  -> either `src/adaptive_preference_engine/storage/transactions.py` or `experimental/concurrency_control.py`
  Decision rule: move only if it matches the real storage contract; otherwise quarantine it.

### Core service layer

- `scripts/signal_processor.py`
  -> `src/adaptive_preference_engine/services/signals.py`
- `scripts/preference_loader.py`
  -> `src/adaptive_preference_engine/services/loading.py`
- `scripts/consolidation_engine.py`
  -> `src/adaptive_preference_engine/services/consolidation.py`
- `scripts/significance_consolidation_bridge.py`
  -> `src/adaptive_preference_engine/services/significance.py`
- `scripts/significance_tester.py`
  -> `src/adaptive_preference_engine/services/statistics.py`
- `scripts/bayesian_strength_calculator.py`
  -> `src/adaptive_preference_engine/services/strength.py`
- `scripts/pattern_analyzer.py`
  -> `src/adaptive_preference_engine/services/patterns.py`
- `scripts/trend_predictor.py`
  -> `src/adaptive_preference_engine/services/trends.py`
- `scripts/suggestion_engine.py`
  -> `src/adaptive_preference_engine/services/suggestions.py`
- `scripts/auto_detector.py`
  -> `src/adaptive_preference_engine/services/detection.py`
- `scripts/agentic_loops.py`
  -> `src/adaptive_preference_engine/services/loops.py` or `experimental/agentic_loops.py`

### Onboarding and user-facing service layer

- `scripts/onboarding.py`
  -> split into:
  - `src/adaptive_preference_engine/onboarding/state.py`
  - `src/adaptive_preference_engine/onboarding/actions.py`
  - `src/adaptive_preference_engine/onboarding/tutorial.py`
- `scripts/preference_templates.py`
  -> `src/adaptive_preference_engine/onboarding/templates.py`
- `scripts/user_feedback_system.py`
  -> `src/adaptive_preference_engine/services/feedback.py`
- `scripts/user_control_panel.py`
  -> `src/adaptive_preference_engine/cli/presentation.py` or `src/adaptive_preference_engine/services/control_panel.py`
- `scripts/habit_tracker.py`
  -> `src/adaptive_preference_engine/services/habits.py`

### CLI layer

- `scripts/cli.py`
  -> split into:
  - `src/adaptive_preference_engine/cli/app.py`
  - `src/adaptive_preference_engine/cli/commands/`
  - `src/adaptive_preference_engine/cli/rendering.py`
- `scripts/cli_utils.py`
  -> `src/adaptive_preference_engine/cli/rendering.py`

### Claude host adapter

- `SKILL.md`
  -> `claude/SKILL.md`
- `CLAUDE.md`
  -> `docs/hosts/claude-code.md`
- `claude-code.config.json`
  -> `claude/claude-code.config.json`
- `agents/*.md`
  -> `claude/agents/`
- `scripts/agent_hook.py`
  -> `src/adaptive_preference_engine/host_adapters/claude_code/runtime.py`

### Codex host adapter

- `plugins/adaptive-preferences/...`
  -> `plugins/codex/adaptive-preferences/...`
- `.agents/plugins/marketplace.json`
  -> keep under `.agents/`, but document as Codex-only metadata
- Codex-specific skill docs
  -> `docs/hosts/codex.md`

### Tests

- `tests/test_cli.py`
  -> keep, but update imports to the new package path
- `tests/test_onboarding.py`
  -> split later into:
  - `tests/test_onboarding_state.py`
  - `tests/test_onboarding_actions.py`
  - `tests/test_onboarding_cli.py`
- `tests/test_query_index.py`
  -> keep under storage/indexing tests
- `tests/test_storage_reliability.py`
  -> keep under storage/reliability tests
- `tests/test_models.py`
  -> keep under model/schema tests

### Docs

- `README.md`
  -> root product overview only
- `PROJECT_STRUCTURE.md`
  -> replace with generated or manually maintained current repo map
- `QUICKSTART.md`
  -> operator quickstart only
- `docs/architecture/REPO_LAYOUT.md`
  -> current structure note
- new:
  - `docs/architecture/SYSTEM_OVERVIEW.md`
  - `docs/architecture/CLAUDE_FIRST_MIGRATION_PLAN.md`
  - `docs/hosts/claude-code.md`
  - `docs/hosts/codex.md`

## Migration Order

### Phase 1: Create package skeleton without breaking runtime

1. Add `src/adaptive_preference_engine/`.
2. Copy or move the stable model and storage primitives first.
3. Update `pyproject.toml` to package from `src/`.
4. Leave temporary compatibility shims in `scripts/` that import from `src/`.

Success criteria:
- `adaptive-cli` still works
- tests still run
- imports no longer require `scripts` as the long-term package boundary

### Phase 2: Move core services

1. Move signal processing, loading, consolidation, and statistics logic into `src/.../services/`.
2. Replace direct cross-module construction with explicit service wiring.
3. Keep CLI and host adapters calling the same services.

Success criteria:
- no behavioral drift in CLI flows
- service modules do not import host-specific docs or presentation code

### Phase 3: Split onboarding

1. Extract onboarding state persistence from tutorial copy and CLI prompts.
2. Move onboarding actions into reusable service functions.
3. Keep the CLI as the interactive shell over those actions.

Success criteria:
- onboarding tests become more granular
- completed-user and modify flows can be exercised without rendering full tutorial copy

### Phase 4: Formalize host adapters

1. Move Claude assets into `claude/`.
2. Keep Codex assets under `plugins/codex/`.
3. Define one small host contract:
   - load compact context
   - record correction
   - record feedback
   - resolve storage path

Success criteria:
- Claude remains the primary documented host
- Codex uses the same runtime APIs with a thinner compatibility layer

### Phase 5: Reduce root clutter

1. Keep only a minimal root entry set:
   - `README.md`
   - `pyproject.toml`
   - `LICENSE`
   - `src/`
   - `tests/`
   - `docs/`
   - `plugins/`
   - `claude/`
2. Move historical iteration material deeper under `docs/history/` or `docs/iterations/`.
3. Remove or replace stale structure docs.

Success criteria:
- a new contributor can identify runtime, tests, docs, and host adapters in one scan

## Compatibility Strategy

During migration, keep these temporary wrappers:

- `scripts/cli.py` imports and runs `adaptive_preference_engine.cli.app`
- `scripts/agent_hook.py` imports Claude adapter runtime from `src/`
- `scripts/preference_loader.py`, `scripts/storage.py`, and similar wrappers re-export the new implementations during the transition

Remove wrappers only after:
- CLI entrypoint is updated
- tests point at `src/`
- host adapters are stable

## Claude-First Decisions

- Claude Code remains the primary documented install and operating path.
- Root-level language should describe the product once, then point to Claude as the default host.
- Codex docs and plugin manifests should stay concise and avoid duplicating the full behavioral contract.
- Any host-specific behavior that is not required by both hosts should live under the host adapter, not in core services.

## A-Grade Exit Criteria

The migration is done when:

- the runtime lives under `src/adaptive_preference_engine/`
- the CLI is a thin wrapper over services
- Claude and Codex are thin host adapters over the same runtime contract
- onboarding state/actions/presentation are separated
- storage and significance metadata use explicit typed schemas
- root docs are reduced to a small canonical set
- tests import the library package directly and cover failure paths cleanly

## Immediate Next Step

The first concrete implementation step should be:

1. create `src/adaptive_preference_engine/`
2. move `models.py`, `paths.py`, `storage.py`, and `query_index.py`
3. update `pyproject.toml`
4. leave `scripts/` compatibility shims in place

That gets the repo onto the right structural path without forcing a full host-adapter rewrite in one jump.
