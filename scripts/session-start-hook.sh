#!/usr/bin/env bash
# Adaptive Preference Engine — SessionStart Hook
# Loads hot-tier preferences matching the current project context.
# Uses --auto-detect for context detection and tier-filtered loading.

set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
ADAPTIVE_DIR="$HOME/.adaptive-cli"
CLI="$PLUGIN_ROOT/scripts/cli.py"

if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    cd "$CLAUDE_PROJECT_DIR" 2>/dev/null || true
fi

# Initialize data directory if needed
if [ ! -d "$ADAPTIVE_DIR/preferences" ]; then
    mkdir -p "$ADAPTIVE_DIR/preferences" "$ADAPTIVE_DIR/backups"
    echo "Adaptive preferences: initialized $ADAPTIVE_DIR"
    exit 0
fi

# --- Temporal expiry: archive expired entries in both DBs ---
python3 "$CLI" knowledge expire --quiet 2>/dev/null || true

# --- Inbox: ingest any pending memory files from crashed sessions ---
python3 "$CLI" knowledge ingest-inbox --quiet 2>/dev/null || true

# --- Memory generation: generate .md files for Claude Code ---
# Discover project memory directory
CLAUDE_PROJECT_MEMORY_DIR=""
for dir in "$HOME/.claude/projects"/*/memory; do
    if [ -d "$dir" ]; then
        project_dir="$(dirname "$dir")"
        if [ -f "$project_dir/.project_path" ]; then
            stored_path="$(cat "$project_dir/.project_path" 2>/dev/null)"
            if [ "$stored_path" = "$PWD" ]; then
                CLAUDE_PROJECT_MEMORY_DIR="$dir"
                break
            fi
        fi
    fi
done
export CLAUDE_PROJECT_MEMORY_DIR

if [ -n "$CLAUDE_PROJECT_MEMORY_DIR" ]; then
    python3 "$CLI" knowledge generate-memory \
        --memory-dir "$CLAUDE_PROJECT_MEMORY_DIR" --quiet 2>/dev/null || true
fi

# Load hot-tier preferences with auto-detected context
prefs=$(python3 "$CLI" agent-context --auto-detect 2>/dev/null || echo "")
stat_line=$(python3 "$CLI" stats --oneline 2>/dev/null || echo "")

# Extract context tags from auto-detect output for status line
context_tags=$(echo "$prefs" | python3 -c "import sys,json; d=json.load(sys.stdin); print(','.join(d.get('context_tags',[])))" 2>/dev/null || echo "unknown")

if [ -n "$stat_line" ]; then
    echo "Adaptive preferences: ${stat_line} | context=${context_tags}"
else
    echo "Adaptive preferences: 0 preferences, 0 signals | context=${context_tags}"
fi
