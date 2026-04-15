"""
storage.py - SQLite storage for preferences, associations, signals, contexts.

Database lives at <base_dir>/preferences/adaptive.db (single file).
All nested objects (LearningData, context preferences, signal lists) are
stored as JSON TEXT blobs so callers never deal with join queries.
"""


class JSONLStorageReadError(Exception):
    """Raised when reading a JSONL file encounters parse errors.

    Kept for backward compatibility with tests written against the JSONL-era
    storage layer. The SQLite implementation never raises this at runtime.
    """

    def __init__(self, filepath, errors):
        self.filepath = filepath
        self.errors = errors
        super().__init__(f"Malformed JSONL in {filepath}: {errors}")

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from scripts.models import (
    Association, ContextStack,
    Preference, Signal,
)
from scripts.behaviors import BehaviorStorage, BEHAVIOR_SCHEMA
from adaptive_preference_engine.knowledge import KnowledgeEntry

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
    association_type    TEXT    DEFAULT 'correlation',
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

CREATE TABLE IF NOT EXISTS knowledge (
    id              TEXT PRIMARY KEY,
    partition       TEXT NOT NULL,
    category        TEXT NOT NULL,
    title           TEXT NOT NULL,
    tags            TEXT NOT NULL,
    content         TEXT NOT NULL,
    confidence      REAL DEFAULT 1.0,
    source          TEXT DEFAULT 'explicit',
    machine_origin  TEXT,
    decay_exempt    INTEGER DEFAULT 0,
    access_count    INTEGER DEFAULT 0,
    token_estimate  INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL,
    last_used       TEXT NOT NULL,
    archived        INTEGER DEFAULT 0,
    ref_path        TEXT,
    content_hash    TEXT
);
CREATE INDEX IF NOT EXISTS idx_know_partition ON knowledge(partition);
CREATE INDEX IF NOT EXISTS idx_know_category  ON knowledge(category);
CREATE INDEX IF NOT EXISTS idx_know_archived  ON knowledge(archived);
CREATE INDEX IF NOT EXISTS idx_know_content_hash ON knowledge(content_hash);

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT NOT NULL
);
"""


class _LockedConnection:
    """
    Thin proxy around a sqlite3.Connection that serialises all access via a
    threading.RLock. RLock (not Lock) is required because the `with self._conn:`
    transaction pattern acquires the lock in __enter__, then calls execute()
    inside the block — which would deadlock on a plain Lock.

    Lock scope covers execute, commit, and the transaction boundary (__enter__/
    __exit__) so that no thread can execute or commit while another is mid-
    transaction. backup() also holds the lock for its full duration.
    """

    def __init__(self, conn: sqlite3.Connection, lock) -> None:  # lock: threading.RLock instance
        self._conn = conn
        self._lock = lock

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def executescript(self, sql: str) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.executescript(sql)

    def executemany(self, sql: str, params) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.executemany(sql, params)

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def backup(self, target) -> None:
        with self._lock:
            self._conn.backup(target)

    def close(self) -> None:
        self._conn.close()

    def __getattr__(self, name: str):
        # Proxy any attribute not explicitly defined above to the underlying
        # connection (e.g. row_factory, isolation_level, in_transaction).
        # This prevents AttributeError on legitimate sqlite3.Connection attrs.
        return getattr(self._conn, name)

    def __enter__(self) -> "_LockedConnection":
        self._lock.acquire()
        try:
            self._conn.__enter__()
        except Exception:
            self._lock.release()
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            self._conn.__exit__(exc_type, exc_val, exc_tb)
        finally:
            self._lock.release()


class SQLiteDB:
    """
    Base class: holds a reference to a shared SQLite connection.
    Each subclass gets the same connection passed in from the manager.

    WAL mode is enabled once at open time so reads and writes don't block
    each other — important when the CLI and background processors run
    concurrently.
    """

    def __init__(self, conn: Union[_LockedConnection, sqlite3.Connection]) -> None:
        self._conn = conn


class PreferenceStorage(SQLiteDB):
    """CRUD for the `preferences` table."""

    def __init__(self, conn: Union[_LockedConnection, sqlite3.Connection], filepath: Optional[Path] = None) -> None:
        super().__init__(conn)
        # Compatibility: JSONL-era tests write to this file and expect read_all()
        # to parse it.  When filepath is None (default), read_all() falls back to
        # the SQLite store instead.
        self.filepath: Optional[Path] = filepath
        self.last_read_errors: List[Dict] = []

    def read_all(self, skip_invalid: bool = False) -> List[Dict]:
        """Read raw preference dicts from the JSONL file (JSONL-era compatibility API).

        If self.filepath does not exist, returns an empty list.
        When skip_invalid is False a bad line raises JSONLStorageReadError.
        When skip_invalid is True, bad lines are skipped and recorded in
        self.last_read_errors.
        """
        self.last_read_errors = []
        if self.filepath is None or not self.filepath.exists():
            return []
        records: List[Dict] = []
        errors: List[Dict] = []
        with open(self.filepath) as fh:
            for line_number, raw in enumerate(fh, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    records.append(json.loads(raw))
                except json.JSONDecodeError as exc:
                    entry = {"line_number": line_number, "message": str(exc)}
                    errors.append(entry)
        if errors:
            self.last_read_errors = errors
            if not skip_invalid:
                raise JSONLStorageReadError(self.filepath, errors)
        return records

    def get_all_preferences(self) -> List[Preference]:
        """Return all preferences from SQLite, raising JSONLStorageReadError if the
        JSONL file exists and contains parse errors (JSONL-era compatibility)."""
        if self.filepath is not None and self.filepath.exists():
            # Trigger JSONL validation — raises JSONLStorageReadError on bad lines.
            self.read_all(skip_invalid=False)
        rows = self._conn.execute("SELECT * FROM preferences").fetchall()
        return [self._row_to_preference(r) for r in rows]

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
                    (id, from_id, to_id, association_type, bidirectional,
                     strength_forward, strength_backward, learning_forward,
                     learning_backward, description, context_tags, created,
                     time_decay_factor, last_decay_applied)
                VALUES
                    (:id, :from_id, :to_id, :association_type, :bidirectional,
                     :strength_forward, :strength_backward, :learning_forward,
                     :learning_backward, :description, :context_tags, :created,
                     :time_decay_factor, :last_decay_applied)
                ON CONFLICT(id) DO UPDATE SET
                    from_id            = excluded.from_id,
                    to_id              = excluded.to_id,
                    association_type   = excluded.association_type,
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


class KnowledgeStorage(SQLiteDB):
    """CRUD for the `knowledge` table."""

    def save_entry(self, entry: KnowledgeEntry) -> None:
        d = entry.to_dict()
        # Compute content hash for deduplication
        hash_data = f"{entry.title}\n{entry.content}\n{entry.category}\n{entry.partition}"
        content_hash = hashlib.sha256(hash_data.encode("utf-8")).hexdigest()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO knowledge
                    (id, partition, category, title, tags, content, confidence,
                     source, machine_origin, decay_exempt, access_count,
                     token_estimate, created_at, last_used, archived, ref_path,
                     expires_at, expires_when, expires_when_tag, content_hash)
                VALUES
                    (:id, :partition, :category, :title, :tags, :content, :confidence,
                     :source, :machine_origin, :decay_exempt, :access_count,
                     :token_estimate, :created_at, :last_used, :archived, :ref_path,
                     :expires_at, :expires_when, :expires_when_tag, :content_hash)
                ON CONFLICT(id) DO UPDATE SET
                    partition       = excluded.partition,
                    category        = excluded.category,
                    title           = excluded.title,
                    tags            = excluded.tags,
                    content         = excluded.content,
                    confidence      = excluded.confidence,
                    source          = excluded.source,
                    machine_origin  = excluded.machine_origin,
                    decay_exempt    = excluded.decay_exempt,
                    access_count    = excluded.access_count,
                    token_estimate  = excluded.token_estimate,
                    last_used       = excluded.last_used,
                    archived        = excluded.archived,
                    ref_path        = excluded.ref_path,
                    expires_at      = excluded.expires_at,
                    expires_when    = excluded.expires_when,
                    expires_when_tag = excluded.expires_when_tag,
                    content_hash    = excluded.content_hash
                """,
                {
                    **d,
                    "tags": json.dumps(d["tags"]),
                    "decay_exempt": int(d["decay_exempt"]),
                    "archived": int(d["archived"]),
                    "content_hash": content_hash,
                },
            )

    def get_entry(self, entry_id: str) -> Optional[KnowledgeEntry]:
        row = self._conn.execute(
            "SELECT * FROM knowledge WHERE id = ?", (entry_id,)
        ).fetchone()
        return self._row_to_entry(row) if row else None

    def get_entries_by_partition(self, partition: str, include_archived: bool = False) -> List[KnowledgeEntry]:
        if include_archived:
            rows = self._conn.execute(
                "SELECT * FROM knowledge WHERE partition = ?", (partition,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM knowledge WHERE partition = ? AND archived = 0", (partition,)
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get_entries_by_category(self, category: str, include_archived: bool = False) -> List[KnowledgeEntry]:
        if include_archived:
            rows = self._conn.execute(
                "SELECT * FROM knowledge WHERE category = ?", (category,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM knowledge WHERE category = ? AND archived = 0", (category,)
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def search_by_tags(self, tags: List[str], include_archived: bool = False) -> List[KnowledgeEntry]:
        """Return entries that have ANY of the provided tags (OR logic)."""
        all_entries = self.get_all_entries(include_archived=include_archived)
        matches = []
        for entry in all_entries:
            if any(tag in entry.tags for tag in tags):
                matches.append(entry)
        return matches

    def get_all_entries(self, include_archived: bool = False) -> List[KnowledgeEntry]:
        if include_archived:
            rows = self._conn.execute("SELECT * FROM knowledge").fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM knowledge WHERE archived = 0").fetchall()
        return [self._row_to_entry(r) for r in rows]

    def record_access(self, entry_id: str) -> None:
        """Increment access_count and update last_used timestamp."""
        with self._conn:
            self._conn.execute(
                """
                UPDATE knowledge
                SET access_count = access_count + 1,
                    last_used = ?
                WHERE id = ?
                """,
                (datetime.now().isoformat(), entry_id),
            )

    def archive_entry(self, entry_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE knowledge SET archived = 1 WHERE id = ?", (entry_id,)
            )

    def unarchive_entry(self, entry_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE knowledge SET archived = 0 WHERE id = ?", (entry_id,)
            )

    def delete_entry(self, entry_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM knowledge WHERE id = ?", (entry_id,))

    def archive_expired(self) -> int:
        """Archive entries where expires_at is past today. Returns count archived."""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE knowledge SET archived = 1
                WHERE expires_at IS NOT NULL
                  AND expires_at < ?
                  AND archived = 0
                """,
                (today,),
            )
            return cursor.rowcount

    def find_triggered_entries(self, signals_conn) -> List[KnowledgeEntry]:
        """Find entries whose expires_when_tag has a matching signal after created_at.

        Args:
            signals_conn: Connection to the database containing the signals table.
                          For confidential DB entries, this is the public DB connection.
        """
        entries = self._conn.execute(
            """SELECT * FROM knowledge
               WHERE expires_when_tag IS NOT NULL
                 AND archived = 0"""
        ).fetchall()

        triggered = []
        for row in entries:
            entry = self._row_to_entry(row)
            tag = entry.expires_when_tag
            count = signals_conn.execute(
                """SELECT COUNT(*) FROM signals
                   WHERE ',' || context_tags || ',' LIKE '%,' || ? || ',%'
                     AND timestamp > ?""",
                (tag, entry.created_at),
            ).fetchone()[0]
            if count > 0:
                triggered.append(entry)
        return triggered

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> KnowledgeEntry:
        d = dict(row)
        d["tags"] = json.loads(d["tags"])
        d["decay_exempt"] = bool(d["decay_exempt"])
        d["archived"] = bool(d["archived"])
        return KnowledgeEntry.from_dict(d)


class PreferenceStorageManager:
    """
    Facade that owns the single SQLite connection and exposes typed
    sub-managers for each entity (preferences, associations, contexts,
    signals).  All sub-managers share the same on-disk database.
    """

    _CURRENT_VERSION = 7

    def __init__(self, base_dir: Optional[str] = None) -> None:
        if base_dir is None:
            base_dir = os.path.expanduser("~/.adaptive-cli")
        self.base_dir = Path(base_dir)
        db_path = self.base_dir / "preferences" / "adaptive.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        _raw_conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _raw_conn.row_factory = sqlite3.Row
        self._conn = _LockedConnection(_raw_conn, self._lock)
        self._conn.executescript(_SCHEMA)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.commit()
        self._apply_migrations()
        self._closed = False
        self.db_path = db_path
        prefs_dir = db_path.parent
        self.preferences  = PreferenceStorage(
            self._conn, filepath=prefs_dir / "all_preferences.jsonl"
        )
        self.associations = AssociationStorage(self._conn)
        self.contexts     = ContextStorage(self._conn)
        self.signals      = SignalStorage(self._conn)
        self.behaviors    = BehaviorStorage(self._conn)
        self.knowledge    = KnowledgeStorage(self._conn)

    def _apply_migrations(self) -> None:
        """Ensure schema_version reflects the current version. Runs pending migrations."""
        row = self._conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        current = row[0] if row[0] is not None else 0

        if current < 1:
            # Version 1: initial SQLite schema (preferences, associations, contexts, signals)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (1, datetime.now().isoformat()),
                )

        if current < 2:
            # v2: behavior tables
            self._conn.executescript(BEHAVIOR_SCHEMA)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (2, datetime.now().isoformat()),
                )

        if current < 3:
            # v3: knowledge table + decay_exempt on preferences + machine_origin on signals
            # Knowledge table DDL is already in _SCHEMA (runs on fresh DBs).
            # For existing DBs, create the table if it doesn't exist.
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    id              TEXT PRIMARY KEY,
                    partition       TEXT NOT NULL,
                    category        TEXT NOT NULL,
                    title           TEXT NOT NULL,
                    tags            TEXT NOT NULL,
                    content         TEXT NOT NULL,
                    confidence      REAL DEFAULT 1.0,
                    source          TEXT DEFAULT 'explicit',
                    machine_origin  TEXT,
                    decay_exempt    INTEGER DEFAULT 0,
                    access_count    INTEGER DEFAULT 0,
                    token_estimate  INTEGER DEFAULT 0,
                    created_at      TEXT NOT NULL,
                    last_used       TEXT NOT NULL,
                    archived        INTEGER DEFAULT 0,
                    ref_path        TEXT,
                    expires_at      TEXT,
                    expires_when    TEXT,
                    expires_when_tag TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_know_partition ON knowledge(partition);
                CREATE INDEX IF NOT EXISTS idx_know_category  ON knowledge(category);
                CREATE INDEX IF NOT EXISTS idx_know_archived  ON knowledge(archived);
            """)
            # Add decay_exempt column to preferences (for pruning support)
            try:
                self._conn.execute("ALTER TABLE preferences ADD COLUMN decay_exempt INTEGER DEFAULT 0")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists (fresh DB)
            # Add machine_origin column to signals (for multi-machine tracking)
            try:
                self._conn.execute("ALTER TABLE signals ADD COLUMN machine_origin TEXT")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists (fresh DB)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (3, datetime.now().isoformat()),
                )

        if current < 4:
            # v4: association_type column on associations (correlation/rule/directive)
            try:
                self._conn.execute(
                    "ALTER TABLE associations ADD COLUMN association_type TEXT DEFAULT 'correlation'"
                )
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists (fresh DB)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (4, datetime.now().isoformat()),
                )

        if current < 5:
            # v5: ref_path column on knowledge (compaction system)
            try:
                self._conn.execute("ALTER TABLE knowledge ADD COLUMN ref_path TEXT")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists (fresh DB)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (5, datetime.now().isoformat()),
                )

        if current < 6:
            # v6: temporal expiry fields on knowledge (expires_at, expires_when, expires_when_tag)
            for col in ("expires_at TEXT", "expires_when TEXT", "expires_when_tag TEXT"):
                try:
                    self._conn.execute(f"ALTER TABLE knowledge ADD COLUMN {col}")
                    self._conn.commit()
                except sqlite3.OperationalError:
                    pass  # Column already exists (fresh DB)
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS sync_meta (
                    last_push_at TEXT,
                    last_pull_at TEXT
                );
            """)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (6, datetime.now().isoformat()),
                )

        if current < 7:
            # v7: content_hash column + index for O(1) deduplication
            try:
                self._conn.execute("ALTER TABLE knowledge ADD COLUMN content_hash TEXT")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists (fresh DB)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_know_content_hash ON knowledge(content_hash)")
            self._conn.commit()
            with self._conn:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (7, datetime.now().isoformat()),
                )

    def get_storage_info(self) -> Dict[str, Any]:
        return {
            "base_dir": str(self.base_dir),
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
            "behaviors_count": self._conn.execute(
                "SELECT COUNT(*) FROM behaviors"
            ).fetchone()[0],
            "knowledge_count": self._conn.execute(
                "SELECT COUNT(*) FROM knowledge"
            ).fetchone()[0],
        }

    def backup(self, backup_name: Optional[str] = None) -> str:
        """Back up the live database using SQLite's online backup API."""
        if backup_name is None:
            backup_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Reject names that could escape the backups directory
        if "/" in backup_name or "\\" in backup_name or ".." in backup_name:
            raise ValueError(f"Invalid backup_name (must not contain path separators or '..'): {backup_name!r}")
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
            rowcount = cursor.rowcount
        return rowcount

    def delete_preference(self, pref_id: str) -> bool:
        """Remove a preference by ID, cascading to associations and context refs.

        Returns True if the preference existed and was deleted, False if it was
        not found.
        """
        if self.preferences.get_preference(pref_id) is None:
            return False

        # Cascade: remove associations that reference this preference
        assocs = self.associations.get_associations_for_preference(pref_id)
        for assoc in assocs:
            with self._conn:
                self._conn.execute("DELETE FROM associations WHERE id = ?", (assoc.id,))

        # Cascade: remove this preference from any context's preference map
        contexts = self.contexts.get_all_contexts()
        for ctx in contexts:
            if pref_id in ctx.preferences:
                del ctx.preferences[pref_id]
                self.contexts.save_context(ctx)

        self.preferences.delete_preference(pref_id)
        return True

    def delete_signal(self, signal_id: str) -> None:
        """Convenience delegate — remove a signal by ID."""
        self.signals.delete_signal(signal_id)

    def reset(self) -> None:
        """Wipe all rows from every table (schema stays intact)."""
        _RESET_TABLES = frozenset({
            "behavior_behavior_deps", "behavior_pref_deps", "behaviors",
            "preferences", "associations", "contexts", "signals",
            "knowledge",
        })
        with self._conn:
            for table in _RESET_TABLES:
                assert table in _RESET_TABLES  # belt-and-suspenders: only allowlisted names
                self._conn.execute(f"DELETE FROM {table}")

    def update_sync_meta(self, push_at=None, pull_at=None):
        row = self._conn.execute("SELECT COUNT(*) FROM sync_meta").fetchone()[0]
        if row == 0:
            self._conn.execute(
                "INSERT INTO sync_meta (last_push_at, last_pull_at) VALUES (?, ?)",
                (push_at, pull_at),
            )
        else:
            if push_at:
                self._conn.execute("UPDATE sync_meta SET last_push_at = ?", (push_at,))
            if pull_at:
                self._conn.execute("UPDATE sync_meta SET last_pull_at = ?", (pull_at,))
        self._conn.commit()

    def get_sync_meta(self):
        row = self._conn.execute("SELECT * FROM sync_meta").fetchone()
        if row:
            return {"last_push_at": row["last_push_at"], "last_pull_at": row["last_pull_at"]}
        return {"last_push_at": None, "last_pull_at": None}

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


class ConfidentialStorageManager:
    """Lightweight storage manager for the confidential database.

    Only exposes a KnowledgeStorage — confidential DB has no preferences,
    associations, contexts, or signals (those live in the public DB).
    """

    def __init__(self, base_dir=None):
        if base_dir is None:
            base_dir = os.path.expanduser("~/.adaptive-cli")
        self.base_dir = Path(base_dir)
        db_path = self.base_dir / "ape-confidential.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        _raw_conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _raw_conn.row_factory = sqlite3.Row
        self._conn = _LockedConnection(_raw_conn, self._lock)
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id              TEXT PRIMARY KEY,
                partition       TEXT NOT NULL,
                category        TEXT NOT NULL,
                title           TEXT NOT NULL,
                tags            TEXT NOT NULL,
                content         TEXT NOT NULL,
                confidence      REAL DEFAULT 1.0,
                source          TEXT DEFAULT 'explicit',
                machine_origin  TEXT,
                decay_exempt    INTEGER DEFAULT 0,
                access_count    INTEGER DEFAULT 0,
                token_estimate  INTEGER DEFAULT 0,
                created_at      TEXT NOT NULL,
                last_used       TEXT NOT NULL,
                archived        INTEGER DEFAULT 0,
                ref_path        TEXT,
                expires_at      TEXT,
                expires_when    TEXT,
                expires_when_tag TEXT,
                content_hash    TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_know_partition ON knowledge(partition);
            CREATE INDEX IF NOT EXISTS idx_know_category  ON knowledge(category);
            CREATE INDEX IF NOT EXISTS idx_know_archived  ON knowledge(archived);
            CREATE INDEX IF NOT EXISTS idx_know_content_hash ON knowledge(content_hash);
            CREATE TABLE IF NOT EXISTS sync_meta (
                last_push_at TEXT,
                last_pull_at TEXT
            );
        """)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.commit()
        self._closed = False
        self.db_path = db_path
        self.knowledge = KnowledgeStorage(self._conn)

    def close(self):
        if not self._closed:
            self._conn.close()
            self._closed = True

    def update_sync_meta(self, push_at=None, pull_at=None):
        row = self._conn.execute("SELECT COUNT(*) FROM sync_meta").fetchone()[0]
        if row == 0:
            self._conn.execute(
                "INSERT INTO sync_meta (last_push_at, last_pull_at) VALUES (?, ?)",
                (push_at, pull_at),
            )
        else:
            if push_at:
                self._conn.execute("UPDATE sync_meta SET last_push_at = ?", (push_at,))
            if pull_at:
                self._conn.execute("UPDATE sync_meta SET last_pull_at = ?", (pull_at,))
        self._conn.commit()

    def get_sync_meta(self):
        row = self._conn.execute("SELECT * FROM sync_meta").fetchone()
        if row:
            return {"last_push_at": row["last_push_at"], "last_pull_at": row["last_pull_at"]}
        return {"last_push_at": None, "last_pull_at": None}
