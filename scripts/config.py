"""
config.py — Persistent configuration for adaptive-preference-engine.

Config file: <base_dir>/config.json
Currently stores:
  sync_repo_path: str | None   — path to the git repo containing JSONL exports
"""

import json
import os
from pathlib import Path
from typing import Optional


class AdaptiveConfig:
    """Read/write ~/.adaptive-cli/config.json."""

    def __init__(self, base_dir=None) -> None:
        if base_dir is None:
            base_dir = os.path.expanduser("~/.adaptive-cli")
        self._path = Path(base_dir) / "config.json"
        self._data = self._load()

    @property
    def sync_repo_path(self) -> Optional[str]:
        return self._data.get("sync_repo_path")

    @sync_repo_path.setter
    def sync_repo_path(self, value: Optional[str]) -> None:
        self._data["sync_repo_path"] = value
        self._save()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except json.JSONDecodeError as e:
                print(
                    f"WARNING: Config file is malformed and will be ignored: {self._path}\n"
                    f"  Parse error: {e}\n"
                    f"  Delete it to reset: {self._path}"
                )
                return {}
            except OSError as e:
                print(f"WARNING: Could not read config file {self._path}: {e}")
                return {}
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        os.replace(tmp, self._path)
