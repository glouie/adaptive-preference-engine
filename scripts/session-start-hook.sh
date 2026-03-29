#!/usr/bin/env bash
# Adaptive Preference Engine — SessionStart Hook
# Loads learned preferences based on the current project context.
# Outputs a summary for Claude's system context.

set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
ADAPTIVE_DIR="$HOME/.adaptive-cli"
CLI="$PLUGIN_ROOT/scripts/cli.py"

# Detect context from working directory
context_tags="general"
if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    cd "$CLAUDE_PROJECT_DIR" 2>/dev/null || true
fi

if git rev-parse --git-dir > /dev/null 2>&1; then
    repo=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)")
    context_tags="$repo"

    # Detect language
    if [ -f "package.json" ]; then
        context_tags="$context_tags javascript"
    elif [ -f "requirements.txt" ] || [ -f "pyproject.toml" ] || [ -f "setup.py" ]; then
        context_tags="$context_tags python"
    elif [ -f "go.mod" ]; then
        context_tags="$context_tags go"
    elif [ -f "Cargo.toml" ]; then
        context_tags="$context_tags rust"
    fi
fi

# Initialize data directory if needed
if [ ! -d "$ADAPTIVE_DIR/preferences" ]; then
    mkdir -p "$ADAPTIVE_DIR/preferences" "$ADAPTIVE_DIR/backups"
    echo "Adaptive preferences: initialized $ADAPTIVE_DIR"
    exit 0
fi

# Load preferences for this context
prefs=$(python3 "$CLI" agent-context --context $context_tags 2>/dev/null || echo "")
stat_line=$(python3 "$CLI" stats 2>/dev/null | head -3 || echo "")

pref_count=$(echo "$stat_line" | grep -o '[0-9]* preferences' | head -1 || echo "0 preferences")
signal_count=$(echo "$stat_line" | grep -o '[0-9]* signals' | head -1 || echo "0 signals")

echo "Adaptive preferences: ${pref_count}, ${signal_count} | context=${context_tags}"
