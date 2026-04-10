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

    @property
    def buddy_enabled(self) -> bool:
        return bool(self._data.get("buddy_enabled", False))

    @buddy_enabled.setter
    def buddy_enabled(self, value: bool) -> None:
        self._data["buddy_enabled"] = value
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


# ── APE Layered Config ──────────────────────────────────────────────────────

_DEFAULTS = {
    "token_budgets": {
        "preferences": 500,
        "knowledge": 3000,
        "partition": 1000,
        "context_injection": 2000,
        "signals": 200,
        "total": 5000,
    },
    "pruning": {
        "preference": 180,
        "pattern": 90,
        "decision": 60,
        "convention": 120,
        "context": 30,
    },
    "universal_prefixes": [
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
    ],
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override wins on conflicts."""
    merged = dict(base)
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


class APEConfig:
    """Layered configuration: defaults < config.json < sync repo config.yaml."""

    def __init__(self, data: dict) -> None:
        self._data = data

    @classmethod
    def load(cls, base_dir: str, sync_repo_path: Optional[str] = None) -> "APEConfig":
        import copy
        data = copy.deepcopy(_DEFAULTS)

        config_json = Path(base_dir) / "config.json"
        if config_json.exists():
            try:
                with open(config_json) as f:
                    local = json.load(f)
                data = _deep_merge(data, local)
            except (json.JSONDecodeError, OSError):
                pass

        if sync_repo_path:
            config_yaml = Path(sync_repo_path) / "config.yaml"
            if config_yaml.exists():
                try:
                    import yaml
                    with open(config_yaml) as f:
                        remote = yaml.safe_load(f) or {}
                    data = _deep_merge(data, remote)
                except ImportError:
                    pass

        return cls(data)

    def get(self, dotpath: str, default=None):
        """Dot-path access: config.get('token_budgets.knowledge', 3000)."""
        keys = dotpath.split(".")
        obj = self._data
        for key in keys:
            if isinstance(obj, dict) and key in obj:
                obj = obj[key]
            else:
                return default
        return obj

    @property
    def data(self) -> dict:
        return self._data

    @staticmethod
    def save_defaults(base_dir: str) -> None:
        """Write config.json with defaults if it doesn't exist."""
        config_path = Path(base_dir) / "config.json"
        if not config_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w") as f:
                json.dump(_DEFAULTS, f, indent=2)
