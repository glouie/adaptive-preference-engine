# Repo Map

This is the current source-of-truth layout for the repository.

## Runtime

- [scripts/cli.py](../scripts/cli.py): CLI entrypoint and command handlers
- [scripts/onboarding.py](../scripts/onboarding.py): onboarding flow and setup management
- [scripts/storage.py](../scripts/storage.py): JSONL persistence and high-level storage manager
- [scripts/query_index.py](../scripts/query_index.py): in-memory and persisted query indexing
- [scripts/signal_processor.py](../scripts/signal_processor.py): correction and feedback processing
- [scripts/preference_loader.py](../scripts/preference_loader.py): host-facing preference loading and compact agent-context output
- [scripts/models.py](../scripts/models.py): core data models
- [scripts/paths.py](../scripts/paths.py): shared storage and Codex path resolution

## Tests

- [tests/test_cli.py](../tests/test_cli.py): CLI regression coverage
- [tests/test_onboarding.py](../tests/test_onboarding.py): onboarding regression coverage
- [tests/test_query_index.py](../tests/test_query_index.py): query-index correctness and persistence checks
- [tests/test_models.py](../tests/test_models.py): model/schema persistence checks
- [tests/test_storage_reliability.py](../tests/test_storage_reliability.py): malformed JSON and storage cleanup behavior

## Host Adapters

- [SKILL.md](../SKILL.md): Claude skill
- [CLAUDE.md](../CLAUDE.md): Claude-oriented operator docs
- [plugins/adaptive-preferences](../plugins/adaptive-preferences): Codex plugin and skill assets
- [.agents/plugins/marketplace.json](../.agents/plugins/marketplace.json): repo-local Codex marketplace metadata

## Docs

- [README.md](../README.md): repo overview
- [QUICKSTART.md](../QUICKSTART.md): short operator path
- [PROJECT_STRUCTURE.md](../PROJECT_STRUCTURE.md): pointer to this file
- [docs/IMPLEMENTATION](./IMPLEMENTATION): implementation/history material
- [docs/FRAMEWORKS](./FRAMEWORKS): prior review frameworks
- [docs/ITERATION1_EVALUATION](./ITERATION1_EVALUATION): historical iteration artifacts
- [docs/ITERATION2_EVALUATION](./ITERATION2_EVALUATION): historical iteration artifacts

## Local Artifacts

- [reviews](../reviews): review outputs
- delegated-review delta snapshots are stored locally and ignored from git

## Known Structural Debt

- The runtime still lives under `scripts/` instead of a library-first `src/` package.
- Some docs are still host- or history-heavy relative to the product core.
- The top-level surface is cleaner than before, but still broader than ideal.
