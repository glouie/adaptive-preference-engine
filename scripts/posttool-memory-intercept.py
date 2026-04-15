#!/usr/bin/env python3
"""PostToolUse hook: copy memory writes to inbox for batched ingestion.

Reads hook JSON from stdin. If the tool wrote to a memory directory,
copies the file to ~/.adaptive-cli/memory-inbox/ with an atomic
temp-file + rename. Does NOT ingest into APE — that happens at
session boundaries.

Exit 0 always (non-blocking hook).
"""

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        return

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return

    # Only intercept memory directory writes
    if "/memory/" not in file_path:
        return

    # Skip MEMORY.md index
    if file_path.endswith("MEMORY.md"):
        return

    # Extract project hash from path: .../projects/<hash>/memory/<file>
    match = re.search(r'/projects/([^/]+)/memory/([^/]+)$', file_path)
    if not match:
        return

    project_hash = match.group(1)
    basename = match.group(2)
    unique_name = f"{project_hash}_{basename}"

    # Determine inbox path
    inbox_dir = os.environ.get(
        "ADAPTIVE_CLI_INBOX",
        os.path.expanduser("~/.adaptive-cli/memory-inbox"),
    )
    inbox = Path(inbox_dir)
    inbox.mkdir(parents=True, exist_ok=True)

    source = Path(file_path)
    if not source.exists():
        return

    # Atomic copy: temp file + rename
    target = inbox / unique_name
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=f".{unique_name}.", suffix=".tmp", dir=str(inbox)
    )
    try:
        with os.fdopen(tmp_fd, 'wb') as f:
            f.write(source.read_bytes())
        os.rename(tmp_path, str(target))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


if __name__ == "__main__":
    main()
