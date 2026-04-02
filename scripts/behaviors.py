"""behaviors.py - Behavior storage for APE."""

import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

# Schema DDL for behavior tables (v2 migration)
BEHAVIOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS behaviors (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    version         TEXT NOT NULL,
    description     TEXT DEFAULT '',
    platform        TEXT NOT NULL DEFAULT 'any',
    enabled         INTEGER DEFAULT 1,
    hook_event      TEXT,
    hook_matcher    TEXT,
    artifact_path   TEXT,
    artifact_header TEXT,
    setup_script    TEXT,
    verify_script   TEXT,
    created         TEXT NOT NULL,
    last_updated    TEXT NOT NULL,
    installed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_beh_name    ON behaviors(name);
CREATE INDEX IF NOT EXISTS idx_beh_enabled ON behaviors(enabled);

CREATE TABLE IF NOT EXISTS behavior_behavior_deps (
    behavior_id TEXT NOT NULL,
    dep_id      TEXT NOT NULL,
    PRIMARY KEY (behavior_id, dep_id),
    FOREIGN KEY (behavior_id) REFERENCES behaviors(id) ON DELETE CASCADE,
    FOREIGN KEY (dep_id)      REFERENCES behaviors(id)
);

CREATE TABLE IF NOT EXISTS behavior_pref_deps (
    behavior_id TEXT NOT NULL,
    pref_path   TEXT NOT NULL,
    PRIMARY KEY (behavior_id, pref_path),
    FOREIGN KEY (behavior_id) REFERENCES behaviors(id) ON DELETE CASCADE
);
"""


class Behavior:
    """Represents a named automation unit stored in APE."""

    def __init__(
        self,
        id: str,
        name: str,
        version: str,
        description: str = "",
        platform: str = "any",
        enabled: bool = True,
        hook_event: Optional[str] = None,
        hook_matcher: Optional[str] = None,
        artifact_path: Optional[str] = None,
        artifact_header: Optional[str] = None,
        setup_script: Optional[str] = None,
        verify_script: Optional[str] = None,
        created: Optional[str] = None,
        last_updated: Optional[str] = None,
        installed_at: Optional[str] = None,
        behavior_deps: Optional[List[str]] = None,
        pref_deps: Optional[List[str]] = None,
    ):
        now = datetime.now().isoformat()
        self.id = id
        self.name = name
        self.version = version
        self.description = description
        self.platform = platform
        self.enabled = enabled
        self.hook_event = hook_event
        self.hook_matcher = hook_matcher
        self.artifact_path = artifact_path
        self.artifact_header = artifact_header
        self.setup_script = setup_script
        self.verify_script = verify_script
        self.created = created or now
        self.last_updated = last_updated or now
        self.installed_at = installed_at or now
        self.behavior_deps: List[str] = behavior_deps or []
        self.pref_deps: List[str] = pref_deps or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "platform": self.platform,
            "enabled": self.enabled,
            "hook_event": self.hook_event,
            "hook_matcher": self.hook_matcher,
            "artifact_path": self.artifact_path,
            "artifact_header": self.artifact_header,
            "setup_script": self.setup_script,
            "verify_script": self.verify_script,
            "created": self.created,
            "last_updated": self.last_updated,
            "installed_at": self.installed_at,
            "behavior_deps": self.behavior_deps,
            "pref_deps": self.pref_deps,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Behavior":
        return cls(**{k: v for k, v in d.items() if k in cls.__init__.__code__.co_varnames})


class BehaviorStorage:
    """CRUD for behaviors and their dependency junction tables."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_behavior(self, behavior: Behavior, update_deps: bool = True) -> None:
        """Persist a behavior record. Pass update_deps=False when only scalar fields
        changed (e.g. toggling enabled) to skip unnecessary junction table churn."""
        d = behavior.to_dict()
        with self._conn:
            self._conn.execute("""
                INSERT INTO behaviors
                    (id, name, version, description, platform, enabled,
                     hook_event, hook_matcher, artifact_path, artifact_header,
                     setup_script, verify_script, created, last_updated, installed_at)
                VALUES
                    (:id, :name, :version, :description, :platform, :enabled,
                     :hook_event, :hook_matcher, :artifact_path, :artifact_header,
                     :setup_script, :verify_script, :created, :last_updated, :installed_at)
                ON CONFLICT(id) DO UPDATE SET
                    name           = excluded.name,
                    version        = excluded.version,
                    description    = excluded.description,
                    platform       = excluded.platform,
                    enabled        = excluded.enabled,
                    hook_event     = excluded.hook_event,
                    hook_matcher   = excluded.hook_matcher,
                    artifact_path  = excluded.artifact_path,
                    artifact_header = excluded.artifact_header,
                    setup_script   = excluded.setup_script,
                    verify_script  = excluded.verify_script,
                    last_updated   = excluded.last_updated
            """, {**d, "enabled": int(d["enabled"])})
            if update_deps:
                self._conn.execute("DELETE FROM behavior_behavior_deps WHERE behavior_id = ?", (behavior.id,))
                for dep_id in behavior.behavior_deps:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO behavior_behavior_deps (behavior_id, dep_id) VALUES (?, ?)",
                        (behavior.id, dep_id)
                    )
                self._conn.execute("DELETE FROM behavior_pref_deps WHERE behavior_id = ?", (behavior.id,))
                for pref_path in behavior.pref_deps:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO behavior_pref_deps (behavior_id, pref_path) VALUES (?, ?)",
                        (behavior.id, pref_path)
                    )

    def get_behavior(self, behavior_id: str) -> Optional[Behavior]:
        row = self._conn.execute("SELECT * FROM behaviors WHERE id = ?", (behavior_id,)).fetchone()
        return self._row_to_behavior(row, {}, {}) if row else None

    def get_behavior_by_name(self, name: str) -> Optional[Behavior]:
        row = self._conn.execute("SELECT * FROM behaviors WHERE name = ?", (name,)).fetchone()
        if not row:
            return None
        bid = dict(row)["id"]
        bdeps = {bid: [r[0] for r in self._conn.execute(
            "SELECT dep_id FROM behavior_behavior_deps WHERE behavior_id = ?", (bid,)
        ).fetchall()]}
        pdeps = {bid: [r[0] for r in self._conn.execute(
            "SELECT pref_path FROM behavior_pref_deps WHERE behavior_id = ?", (bid,)
        ).fetchall()]}
        return self._row_to_behavior(row, bdeps, pdeps)

    def get_all_behaviors(self) -> List[Behavior]:
        rows = self._conn.execute("SELECT * FROM behaviors ORDER BY name").fetchall()
        return self._fetch_with_deps(rows)

    def get_enabled_behaviors(self) -> List[Behavior]:
        rows = self._conn.execute(
            "SELECT * FROM behaviors WHERE enabled = 1 ORDER BY name"
        ).fetchall()
        return self._fetch_with_deps(rows)

    def delete_behavior(self, behavior_id: str) -> bool:
        with self._conn:
            cursor = self._conn.execute("DELETE FROM behaviors WHERE id = ?", (behavior_id,))
        return cursor.rowcount > 0

    def _fetch_with_deps(self, rows: List[sqlite3.Row]) -> List["Behavior"]:
        """Batch-load junction rows in 2 queries instead of 2N."""
        if not rows:
            return []
        ids = [dict(r)["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        bdep_rows = self._conn.execute(
            f"SELECT behavior_id, dep_id FROM behavior_behavior_deps WHERE behavior_id IN ({placeholders})",
            ids,
        ).fetchall()
        pdep_rows = self._conn.execute(
            f"SELECT behavior_id, pref_path FROM behavior_pref_deps WHERE behavior_id IN ({placeholders})",
            ids,
        ).fetchall()
        bdeps: Dict[str, List[str]] = {}
        pdeps: Dict[str, List[str]] = {}
        for r in bdep_rows:
            bdeps.setdefault(r[0], []).append(r[1])
        for r in pdep_rows:
            pdeps.setdefault(r[0], []).append(r[1])
        return [self._row_to_behavior(r, bdeps, pdeps) for r in rows]

    def _row_to_behavior(
        self,
        row: sqlite3.Row,
        bdeps: Dict[str, List[str]],
        pdeps: Dict[str, List[str]],
    ) -> "Behavior":
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        return Behavior(
            id=d["id"],
            name=d["name"],
            version=d["version"],
            description=d["description"],
            platform=d["platform"],
            enabled=d["enabled"],
            hook_event=d["hook_event"],
            hook_matcher=d["hook_matcher"],
            artifact_path=d["artifact_path"],
            artifact_header=d["artifact_header"],
            setup_script=d["setup_script"],
            verify_script=d["verify_script"],
            created=d["created"],
            last_updated=d["last_updated"],
            installed_at=d["installed_at"],
            behavior_deps=bdeps.get(d["id"], []),
            pref_deps=pdeps.get(d["id"], []),
        )


def parse_ape_header(path: str) -> dict:
    """Parse APE-* header comments from a behavior artifact file.

    Scans ALL comment lines in the file (lines starting with '#'), ignoring
    non-comment lines. This means headers can appear anywhere in the comment
    block — after the shebang, after 'set -euo pipefail', etc.

    Required fields: APE-BEHAVIOR, APE-VERSION.
    Raises ValueError with a helpful message if either is missing.

    Returns dict with keys:
        name, version, platform, hook_event, hook_matcher, enabled,
        description, verify_script, setup_script, pref_deps (list, deduplicated)
    """
    result = {
        "name": None,
        "version": None,
        "platform": "any",
        "hook_event": None,
        "hook_matcher": None,
        "enabled": True,
        "description": "",
        "verify_script": None,
        "setup_script": None,
        "pref_deps": [],
    }
    _seen_pref_deps: set = set()

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line.strip():
                    continue
                if not line.startswith("#"):
                    continue
                if not line.startswith("# APE-"):
                    continue
                rest = line[2:]  # strip "# "
                if ":" not in rest:
                    continue
                key, _, value = rest.partition(":")
                key = key.strip()
                value = value.strip()

                if key == "APE-BEHAVIOR":
                    result["name"] = value
                elif key == "APE-VERSION":
                    result["version"] = value
                elif key == "APE-PLATFORM":
                    result["platform"] = value
                elif key == "APE-HOOK-EVENT":
                    result["hook_event"] = value if value.lower() != "none" else None
                elif key == "APE-HOOK-MATCHER":
                    result["hook_matcher"] = value if value.lower() != "none" else None
                elif key == "APE-STATUS":
                    result["enabled"] = value.lower() == "enabled"
                elif key == "APE-DESCRIPTION":
                    result["description"] = value
                elif key == "APE-VERIFY":
                    result["verify_script"] = value
                elif key == "APE-SETUP":
                    result["setup_script"] = value
                elif key == "APE-PREF-DEP":
                    if value and value not in _seen_pref_deps:
                        _seen_pref_deps.add(value)
                        result["pref_deps"].append(value)
    except FileNotFoundError:
        raise FileNotFoundError(f"Artifact file not found: {path}")

    missing = []
    if not result["name"]:
        missing.append("APE-BEHAVIOR")
    if not result["version"]:
        missing.append("APE-VERSION")
    if missing:
        raise ValueError(
            f"Missing required APE header(s) in {path}: {', '.join(missing)}\n"
            f"  Add these lines anywhere in the comment block (lines starting with '#'):\n"
            + "\n".join(f"  # {m}: <value>" for m in missing)
        )

    return result
