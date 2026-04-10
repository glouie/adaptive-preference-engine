"""Auto-detect session context from working directory and environment."""

import os
import subprocess
from pathlib import Path
from typing import List


UNIVERSAL_PREFIXES = [
    "workflow.git",
    "workflow.plan_execution",
    "workflow.progress_reporting",
    "workflow.memory_management",
    "workflow.persistence",
    "workflow.skills",
    "formatting.git_commits",
    "general.",
    "tools.cli",
    "tools.adaptive_cli",
]


def detect_context(cwd: str = None) -> List[str]:
    """Detect context tags from working directory."""
    tags = []
    cwd = cwd or os.getcwd()
    cwd_path = Path(cwd)

    try:
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            cwd=cwd,
        ).decode().strip()
        tags.append(Path(git_root).name)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    if (cwd_path / "pyproject.toml").exists() or (cwd_path / "setup.py").exists():
        tags.append("python")
    if (cwd_path / "package.json").exists():
        tags.append("javascript")
    if (cwd_path / "go.mod").exists():
        tags.append("go")
    if (cwd_path / "Cargo.toml").exists():
        tags.append("rust")

    claude_md = cwd_path / "CLAUDE.md"
    if claude_md.exists():
        try:
            first_line = claude_md.read_text(encoding="utf-8").split("\n")[0]
            if first_line.startswith("# "):
                project_name = first_line[2:].strip().lower()
                normalized = project_name.replace(" ", "-")
                normalized = "".join(c for c in normalized if c.isalnum() or c == "-")
                if normalized:
                    tags.append(normalized)
        except OSError:
            pass

    return tags


def is_universal_prefix(path: str, config_prefixes: List[str] = None) -> bool:
    """Check if a preference path matches a universal prefix (always loaded)."""
    prefixes = config_prefixes if config_prefixes is not None else UNIVERSAL_PREFIXES
    for prefix in prefixes:
        if path.startswith(prefix):
            return True
    return False


def matches_context(pref_path: str, context_tags: List[str], config_prefixes: List[str] = None) -> bool:
    """Check if a preference path is relevant to the given context tags."""
    if is_universal_prefix(pref_path, config_prefixes):
        return True

    path_lower = pref_path.lower()
    path_segments = set(path_lower.split("."))

    for tag in context_tags:
        tag_lower = tag.lower()
        if tag_lower in path_segments:
            return True
        if tag_lower in path_lower:
            return True

    return False
