#!/usr/bin/env bash
# Session-end hook: ingest inbox, export, generate memory, push both repos.
# Runs on Claude Code Stop event. Non-blocking — errors are logged, not fatal.
set -uo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
CLI="$PLUGIN_ROOT/scripts/cli.py"

# 1. Ingest pending inbox files
python3 "$CLI" knowledge ingest-inbox --quiet 2>/dev/null || true

# 2. Generate memory .md files
if [ -n "${CLAUDE_PROJECT_MEMORY_DIR:-}" ]; then
    python3 "$CLI" knowledge generate-memory \
        --memory-dir "$CLAUDE_PROJECT_MEMORY_DIR" --quiet 2>/dev/null || true
fi

# 3. Sync push (handles both public and confidential repos)
python3 "$CLI" sync push --quiet 2>/dev/null || true

# 4. Clear inbox
rm -f "$HOME/.adaptive-cli/memory-inbox/"*.md 2>/dev/null || true
