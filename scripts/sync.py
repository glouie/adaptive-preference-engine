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

import fcntl
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict

from adaptive_preference_engine.knowledge import KnowledgeEntry
from scripts.models import Association, ContextStack, Preference, Signal
from scripts.storage import PreferenceStorageManager, ConfidentialStorageManager

# ~/.claude/ files synced by push/pull (filenames only, no subdirs)
_CLAUDE_SYNC_SCRIPTS = ["statusline-ape.sh", "settings.json"]


class RepoLock:
    """Non-blocking flock for serializing git operations on a repo."""

    def __init__(self, repo_name: str, lock_dir: str = "~/.adaptive-cli"):
        lock_dir = Path(lock_dir).expanduser()
        lock_dir.mkdir(parents=True, exist_ok=True)
        self.lock_path = lock_dir / f"{repo_name}.lock"
        self._fd = None

    def acquire(self) -> bool:
        self._fd = open(self.lock_path, "w")
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (IOError, OSError):
            self._fd.close()
            self._fd = None
            return False

    def release(self) -> None:
        if self._fd:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            self._fd.close()
            self._fd = None

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"Could not acquire lock: {self.lock_path}")
        return self

    def __exit__(self, *args):
        self.release()


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

        knowledge = mgr.knowledge.get_all_entries(include_archived=True)
        _write_jsonl(dest_dir / "knowledge.jsonl", [k.to_dict() for k in knowledge])
        counts["knowledge"] = len(knowledge)

        return counts

    @staticmethod
    def import_from(mgr: PreferenceStorageManager, src_dir: Path) -> Dict[str, int]:
        """
        Upsert JSONL files from src_dir into local SQLite.
        Idempotent — running twice produces no duplicates (uses INSERT OR REPLACE).
        Returns upsert-call counts per table (not insert counts — existing records
        that are re-imported still increment the count).
        """
        src_dir = Path(src_dir)
        counts: Dict[str, int] = {"preferences": 0, "associations": 0, "contexts": 0, "signals": 0, "knowledge": 0}

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

        for d in _read_jsonl(src_dir / "knowledge.jsonl"):
            try:
                entry_obj = KnowledgeEntry.from_dict(d)
                mgr.knowledge.save_entry(entry_obj)
                counts["knowledge"] += 1
                # Warn if ref_path exists but file not found
                if hasattr(entry_obj, 'ref_path') and entry_obj.ref_path:
                    ref_file = src_dir / entry_obj.ref_path
                    if not ref_file.exists():
                        print(f"  WARNING: Knowledge entry {entry_obj.id} references {entry_obj.ref_path} but file not found")
            except (ValueError, KeyError, TypeError) as e:
                print(f"  WARNING: Skipping malformed knowledge {d.get('id')}: {e}")
            except Exception as e:
                raise RuntimeError(
                    f"Unexpected error importing knowledge {d.get('id')}: {e}"
                ) from e

        # Trigger compaction after importing knowledge
        if counts["knowledge"] > 0:
            try:
                from scripts.compaction import CompactionEngine
                engine = CompactionEngine(mgr)
                compacted = engine.check_and_compact()
                if compacted:
                    print(f"  Compacted {len(compacted)} partition(s) after import")
            except Exception as exc:
                print(f"  WARNING: Post-import compaction failed: {exc}")

        return counts


class ConfidentialSync:
    """Export/import for the confidential knowledge database (knowledge only)."""

    @staticmethod
    def export(cmgr: "ConfidentialStorageManager", dest_dir: Path) -> Dict:
        dest_dir = Path(dest_dir)
        entries = cmgr.knowledge.get_all_entries(include_archived=True)
        records = []
        for e in entries:
            d = e.to_dict()
            d["tags"] = json.dumps(d["tags"])
            records.append(d)
        _write_jsonl(dest_dir / "knowledge.jsonl", records)
        return {"knowledge": len(records)}

    @staticmethod
    def import_from(cmgr: "ConfidentialStorageManager", src_dir: Path) -> Dict:
        src_dir = Path(src_dir)
        counts = {}
        knowledge_path = src_dir / "knowledge.jsonl"
        if knowledge_path.exists():
            records = _read_jsonl(knowledge_path)
            imported = 0
            for rec in records:
                if "tags" in rec and isinstance(rec["tags"], str):
                    rec["tags"] = json.loads(rec["tags"])
                entry = KnowledgeEntry.from_dict(rec)
                cmgr.knowledge.save_entry(entry)
                imported += 1
            counts["knowledge"] = imported
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

        # Export agent definitions from ~/.adaptive-cli/agents/ if any exist
        local_agents = Path(os.path.expanduser("~/.adaptive-cli/agents"))
        if local_agents.exists():
            repo_agents = self.repo / "agents"
            repo_agents.mkdir(exist_ok=True)
            for f in local_agents.glob("*.md"):
                shutil.copy2(f, repo_agents / f.name)

        # Export ~/.claude/ scripts (statusline, etc.)
        claude_dir = Path.home() / ".claude"
        repo_scripts = self.repo / "claude_scripts"
        for src in _CLAUDE_SYNC_SCRIPTS:
            f = claude_dir / src
            if f.exists():
                repo_scripts.mkdir(exist_ok=True)
                shutil.copy2(f, repo_scripts / f.name)

        status = _git(["status", "--porcelain"], cwd=self.repo)
        if not status.strip():
            return {"status": "up-to-date", "counts": counts}

        git_add = ["all_preferences.jsonl", "associations.jsonl",
                   "contexts.jsonl", "signals.jsonl", "knowledge.jsonl"]
        if (self.repo / "config.yaml").exists():
            git_add.append("config.yaml")
        if (self.repo / "agents").exists():
            git_add.append("agents/")
        if (self.repo / "claude_scripts").exists():
            git_add.append("claude_scripts/")
        _git(["add"] + git_add, cwd=self.repo)

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
            # Abort if the repo is in a conflicted state — importing from
            # conflict-marked JSONL would silently corrupt data.
            conflict_status = _git_safe(["status", "--porcelain"], cwd=self.repo)
            if conflict_status and any(
                line[:2] in ("AA", "UU", "DD", "AU", "UA", "DU", "UD")
                for line in conflict_status.splitlines()
            ):
                return {
                    "status": "conflict",
                    "git_pull_error": git_pull_error,
                    "counts": {},
                }
        counts = PreferenceSync.import_from(self.mgr, self.repo)

        # Restore agent definitions to ~/.adaptive-cli/agents/ and ~/.claude/agents/
        repo_agents = self.repo / "agents"
        if repo_agents.exists():
            local_agents = Path(os.path.expanduser("~/.adaptive-cli/agents"))
            claude_agents = Path.home() / ".claude" / "agents"
            local_agents.mkdir(parents=True, exist_ok=True)
            claude_agents.mkdir(parents=True, exist_ok=True)
            installed = 0
            for f in repo_agents.glob("*.md"):
                # Reject symlinks and names with path separators to prevent traversal
                if f.is_symlink():
                    print(f"  WARNING: Skipping symlink in agents/: {f.name}")
                    continue
                real = f.resolve()
                if not str(real).startswith(str(repo_agents.resolve())):
                    print(f"  WARNING: Skipping out-of-tree agent file: {f.name}")
                    continue
                safe_name = f.name
                if "/" in safe_name or "\\" in safe_name or ".." in safe_name:
                    print(f"  WARNING: Skipping unsafe agent filename: {safe_name}")
                    continue
                shutil.copy2(f, local_agents / safe_name)
                shutil.copy2(f, claude_agents / safe_name)
                installed += 1
            counts["agents"] = installed

        # Restore ~/.claude/ scripts
        repo_scripts = self.repo / "claude_scripts"
        if repo_scripts.exists():
            claude_dir = Path.home() / ".claude"
            claude_dir.mkdir(parents=True, exist_ok=True)
            restored = 0
            for name in _CLAUDE_SYNC_SCRIPTS:
                src = repo_scripts / name
                if src.exists() and not src.is_symlink():
                    shutil.copy2(src, claude_dir / name)
                    restored += 1
            if restored:
                counts["claude_scripts"] = restored

        result: Dict = {"status": "pulled", "counts": counts}
        if git_pull_error:
            result["git_pull_error"] = git_pull_error
        return result

    def status(self) -> str:
        """Return git status output from the sync repo."""
        if not self.repo.exists():
            return f"Sync repo not configured or not found: {self.repo}"
        return _git(["status", "--short"], cwd=self.repo)

    def pending_counts(self) -> Dict[str, int]:
        """
        Compare SQLite row counts to JSONL line counts in the repo.

        Returns dict of {table: N} where:
          N > 0 — SQLite has that many records not yet reflected in the repo JSONL (push needed)
          N < 0 — JSONL has that many records not in SQLite (e.g. after a reset; pull would re-import them)

        Only tables with a non-zero diff are included. Returns empty dict if repo
        doesn't exist or all counts match.
        """
        if not self.repo.exists():
            return {}

        info = self.mgr.get_storage_info()
        sqlite_counts = {
            "preferences":  info["preferences_count"],
            "associations": info["associations_count"],
            "contexts":     info["contexts_count"],
            "signals":      info["signals_count"],
            "knowledge":    info.get("knowledge_count", 0),
        }

        file_map = {
            "preferences":  "all_preferences.jsonl",
            "associations": "associations.jsonl",
            "contexts":     "contexts.jsonl",
            "signals":      "signals.jsonl",
            "knowledge":    "knowledge.jsonl",
        }

        pending: Dict[str, int] = {}
        for table, filename in file_map.items():
            path = self.repo / filename
            repo_count = len(_read_jsonl(path))
            diff = sqlite_counts[table] - repo_count
            if diff != 0:
                pending[table] = diff
        return pending

    def diff(self) -> Dict:
        """Compare local SQLite counts to repo JSONL counts."""
        if not self.repo.exists():
            return {"status": "no_repo", "diffs": {}}
        local_info = self.mgr.get_storage_info()
        local_counts = {
            "preferences": local_info["preferences_count"],
            "associations": local_info["associations_count"],
            "contexts": local_info["contexts_count"],
            "signals": local_info["signals_count"],
            "knowledge": local_info.get("knowledge_count", 0),
        }
        file_map = {
            "preferences": "all_preferences.jsonl",
            "associations": "associations.jsonl",
            "contexts": "contexts.jsonl",
            "signals": "signals.jsonl",
            "knowledge": "knowledge.jsonl",
        }
        diffs = {}
        for table, filename in file_map.items():
            path = self.repo / filename
            remote_count = len(_read_jsonl(path))
            diff_val = local_counts[table] - remote_count
            if diff_val != 0:
                diffs[table] = diff_val
        return {"status": "ok", "diffs": diffs, "local": local_counts}


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_jsonl(path: Path, records: list) -> None:
    """Write list of dicts as JSONL (atomic via tmp file)."""
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


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


def _git_safe(args: list, cwd: Path) -> str:
    """Run a git command in cwd. Returns empty string on non-zero exit (no raise)."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else ""
