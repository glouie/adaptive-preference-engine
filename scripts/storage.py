"""
storage.py - SQLite storage for preferences, associations, signals, contexts.

Database lives at <base_dir>/preferences/adaptive.db (single file).
All nested objects (LearningData, context preferences, signal lists) are
stored as JSON TEXT blobs so callers never deal with join queries.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.models import (
    Association, ContextStack,
    Preference, Signal,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS preferences (
    id              TEXT PRIMARY KEY,
    path            TEXT NOT NULL,
    parent_id       TEXT,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,
    value           TEXT,
    confidence      REAL    DEFAULT 0.5,
    description     TEXT    DEFAULT '',
    created         TEXT    NOT NULL,
    last_updated    TEXT    NOT NULL,
    auto_detected   INTEGER DEFAULT 0,
    learning        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pref_path   ON preferences(path);
CREATE INDEX IF NOT EXISTS idx_pref_parent ON preferences(parent_id);

CREATE TABLE IF NOT EXISTS associations (
    id                  TEXT PRIMARY KEY,
    from_id             TEXT NOT NULL,
    to_id               TEXT NOT NULL,
    bidirectional       INTEGER DEFAULT 1,
    strength_forward    REAL    DEFAULT 0.5,
    strength_backward   REAL    DEFAULT 0.5,
    learning_forward    TEXT    NOT NULL,
    learning_backward   TEXT    NOT NULL,
    description         TEXT    DEFAULT '',
    context_tags        TEXT    NOT NULL,
    created             TEXT    NOT NULL,
    time_decay_factor   REAL    DEFAULT 0.98,
    last_decay_applied  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assoc_from ON associations(from_id);
CREATE INDEX IF NOT EXISTS idx_assoc_to   ON associations(to_id);

CREATE TABLE IF NOT EXISTS contexts (
    id          TEXT PRIMARY KEY,
    name        TEXT    NOT NULL,
    scope       TEXT    NOT NULL,
    active      INTEGER DEFAULT 1,
    preferences TEXT    NOT NULL,
    stack_level INTEGER DEFAULT 0,
    created     TEXT    NOT NULL,
    last_used   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ctx_scope  ON contexts(scope);
CREATE INDEX IF NOT EXISTS idx_ctx_active ON contexts(active);

CREATE TABLE IF NOT EXISTS signals (
    id                    TEXT PRIMARY KEY,
    timestamp             TEXT NOT NULL,
    type                  TEXT NOT NULL,
    task                  TEXT,
    context_tags          TEXT NOT NULL,
    agent_proposed        TEXT,
    user_corrected_to     TEXT,
    user_response         TEXT,
    emotional_tone        TEXT,
    emotional_indicators  TEXT NOT NULL,
    preferences_used      TEXT NOT NULL,
    associations_affected TEXT NOT NULL,
    preferences_affected  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sig_timestamp ON signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_sig_type      ON signals(type);

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT NOT NULL
);
"""


class SQLiteDB:
    """
    Base class: holds a reference to a shared SQLite connection.
    Each subclass gets the same connection passed in from the manager.

    WAL mode is enabled once at open time so reads and writes don't block
    each other — important when the CLI and background processors run
    concurrently.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn


class PreferenceStorage(SQLiteDB):
    """CRUD for the `preferences` table."""

    def save_preference(self, preference: Preference) -> None:
        d = preference.to_dict()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO preferences
                    (id, path, parent_id, name, type, value, confidence,
                     description, created, last_updated, auto_detected, learning)
                VALUES
                    (:id, :path, :parent_id, :name, :type, :value, :confidence,
                     :description, :created, :last_updated, :auto_detected, :learning)
                ON CONFLICT(id) DO UPDATE SET
                    path           = excluded.path,
                    parent_id      = excluded.parent_id,
                    name           = excluded.name,
                    type           = excluded.type,
                    value          = excluded.value,
                    confidence     = excluded.confidence,
                    description    = excluded.description,
                    last_updated   = excluded.last_updated,
                    auto_detected  = excluded.auto_detected,
                    learning       = excluded.learning
                """,
                {**d, "learning": json.dumps(d["learning"]),
                 "auto_detected": int(d["auto_detected"])},
            )

    def get_preference(self, pref_id: str) -> Optional[Preference]:
        row = self._conn.execute(
            "SELECT * FROM preferences WHERE id = ?", (pref_id,)
        ).fetchone()
        return self._row_to_preference(row) if row else None

    def get_preferences_for_parent(self, parent_id: str) -> List[Preference]:
        rows = self._conn.execute(
            "SELECT * FROM preferences WHERE parent_id = ?", (parent_id,)
        ).fetchall()
        return [self._row_to_preference(r) for r in rows]

    def get_preferences_by_path(self, path_prefix: str) -> List[Preference]:
        rows = self._conn.execute(
            "SELECT * FROM preferences WHERE path = ? OR path LIKE ?",
            (path_prefix, path_prefix + ".%"),
        ).fetchall()
        return [self._row_to_preference(r) for r in rows]

    def get_all_preferences(self) -> List[Preference]:
        rows = self._conn.execute("SELECT * FROM preferences").fetchall()
        return [self._row_to_preference(r) for r in rows]

    def delete_preference(self, pref_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM preferences WHERE id = ?", (pref_id,))

    @staticmethod
    def _row_to_preference(row: sqlite3.Row) -> Preference:
        d = dict(row)
        d["learning"] = json.loads(d["learning"])
        d["auto_detected"] = bool(d["auto_detected"])
        return Preference.from_dict(d)


class AssociationStorage(SQLiteDB):
    """CRUD for the `associations` table."""

    def save_association(self, association: Association) -> None:
        d = association.to_dict()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO associations
                    (id, from_id, to_id, bidirectional, strength_forward,
                     strength_backward, learning_forward, learning_backward,
                     description, context_tags, created, time_decay_factor,
                     last_decay_applied)
                VALUES
                    (:id, :from_id, :to_id, :bidirectional, :strength_forward,
                     :strength_backward, :learning_forward, :learning_backward,
                     :description, :context_tags, :created, :time_decay_factor,
                     :last_decay_applied)
                ON CONFLICT(id) DO UPDATE SET
                    from_id            = excluded.from_id,
                    to_id              = excluded.to_id,
                    bidirectional      = excluded.bidirectional,
                    strength_forward   = excluded.strength_forward,
                    strength_backward  = excluded.strength_backward,
                    learning_forward   = excluded.learning_forward,
                    learning_backward  = excluded.learning_backward,
                    description        = excluded.description,
                    context_tags       = excluded.context_tags,
                    time_decay_factor  = excluded.time_decay_factor,
                    last_decay_applied = excluded.last_decay_applied
                """,
                {
                    **d,
                    "bidirectional": int(d["bidirectional"]),
                    "learning_forward": json.dumps(d["learning_forward"]),
                    "learning_backward": json.dumps(d["learning_backward"]),
                    "context_tags": json.dumps(d["context_tags"]),
                },
            )

    def get_association(self, assoc_id: str) -> Optional[Association]:
        row = self._conn.execute(
            "SELECT * FROM associations WHERE id = ?", (assoc_id,)
        ).fetchone()
        return self._row_to_association(row) if row else None

    def get_associations_for_preference(self, pref_id: str) -> List[Association]:
        rows = self._conn.execute(
            "SELECT * FROM associations WHERE from_id = ? OR to_id = ?",
            (pref_id, pref_id),
        ).fetchall()
        return [self._row_to_association(r) for r in rows]

    def get_associations_from(self, from_id: str) -> List[Association]:
        rows = self._conn.execute(
            "SELECT * FROM associations WHERE from_id = ?", (from_id,)
        ).fetchall()
        return [self._row_to_association(r) for r in rows]

    def get_associations_to(self, to_id: str) -> List[Association]:
        rows = self._conn.execute(
            "SELECT * FROM associations WHERE to_id = ?", (to_id,)
        ).fetchall()
        return [self._row_to_association(r) for r in rows]

    def get_all_associations(self) -> List[Association]:
        rows = self._conn.execute("SELECT * FROM associations").fetchall()
        return [self._row_to_association(r) for r in rows]

    @staticmethod
    def _row_to_association(row: sqlite3.Row) -> Association:
        d = dict(row)
        d["bidirectional"] = bool(d["bidirectional"])
        d["learning_forward"] = json.loads(d["learning_forward"])
        d["learning_backward"] = json.loads(d["learning_backward"])
        d["context_tags"] = json.loads(d["context_tags"])
        return Association.from_dict(d)


class ContextStorage(SQLiteDB):
    """CRUD for the `contexts` table."""

    def save_context(self, context: ContextStack) -> None:
        d = context.to_dict()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO contexts
                    (id, name, scope, active, preferences, stack_level,
                     created, last_used)
                VALUES
                    (:id, :name, :scope, :active, :preferences, :stack_level,
                     :created, :last_used)
                ON CONFLICT(id) DO UPDATE SET
                    name        = excluded.name,
                    scope       = excluded.scope,
                    active      = excluded.active,
                    preferences = excluded.preferences,
                    stack_level = excluded.stack_level,
                    last_used   = excluded.last_used
                """,
                {
                    **d,
                    "active": int(d["active"]),
                    "preferences": json.dumps(d["preferences"]),
                },
            )

    def get_context(self, ctx_id: str) -> Optional[ContextStack]:
        row = self._conn.execute(
            "SELECT * FROM contexts WHERE id = ?", (ctx_id,)
        ).fetchone()
        return self._row_to_context(row) if row else None

    def get_active_contexts(self) -> List[ContextStack]:
        rows = self._conn.execute(
            "SELECT * FROM contexts WHERE active = 1 ORDER BY stack_level ASC"
        ).fetchall()
        return [self._row_to_context(r) for r in rows]

    def get_contexts_by_scope(self, scope: str) -> List[ContextStack]:
        rows = self._conn.execute(
            "SELECT * FROM contexts WHERE scope = ?", (scope,)
        ).fetchall()
        return [self._row_to_context(r) for r in rows]

    def get_all_contexts(self) -> List[ContextStack]:
        rows = self._conn.execute("SELECT * FROM contexts").fetchall()
        return [self._row_to_context(r) for r in rows]

    @staticmethod
    def _row_to_context(row: sqlite3.Row) -> ContextStack:
        d = dict(row)
        d["active"] = bool(d["active"])
        d["preferences"] = json.loads(d["preferences"])
        return ContextStack.from_dict(d)


class SignalStorage(SQLiteDB):
    """CRUD for the `signals` table."""

    def save_signal(self, signal: Signal) -> None:
        d = signal.to_dict()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO signals
                    (id, timestamp, type, task, context_tags, agent_proposed,
                     user_corrected_to, user_response, emotional_tone,
                     emotional_indicators, preferences_used,
                     associations_affected, preferences_affected)
                VALUES
                    (:id, :timestamp, :type, :task, :context_tags, :agent_proposed,
                     :user_corrected_to, :user_response, :emotional_tone,
                     :emotional_indicators, :preferences_used,
                     :associations_affected, :preferences_affected)
                ON CONFLICT(id) DO UPDATE SET
                    timestamp            = excluded.timestamp,
                    type                 = excluded.type,
                    task                 = excluded.task,
                    context_tags         = excluded.context_tags,
                    agent_proposed       = excluded.agent_proposed,
                    user_corrected_to    = excluded.user_corrected_to,
                    user_response        = excluded.user_response,
                    emotional_tone       = excluded.emotional_tone,
                    emotional_indicators = excluded.emotional_indicators,
                    preferences_used     = excluded.preferences_used,
                    associations_affected = excluded.associations_affected,
                    preferences_affected = excluded.preferences_affected
                """,
                {
                    **d,
                    "context_tags": json.dumps(d["context_tags"]),
                    "emotional_indicators": json.dumps(d["emotional_indicators"]),
                    "preferences_used": json.dumps(d["preferences_used"]),
                    "associations_affected": json.dumps(d["associations_affected"]),
                    "preferences_affected": json.dumps(d["preferences_affected"]),
                },
            )

    def get_signal(self, signal_id: str) -> Optional[Signal]:
        row = self._conn.execute(
            "SELECT * FROM signals WHERE id = ?", (signal_id,)
        ).fetchone()
        return self._row_to_signal(row) if row else None

    def get_signals_by_type(self, signal_type: str) -> List[Signal]:
        rows = self._conn.execute(
            "SELECT * FROM signals WHERE type = ?", (signal_type,)
        ).fetchall()
        return [self._row_to_signal(r) for r in rows]

    def get_recent_signals(self, hours: int = 24) -> List[Signal]:
        cutoff = (
            datetime.now() - timedelta(hours=hours)
        ).isoformat()
        rows = self._conn.execute(
            "SELECT * FROM signals WHERE timestamp >= ? ORDER BY timestamp DESC",
            (cutoff,),
        ).fetchall()
        return [self._row_to_signal(r) for r in rows]

    def get_signals_for_preference(self, pref_id: str) -> List[Signal]:
        rows = self._conn.execute(
            """
            SELECT s.* FROM signals s, json_each(s.preferences_used) j
            WHERE j.value = ?
            """,
            (pref_id,),
        ).fetchall()
        return [self._row_to_signal(r) for r in rows]

    def get_all_signals(self) -> List[Signal]:
        rows = self._conn.execute("SELECT * FROM signals").fetchall()
        return [self._row_to_signal(r) for r in rows]

    def delete_signal(self, signal_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM signals WHERE id = ?", (signal_id,))

    @staticmethod
    def _row_to_signal(row: sqlite3.Row) -> Signal:
        d = dict(row)
        d["context_tags"] = json.loads(d["context_tags"])
        d["emotional_indicators"] = json.loads(d["emotional_indicators"])
        d["preferences_used"] = json.loads(d["preferences_used"])
        d["associations_affected"] = json.loads(d["associations_affected"])
        d["preferences_affected"] = json.loads(d["preferences_affected"])
        return Signal.from_dict(d)


class PreferenceStorageManager:
    """
    Facade that owns the single SQLite connection and exposes typed
    sub-managers for each entity (preferences, associations, contexts,
    signals).  All sub-managers share the same on-disk database.
    """

    _CURRENT_VERSION = 1

    def __init__(self, base_dir: Optional[str] = None) -> None:
        if base_dir is None:
            base_dir = os.path.expanduser("~/.adaptive-cli")
        self.base_dir = Path(base_dir)
        db_path = self.base_dir / "preferences" / "adaptive.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.commit()
        self._apply_migrations()
        self._closed = False
        self.db_path = db_path
        self.preferences  = PreferenceStorage(self._conn)
        self.associations = AssociationStorage(self._conn)
        self.contexts     = ContextStorage(self._conn)
        self.signals      = SignalStorage(self._conn)

    def _apply_migrations(self) -> None:
        """Ensure schema_version reflects the current version. Runs pending migrations."""
        row = self._conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        current = row[0] if row[0] is not None else 0

        if current < self._CURRENT_VERSION:
            # Version 1: initial SQLite schema (preferences, associations, contexts, signals)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (self._CURRENT_VERSION, datetime.now().isoformat()),
                )
            print(f"  [storage] Applied migration: schema v{self._CURRENT_VERSION}")

    def get_storage_info(self) -> Dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "preferences_count": self._conn.execute(
                "SELECT COUNT(*) FROM preferences"
            ).fetchone()[0],
            "associations_count": self._conn.execute(
                "SELECT COUNT(*) FROM associations"
            ).fetchone()[0],
            "contexts_count": self._conn.execute(
                "SELECT COUNT(*) FROM contexts"
            ).fetchone()[0],
            "signals_count": self._conn.execute(
                "SELECT COUNT(*) FROM signals"
            ).fetchone()[0],
        }

    def backup(self, backup_name: Optional[str] = None) -> str:
        """Back up the live database using SQLite's online backup API."""
        if backup_name is None:
            backup_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.base_dir / "backups" / backup_name
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / "adaptive.db"
        dst_conn = sqlite3.connect(str(backup_path))
        try:
            self._conn.backup(dst_conn)
            result = dst_conn.execute("PRAGMA integrity_check(1)").fetchone()[0]
            if result != "ok":
                raise RuntimeError(
                    f"Backup integrity check failed at {backup_path}: {result}"
                )
        except sqlite3.Error as e:
            raise RuntimeError(
                f"Database backup failed while writing to {backup_path}: {e}"
            ) from e
        finally:
            dst_conn.close()
        return str(backup_dir)

    def prune_old_signals(self, max_age_days: int = 90) -> int:
        """Delete signals older than *max_age_days*. Returns count removed."""
        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM signals WHERE timestamp < ?", (cutoff,)
            )
        return cursor.rowcount

    def delete_preference(self, pref_id: str) -> None:
        """Convenience delegate — remove a preference by ID."""
        self.preferences.delete_preference(pref_id)

    def delete_signal(self, signal_id: str) -> None:
        """Convenience delegate — remove a signal by ID."""
        self.signals.delete_signal(signal_id)

    def reset(self) -> None:
        """Wipe all rows from every table (schema stays intact)."""
        with self._conn:
            for table in ("preferences", "associations", "contexts", "signals"):
                self._conn.execute(f"DELETE FROM {table}")

    def close(self) -> None:
        """Close the SQLite connection and checkpoint the WAL file. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._conn.close()

    def __enter__(self) -> "PreferenceStorageManager":
        return self

    def __exit__(self, _exc_type: object, _exc_val: object, _exc_tb: object) -> None:
        self.close()
