import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from scripts.paths import get_base_dir

_FILENAME = "assoc_meta.json"


@dataclass
class AssocMeta:
    last_run_at: Optional[str]
    signals_since_last_run: int

    @property
    def is_stale(self) -> bool:
        return self.signals_since_last_run > 0

    @staticmethod
    def load(base_dir: Optional[Path] = None) -> "AssocMeta":
        path = (base_dir or get_base_dir()) / _FILENAME
        try:
            data = json.loads(path.read_text())
            return AssocMeta(
                last_run_at=data.get("last_run_at"),
                signals_since_last_run=int(data.get("signals_since_last_run", 0)),
            )
        except (OSError, json.JSONDecodeError, ValueError, KeyError):
            return AssocMeta(last_run_at=None, signals_since_last_run=0)

    def increment(self, base_dir: Optional[Path] = None) -> None:
        self.signals_since_last_run += 1
        self._save(base_dir)

    def reset(self, base_dir: Optional[Path] = None) -> None:
        self.signals_since_last_run = 0
        self.last_run_at = datetime.now().isoformat()
        self._save(base_dir)

    def _save(self, base_dir: Optional[Path] = None) -> None:
        path = (base_dir or get_base_dir()) / _FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "last_run_at": self.last_run_at,
            "signals_since_last_run": self.signals_since_last_run,
        }))
