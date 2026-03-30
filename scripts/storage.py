"""
storage.py - SQLite storage for preferences, associations, signals, contexts.

Database lives at <base_dir>/preferences/adaptive.db (single file).
All nested objects (LearningData, context preferences, signal lists) are
stored as JSON TEXT blobs so callers never deal with join queries.
"""

import json
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.models import (
    Association, AssociationLearning, ContextStack,
    LearningData, Preference, Signal,
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
"""


class SQLiteDB:
    """
    Base class: opens (or creates) the shared SQLite database and applies
    the schema. Each subclass gets a reference to the same connection.

    WAL mode is enabled once at open time so reads and writes don't block
    each other — important when the CLI and background processors run
    concurrently.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.commit()
