"""
paths.py - Shared filesystem locations for host integrations
"""

import os
from pathlib import Path


DEFAULT_STORAGE_ENV_VAR = "ADAPTIVE_PREFS_HOME"
DEFAULT_STORAGE_DIRNAME = ".adaptive-cli"


def get_base_dir(base_dir: str = None) -> Path:
    """
    Resolve the preference storage directory.

    Precedence:
    1. Explicit base_dir argument
    2. ADAPTIVE_PREFS_HOME environment variable
    3. ~/.adaptive-cli
    """
    if base_dir:
        return Path(base_dir).expanduser()

    override = os.environ.get(DEFAULT_STORAGE_ENV_VAR)
    if override:
        return Path(override).expanduser()

    return Path.home() / DEFAULT_STORAGE_DIRNAME


def get_codex_plugins_dir() -> Path:
    """Return Codex's default local plugin directory."""
    return Path.home() / ".codex" / "plugins"


def get_codex_skills_dir() -> Path:
    """Return Codex's default local skill directory."""
    return Path.home() / ".codex" / "skills"
