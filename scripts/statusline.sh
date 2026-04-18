#!/bin/bash
# APE statusline segment for Claude Code
# Outputs: "🐒 21p 2a 2b 32s 31k" (buddy enabled) or "APE: 21p 2a 2b 32s 31k" (buddy disabled)

# Exit silently on any error
set +e

# Resolve paths relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_SCRIPT="$SCRIPT_DIR/cli.py"
CONFIG_PATH="$HOME/.adaptive-cli/config.json"
BUDDY_PATH="$HOME/.claude/agents/ape-buddy.md"

# Check if APE is installed
[ ! -d "$HOME/.adaptive-cli" ] && exit 0
[ ! -f "$CLI_SCRIPT" ] && exit 0

# Check buddy status
buddy_enabled=false
if [ -f "$CONFIG_PATH" ]; then
  # Quick JSON parse for buddy_enabled using python3
  buddy_enabled=$(python3 -c "
import json, sys
try:
    with open('$CONFIG_PATH') as f:
        data = json.load(f)
    print('true' if data.get('buddy_enabled', False) else 'false')
except:
    print('false')
" 2>/dev/null)
fi

# Determine prefix
prefix="APE:"
if [ "$buddy_enabled" = "true" ] && [ -f "$BUDDY_PATH" ]; then
  prefix="🦧"
fi

# Get stats from CLI
stats=$(cd "$HOME/.adaptive-cli" && python3 "$CLI_SCRIPT" stats --oneline 2>/dev/null)
[ -z "$stats" ] && exit 0

# Output with prefix
echo "$prefix $stats"
