"""
sync.py — Export/import preferences between local SQLite and a git repo.

Workflow for push:
  1. export() — dump all SQLite tables to JSONL files in the sync repo dir
  2. git_push() — git add + commit + push in the sync repo

Workflow for pull:
  1. git_pull() — git pull in the sync repo
  2. import_from() — upsert JSONL files from sync repo into local SQLite

The export format is plain JSONL (one JSON object per line), identical to
the old storage format, so the files are human-readable and git-diffable.
"""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict

from scripts.models import Association, ContextStack, Preference, Signal
from scripts.storage import PreferenceStorageManager


class PreferenceSync:
    """Static helpers for export/import. Git operations in SyncRunner."""

    @staticmethod
    def export(mgr: PreferenceStorageManager, dest_dir: Path) -> Dict[str, int]:
        """
        Dump all SQLite data to JSONL files in dest_dir.
        Returns counts of records written per table.
        """
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        counts: Dict[str, int] = {}

        prefs = mgr.preferences.get_all_preferences()
        _write_jsonl(dest_dir / "all_preferences.jsonl", [p.to_dict() for p in prefs])
        counts["preferences"] = len(prefs)

        assocs = mgr.associations.get_all_associations()
        _write_jsonl(dest_dir / "associations.jsonl", [a.to_dict() for a in assocs])
        counts["associations"] = len(assocs)

        ctxs = mgr.contexts.get_all_contexts()
        _write_jsonl(dest_dir / "contexts.jsonl", [c.to_dict() for c in ctxs])
        counts["contexts"] = len(ctxs)

        sigs = mgr.signals.get_all_signals()
        _write_jsonl(dest_dir / "signals.jsonl", [s.to_dict() for s in sigs])
        counts["signals"] = len(sigs)

        return counts

    @staticmethod
    def import_from(mgr: PreferenceStorageManager, src_dir: Path) -> Dict[str, int]:
        """
        Upsert JSONL files from src_dir into local SQLite.
        Idempotent — running twice produces no duplicates.
        Returns counts of records imported per table.
        """
        src_dir = Path(src_dir)
        counts: Dict[str, int] = {"preferences": 0, "associations": 0, "contexts": 0, "signals": 0}

        for d in _read_jsonl(src_dir / "all_preferences.jsonl"):
            try:
                mgr.preferences.save_preference(Preference.from_dict(d))
                counts["preferences"] += 1
            except (ValueError, KeyError, TypeError) as e:
                print(f"  WARNING: Skipping malformed preference {d.get('id')}: {e}")
            except Exception as e:
                raise RuntimeError(
                    f"Unexpected error importing preference {d.get('id')}: {e}"
                ) from e

        for d in _read_jsonl(src_dir / "associations.jsonl"):
            try:
                mgr.associations.save_association(Association.from_dict(d))
                counts["associations"] += 1
            except (ValueError, KeyError, TypeError) as e:
                print(f"  WARNING: Skipping malformed association {d.get('id')}: {e}")
            except Exception as e:
                raise RuntimeError(
                    f"Unexpected error importing association {d.get('id')}: {e}"
                ) from e

        for d in _read_jsonl(src_dir / "contexts.jsonl"):
            try:
                mgr.contexts.save_context(ContextStack.from_dict(d))
                counts["contexts"] += 1
            except (ValueError, KeyError, TypeError) as e:
                print(f"  WARNING: Skipping malformed context {d.get('id')}: {e}")
            except Exception as e:
                raise RuntimeError(
                    f"Unexpected error importing context {d.get('id')}: {e}"
                ) from e

        for d in _read_jsonl(src_dir / "signals.jsonl"):
            try:
                mgr.signals.save_signal(Signal.from_dict(d))
                counts["signals"] += 1
            except (ValueError, KeyError, TypeError) as e:
                print(f"  WARNING: Skipping malformed signal {d.get('id')}: {e}")
            except Exception as e:
                raise RuntimeError(
                    f"Unexpected error importing signal {d.get('id')}: {e}"
                ) from e

        return counts


class SyncRunner:
    """Orchestrates git operations + export/import for push and pull."""

    def __init__(self, mgr: PreferenceStorageManager, sync_repo_path: str) -> None:
        self.mgr = mgr
        self.repo = Path(sync_repo_path).expanduser()

    def push(self) -> Dict:
        """Export SQLite → JSONL, git add+commit+push. Returns result dict."""
        if not self.repo.exists():
            raise FileNotFoundError(
                f"Sync repo not found: {self.repo}\n"
                "Run: adaptive-cli sync configure --repo-path <path>"
            )

        counts = PreferenceSync.export(self.mgr, self.repo)

        status = _git(["status", "--porcelain"], cwd=self.repo)
        if not status.strip():
            return {"status": "up-to-date", "counts": counts}

        _git(["add",
              "all_preferences.jsonl", "associations.jsonl",
              "contexts.jsonl", "signals.jsonl"], cwd=self.repo)

        msg = f"sync: export preferences {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        _git(["commit", "-m", msg], cwd=self.repo)
        try:
            _git(["push"], cwd=self.repo)
            return {"status": "pushed", "counts": counts}
        except RuntimeError as e:
            return {"status": "committed", "counts": counts, "git_push_error": str(e)}

    def pull(self) -> Dict:
        """git pull, then import JSONL → SQLite. Returns result dict."""
        if not self.repo.exists():
            raise FileNotFoundError(
                f"Sync repo not found: {self.repo}\n"
                "Run: adaptive-cli sync configure --repo-path <path>"
            )

        git_pull_error = None
        try:
            _git(["pull"], cwd=self.repo)
        except RuntimeError as e:
            git_pull_error = str(e)
        counts = PreferenceSync.import_from(self.mgr, self.repo)
        result: Dict = {"status": "pulled", "counts": counts}
        if git_pull_error:
            result["git_pull_error"] = git_pull_error
        return result

    def status(self) -> str:
        """Return git status output from the sync repo."""
        if not self.repo.exists():
            return f"Sync repo not configured or not found: {self.repo}"
        return _git(["status", "--short"], cwd=self.repo)


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_jsonl(path: Path, records: list) -> None:
    """Write list of dicts as JSONL (atomic via tmp file)."""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    os.replace(tmp, path)


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"  WARNING: Skipping malformed line {lineno} in {path.name}: {e}")
    return out


def _git(args: list, cwd: Path) -> str:
    """Run a git command in cwd. Raises RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed:\n{result.stderr.strip()}"
        )
    return result.stdout
