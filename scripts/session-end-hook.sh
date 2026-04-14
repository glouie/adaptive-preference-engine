#!/usr/bin/env bash
# Session-end hook: ingest inbox, export, generate memory, push both repos.
# Runs on Claude Code Stop event. Non-blocking — errors are logged, not fatal.
set -uo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
CLI="$PLUGIN_ROOT/scripts/cli.py"
LOGDIR="$HOME/.adaptive-cli/logs"
mkdir -p "$LOGDIR"

# 1. Ingest pending inbox files
python3 "$CLI" knowledge ingest-inbox --quiet 2>>"$LOGDIR/hooks.log"
ingest_status=$?

# 2. Generate memory .md files (not required for sync, no exit tracking)
if [ -n "${CLAUDE_PROJECT_MEMORY_DIR:-}" ]; then
    python3 "$CLI" knowledge generate-memory \
        --memory-dir "$CLAUDE_PROJECT_MEMORY_DIR" --quiet 2>>"$LOGDIR/hooks.log" || true
fi

# 3. Sync push public repo
python3 "$CLI" sync push --quiet 2>>"$LOGDIR/hooks.log"
sync_public_status=$?

# 4. Sync push confidential repo (using separate script method)
python3 -c "
from pathlib import Path
from scripts.storage import ConfidentialStorageManager
from scripts.sync import ConfidentialSync
from scripts.config import AdaptiveConfig
import sys
try:
    cfg = AdaptiveConfig('$HOME/.adaptive-cli')
    conf_repo = getattr(cfg, 'confidential_sync_repo_path', None)
    if not conf_repo:
        sys.exit(0)
    conf_repo = Path(conf_repo).expanduser()
    if not conf_repo.exists():
        sys.exit(0)
    cmgr = ConfidentialStorageManager()
    counts = ConfidentialSync.export(cmgr, conf_repo)
    cmgr.close()
    # Git operations
    import subprocess
    subprocess.run(['git', 'add', 'knowledge.jsonl'], cwd=conf_repo, check=False, capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'sync: confidential knowledge'], cwd=conf_repo, check=False, capture_output=True)
    subprocess.run(['git', 'push'], cwd=conf_repo, check=False, capture_output=True)
except Exception as e:
    print(f'confidential sync failed: {e}', file=sys.stderr)
    sys.exit(1)
" 2>>"$LOGDIR/hooks.log"
sync_conf_status=$?

# 5. Clear inbox only if ingest succeeded and at least public sync succeeded
if [ $ingest_status -eq 0 ] && [ $sync_public_status -eq 0 ]; then
    rm -f "$HOME/.adaptive-cli/memory-inbox/"*.md 2>>"$LOGDIR/hooks.log" || true
fi
