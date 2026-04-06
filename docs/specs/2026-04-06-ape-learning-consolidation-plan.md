# APE + Learning Plugin Consolidation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Absorb the learning-agent plugin into APE, adding a knowledge store, enhanced sync, pruning/staleness management, and a unified `/ape` skill.

**Architecture:** New `knowledge` SQLite table + `KnowledgeEntry` model + `KnowledgeStorage` sub-manager follow the existing APE pattern (dataclass model with to_dict/from_dict, SQLiteDB subclass with CRUD, CLI subcommand group). Sync extended to include knowledge.jsonl. Config chain: defaults in config.json, overrides from sync repo config.yaml.

**Tech Stack:** Python 3.9+, SQLite (WAL mode), argparse CLI, pytest, git

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/adaptive_preference_engine/knowledge.py` | KnowledgeEntry dataclass model |
| Create | `scripts/config.py` | APEConfig: defaults + sync repo overrides |
| Create | `scripts/migrate_learning.py` | One-time migration from learning plugin |
| Create | `tests/test_knowledge_model.py` | KnowledgeEntry model tests |
| Create | `tests/test_knowledge_storage.py` | KnowledgeStorage CRUD tests |
| Create | `tests/test_config.py` | Config loading + merge tests |
| Create | `tests/test_migration.py` | Migration script tests |
| Modify | `scripts/storage.py` | Add KnowledgeStorage, schema v3 migration |
| Modify | `scripts/models.py` | Re-export KnowledgeEntry for import convenience |
| Modify | `scripts/sync.py` | Add knowledge.jsonl export/import, sync diff, config.yaml |
| Modify | `scripts/cli.py` | Add knowledge + prune subcommands, enhance stats |
| Modify | `SKILL.md` | Rewrite for unified /ape skill |
| Modify | `README.md` | Document knowledge store + sync repo |

---

## Task 1: KnowledgeEntry Model

**Files:**
- Create: `src/adaptive_preference_engine/knowledge.py`
- Modify: `scripts/models.py` (re-export)
- Test: `tests/test_knowledge_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_knowledge_model.py
"""Tests for KnowledgeEntry model. Run: pytest tests/test_knowledge_model.py -v"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from adaptive_preference_engine.knowledge import KnowledgeEntry


class TestKnowledgeEntry:
    def test_create_with_defaults(self):
        entry = KnowledgeEntry(
            id="know_abc123",
            partition="projects/monitor-cinc",
            category="convention",
            title="Test Entry",
            tags=["test", "convention"],
            content="Some markdown content",
        )
        assert entry.confidence == 1.0
        assert entry.source == "explicit"
        assert entry.archived is False
        assert entry.decay_exempt is False
        assert entry.access_count == 0
        assert entry.token_estimate == 0

    def test_to_dict_round_trip(self):
        entry = KnowledgeEntry(
            id="know_abc123",
            partition="user",
            category="preference",
            title="User Prefs",
            tags=["pref", "style"],
            content="Prefers tables over bullets",
            confidence=0.9,
            source="migrated",
            machine_origin="glouie-macbook",
            decay_exempt=True,
            access_count=5,
            token_estimate=42,
        )
        d = entry.to_dict()
        restored = KnowledgeEntry.from_dict(d)
        assert restored.id == entry.id
        assert restored.partition == entry.partition
        assert restored.tags == ["pref", "style"]
        assert restored.decay_exempt is True
        assert restored.machine_origin == "glouie-macbook"
        assert restored.confidence == 0.9

    def test_from_dict_ignores_unknown_fields(self):
        d = {
            "id": "know_xyz",
            "partition": "domains/tools",
            "category": "convention",
            "title": "Tool Hints",
            "tags": ["tools"],
            "content": "Use glab not gitlab-cli",
            "unknown_field": "should be ignored",
        }
        entry = KnowledgeEntry.from_dict(d)
        assert entry.id == "know_xyz"
        assert not hasattr(entry, "unknown_field")

    def test_tags_stored_as_list(self):
        entry = KnowledgeEntry(
            id="know_tags",
            partition="user",
            category="preference",
            title="Tag Test",
            tags=["a", "b", "c"],
            content="test",
        )
        d = entry.to_dict()
        assert isinstance(d["tags"], list)
        assert d["tags"] == ["a", "b", "c"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/github/adaptive-preference-engine && python3 -m pytest tests/test_knowledge_model.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'adaptive_preference_engine.knowledge'`

- [ ] **Step 3: Write the KnowledgeEntry model**

```python
# src/adaptive_preference_engine/knowledge.py
"""KnowledgeEntry model — factual knowledge stored in APE's knowledge table."""

from dataclasses import dataclass, field, fields as dc_fields
from typing import List, Optional
from datetime import datetime


def _filter_fields(cls, data: dict) -> dict:
    """Return only keys that are declared fields on the dataclass cls."""
    known = {f.name for f in dc_fields(cls)}
    return {k: v for k, v in data.items() if k in known}


@dataclass
class KnowledgeEntry:
    """Factual knowledge entry (project context, conventions, decisions, workflows)."""
    id: str
    partition: str
    category: str
    title: str
    tags: List[str]
    content: str

    confidence: float = 1.0
    source: str = "explicit"
    machine_origin: Optional[str] = None
    decay_exempt: bool = False
    access_count: int = 0
    token_estimate: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_used: str = field(default_factory=lambda: datetime.now().isoformat())
    archived: bool = False

    def to_dict(self):
        return {
            "id": self.id,
            "partition": self.partition,
            "category": self.category,
            "title": self.title,
            "tags": self.tags,
            "content": self.content,
            "confidence": self.confidence,
            "source": self.source,
            "machine_origin": self.machine_origin,
            "decay_exempt": self.decay_exempt,
            "access_count": self.access_count,
            "token_estimate": self.token_estimate,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "archived": self.archived,
        }

    @staticmethod
    def from_dict(data):
        data = dict(data)
        return KnowledgeEntry(**_filter_fields(KnowledgeEntry, data))
```

- [ ] **Step 4: Add re-export in scripts/models.py**

Add at the end of `scripts/models.py`:

```python
# Re-export KnowledgeEntry for convenience
from adaptive_preference_engine.knowledge import KnowledgeEntry  # noqa: F401
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd ~/github/adaptive-preference-engine && python3 -m pytest tests/test_knowledge_model.py -v
```

Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
cd ~/github/adaptive-preference-engine && git add src/adaptive_preference_engine/knowledge.py tests/test_knowledge_model.py scripts/models.py && git commit -m "feat: add KnowledgeEntry model for factual knowledge store"
```

---

## Task 2: KnowledgeStorage SQLite Sub-Manager

**Files:**
- Modify: `scripts/storage.py`
- Test: `tests/test_knowledge_storage.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_knowledge_storage.py
"""Tests for KnowledgeStorage CRUD. Run: pytest tests/test_knowledge_storage.py -v"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.storage import PreferenceStorageManager
from adaptive_preference_engine.knowledge import KnowledgeEntry


def make_knowledge(**kwargs) -> KnowledgeEntry:
    from scripts.models import generate_id
    defaults = dict(
        id=generate_id("know"),
        partition="projects/test",
        category="convention",
        title="Test Knowledge",
        tags=["test"],
        content="Some test content here.",
        confidence=1.0,
        token_estimate=25,
    )
    defaults.update(kwargs)
    return KnowledgeEntry(**defaults)


@pytest.fixture
def mgr(tmp_path):
    return PreferenceStorageManager(str(tmp_path))


class TestKnowledgeStorage:
    def test_save_and_retrieve(self, mgr):
        entry = make_knowledge(id="know_001", title="Test Entry")
        mgr.knowledge.save_knowledge(entry)
        result = mgr.knowledge.get_knowledge("know_001")
        assert result is not None
        assert result.title == "Test Entry"
        assert result.tags == ["test"]

    def test_get_all_excludes_archived(self, mgr):
        mgr.knowledge.save_knowledge(make_knowledge(id="know_a", title="Active"))
        mgr.knowledge.save_knowledge(make_knowledge(id="know_b", title="Archived", archived=True))
        results = mgr.knowledge.get_all_knowledge()
        assert len(results) == 1
        assert results[0].id == "know_a"

    def test_get_all_includes_archived(self, mgr):
        mgr.knowledge.save_knowledge(make_knowledge(id="know_a"))
        mgr.knowledge.save_knowledge(make_knowledge(id="know_b", archived=True))
        results = mgr.knowledge.get_all_knowledge(include_archived=True)
        assert len(results) == 2

    def test_search_by_title(self, mgr):
        mgr.knowledge.save_knowledge(make_knowledge(id="know_1", title="Monitor CINC Notes"))
        mgr.knowledge.save_knowledge(make_knowledge(id="know_2", title="Textual Gotchas"))
        results = mgr.knowledge.search_knowledge("monitor")
        assert len(results) == 1
        assert results[0].id == "know_1"

    def test_search_by_tag(self, mgr):
        mgr.knowledge.save_knowledge(make_knowledge(id="know_1", tags=["cinc", "ops"]))
        mgr.knowledge.save_knowledge(make_knowledge(id="know_2", tags=["textual", "tui"]))
        results = mgr.knowledge.search_knowledge("cinc")
        assert len(results) == 1

    def test_search_by_content(self, mgr):
        mgr.knowledge.save_knowledge(make_knowledge(id="know_1", content="Always use feature branches"))
        mgr.knowledge.save_knowledge(make_knowledge(id="know_2", content="Prefer tables over bullets"))
        results = mgr.knowledge.search_knowledge("feature branches")
        assert len(results) == 1

    def test_archive_and_restore(self, mgr):
        mgr.knowledge.save_knowledge(make_knowledge(id="know_1"))
        mgr.knowledge.archive_knowledge("know_1")
        result = mgr.knowledge.get_knowledge("know_1")
        assert result.archived is True
        mgr.knowledge.restore_knowledge("know_1")
        result = mgr.knowledge.get_knowledge("know_1")
        assert result.archived is False

    def test_get_by_partition(self, mgr):
        mgr.knowledge.save_knowledge(make_knowledge(id="know_1", partition="projects/cinc"))
        mgr.knowledge.save_knowledge(make_knowledge(id="know_2", partition="domains/tools"))
        results = mgr.knowledge.get_knowledge_by_partition("projects/cinc")
        assert len(results) == 1
        assert results[0].id == "know_1"

    def test_upsert_on_save(self, mgr):
        entry = make_knowledge(id="know_1", title="Original")
        mgr.knowledge.save_knowledge(entry)
        entry.title = "Updated"
        mgr.knowledge.save_knowledge(entry)
        result = mgr.knowledge.get_knowledge("know_1")
        assert result.title == "Updated"

    def test_storage_info_includes_knowledge(self, mgr):
        mgr.knowledge.save_knowledge(make_knowledge(id="know_1"))
        info = mgr.get_storage_info()
        assert "knowledge_count" in info
        assert info["knowledge_count"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/github/adaptive-preference-engine && python3 -m pytest tests/test_knowledge_storage.py -v
```

Expected: FAIL — `AttributeError: 'PreferenceStorageManager' object has no attribute 'knowledge'`

- [ ] **Step 3: Add KnowledgeStorage class and schema to storage.py**

In `scripts/storage.py`, add the knowledge table DDL to the `_SCHEMA` string (after signals indexes):

```sql
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
    archived        INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_know_partition ON knowledge(partition);
CREATE INDEX IF NOT EXISTS idx_know_category  ON knowledge(category);
CREATE INDEX IF NOT EXISTS idx_know_archived  ON knowledge(archived);
```

Add import at top of storage.py:

```python
from adaptive_preference_engine.knowledge import KnowledgeEntry
```

Add the KnowledgeStorage class after SignalStorage:

```python
class KnowledgeStorage(SQLiteDB):
    """CRUD for the `knowledge` table."""

    def save_knowledge(self, entry: KnowledgeEntry) -> None:
        d = entry.to_dict()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO knowledge
                    (id, partition, category, title, tags, content, confidence,
                     source, machine_origin, decay_exempt, access_count,
                     token_estimate, created_at, last_used, archived)
                VALUES
                    (:id, :partition, :category, :title, :tags, :content, :confidence,
                     :source, :machine_origin, :decay_exempt, :access_count,
                     :token_estimate, :created_at, :last_used, :archived)
                ON CONFLICT(id) DO UPDATE SET
                    partition      = excluded.partition,
                    category       = excluded.category,
                    title          = excluded.title,
                    tags           = excluded.tags,
                    content        = excluded.content,
                    confidence     = excluded.confidence,
                    source         = excluded.source,
                    machine_origin = excluded.machine_origin,
                    decay_exempt   = excluded.decay_exempt,
                    access_count   = excluded.access_count,
                    token_estimate = excluded.token_estimate,
                    last_used      = excluded.last_used,
                    archived       = excluded.archived
                """,
                {**d,
                 "tags": json.dumps(d["tags"]),
                 "decay_exempt": int(d["decay_exempt"]),
                 "archived": int(d["archived"])},
            )

    def get_knowledge(self, entry_id: str) -> Optional[KnowledgeEntry]:
        row = self._conn.execute(
            "SELECT * FROM knowledge WHERE id = ?", (entry_id,)
        ).fetchone()
        return self._row_to_knowledge(row) if row else None

    def get_all_knowledge(self, include_archived: bool = False) -> List[KnowledgeEntry]:
        if include_archived:
            rows = self._conn.execute("SELECT * FROM knowledge").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM knowledge WHERE archived = 0"
            ).fetchall()
        return [self._row_to_knowledge(r) for r in rows]

    def search_knowledge(self, query: str, include_archived: bool = False) -> List[KnowledgeEntry]:
        pattern = f"%{query}%"
        sql = """
            SELECT * FROM knowledge
            WHERE (title LIKE ? OR tags LIKE ? OR content LIKE ?)
        """
        if not include_archived:
            sql += " AND archived = 0"
        rows = self._conn.execute(sql, (pattern, pattern, pattern)).fetchall()
        return [self._row_to_knowledge(r) for r in rows]

    def get_knowledge_by_partition(self, partition: str) -> List[KnowledgeEntry]:
        rows = self._conn.execute(
            "SELECT * FROM knowledge WHERE partition = ? AND archived = 0",
            (partition,),
        ).fetchall()
        return [self._row_to_knowledge(r) for r in rows]

    def archive_knowledge(self, entry_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE knowledge SET archived = 1 WHERE id = ?", (entry_id,)
            )

    def restore_knowledge(self, entry_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE knowledge SET archived = 0 WHERE id = ?", (entry_id,)
            )

    def delete_knowledge(self, entry_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM knowledge WHERE id = ?", (entry_id,))

    @staticmethod
    def _row_to_knowledge(row) -> KnowledgeEntry:
        d = dict(row)
        d["tags"] = json.loads(d["tags"])
        d["decay_exempt"] = bool(d["decay_exempt"])
        d["archived"] = bool(d["archived"])
        return KnowledgeEntry.from_dict(d)
```

In `PreferenceStorageManager.__init__`, add after `self.behaviors`:

```python
self.knowledge = KnowledgeStorage(self._conn)
```

In `get_storage_info()`, add:

```python
"knowledge_count": self._conn.execute(
    "SELECT COUNT(*) FROM knowledge"
).fetchone()[0],
```

In `reset()`, add `"knowledge"` to `_RESET_TABLES`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/github/adaptive-preference-engine && python3 -m pytest tests/test_knowledge_storage.py -v
```

Expected: 10 passed

- [ ] **Step 5: Run existing tests to verify no regressions**

```bash
cd ~/github/adaptive-preference-engine && python3 -m pytest tests/ -v
```

Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
cd ~/github/adaptive-preference-engine && git add scripts/storage.py tests/test_knowledge_storage.py && git commit -m "feat: add KnowledgeStorage sub-manager with CRUD and search"
```

---

## Task 3: Schema Migration v3 + New Columns

**Files:**
- Modify: `scripts/storage.py`

- [ ] **Step 1: Add v3 migration block**

In `_apply_migrations()`, after the `if current < 2:` block, add:

```python
if current < 3:
    # v3: knowledge table (created by _SCHEMA if fresh DB, but
    # existing DBs need the migration), plus new columns on
    # preferences and signals.
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
            archived        INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_know_partition ON knowledge(partition);
        CREATE INDEX IF NOT EXISTS idx_know_category  ON knowledge(category);
        CREATE INDEX IF NOT EXISTS idx_know_archived  ON knowledge(archived);
    """)
    # Add decay_exempt to preferences (idempotent)
    try:
        self._conn.execute(
            "ALTER TABLE preferences ADD COLUMN decay_exempt INTEGER DEFAULT 0"
        )
    except Exception:
        pass  # column already exists
    # Add machine_origin to signals (idempotent)
    try:
        self._conn.execute(
            "ALTER TABLE signals ADD COLUMN machine_origin TEXT"
        )
    except Exception:
        pass  # column already exists
    with self._conn:
        self._conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (3, datetime.now().isoformat()),
        )
```

Bump `_CURRENT_VERSION = 3`.

- [ ] **Step 2: Test migration on existing DB**

```bash
cd ~/github/adaptive-preference-engine && python3 -c "
from scripts.storage import PreferenceStorageManager
mgr = PreferenceStorageManager()
info = mgr.get_storage_info()
print('knowledge_count:', info['knowledge_count'])
row = mgr._conn.execute('SELECT MAX(version) FROM schema_version').fetchone()
print('schema_version:', row[0])
mgr.close()
"
```

Expected: `knowledge_count: 0`, `schema_version: 3`

- [ ] **Step 3: Commit**

```bash
cd ~/github/adaptive-preference-engine && git add scripts/storage.py && git commit -m "feat: schema v3 migration — knowledge table, decay_exempt, machine_origin"
```

---

## Task 4: Config System

**Files:**
- Create: `scripts/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
"""Tests for APEConfig. Run: pytest tests/test_config.py -v"""

import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.config import APEConfig


@pytest.fixture
def cfg_dir(tmp_path):
    return tmp_path


class TestAPEConfig:
    def test_defaults_without_config_file(self, cfg_dir):
        cfg = APEConfig.load(str(cfg_dir))
        assert cfg.get("token_budgets.knowledge") == 3000
        assert cfg.get("token_budgets.preferences") == 500
        assert cfg.get("pruning.convention") == 120

    def test_config_json_overrides_defaults(self, cfg_dir):
        config_path = cfg_dir / "config.json"
        config_path.write_text(json.dumps({
            "token_budgets": {"knowledge": 5000}
        }))
        cfg = APEConfig.load(str(cfg_dir))
        assert cfg.get("token_budgets.knowledge") == 5000
        assert cfg.get("token_budgets.preferences") == 500  # default preserved

    def test_sync_repo_yaml_overrides_all(self, cfg_dir):
        # Simulate sync repo config.yaml
        sync_dir = cfg_dir / "sync"
        sync_dir.mkdir()
        (sync_dir / "config.yaml").write_text(
            "token_budgets:\n  knowledge: 8000\npruning:\n  context: 15\n"
        )
        cfg = APEConfig.load(str(cfg_dir), sync_repo_path=str(sync_dir))
        assert cfg.get("token_budgets.knowledge") == 8000
        assert cfg.get("pruning.context") == 15
        assert cfg.get("pruning.preference") == 180  # default preserved

    def test_get_missing_key_returns_default(self, cfg_dir):
        cfg = APEConfig.load(str(cfg_dir))
        assert cfg.get("nonexistent.key", 42) == 42

    def test_save_defaults_creates_file(self, cfg_dir):
        APEConfig.save_defaults(str(cfg_dir))
        config_path = cfg_dir / "config.json"
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert "token_budgets" in data
        assert "pruning" in data
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/github/adaptive-preference-engine && python3 -m pytest tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.config'`

- [ ] **Step 3: Write APEConfig**

```python
# scripts/config.py
"""APEConfig — layered config: defaults -> config.json -> sync repo config.yaml."""

import json
import os
from pathlib import Path
from typing import Any, Optional

_DEFAULTS = {
    "token_budgets": {
        "preferences": 500,
        "knowledge": 3000,
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
        data = dict(_DEFAULTS)

        # Layer 1: local config.json
        config_json = Path(base_dir) / "config.json"
        if config_json.exists():
            with open(config_json) as f:
                local = json.load(f)
            data = _deep_merge(data, local)

        # Layer 2: sync repo config.yaml (if provided and exists)
        if sync_repo_path:
            config_yaml = Path(sync_repo_path) / "config.yaml"
            if config_yaml.exists():
                try:
                    import yaml
                    with open(config_yaml) as f:
                        remote = yaml.safe_load(f) or {}
                    data = _deep_merge(data, remote)
                except ImportError:
                    # yaml not available — skip sync repo overrides
                    pass

        return cls(data)

    def get(self, dotpath: str, default: Any = None) -> Any:
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/github/adaptive-preference-engine && python3 -m pytest tests/test_config.py -v
```

Expected: 5 passed (yaml tests may skip if pyyaml not installed — that's OK)

- [ ] **Step 5: Commit**

```bash
cd ~/github/adaptive-preference-engine && git add scripts/config.py tests/test_config.py && git commit -m "feat: add APEConfig with layered defaults + sync repo overrides"
```

---

## Task 5: Knowledge CLI Commands

**Files:**
- Modify: `scripts/cli.py`

- [ ] **Step 1: Add knowledge subparser group**

In `main()`, after the `buddy` subparser block and before `parser.add_argument("--base-dir", ...)`, add:

```python
# Knowledge commands
knowledge_parser = subparsers.add_parser("knowledge", help="Manage knowledge entries")
knowledge_sub = knowledge_parser.add_subparsers(dest="knowledge_subcommand")

know_add = knowledge_sub.add_parser("add", help="Add a knowledge entry")
know_add.add_argument("--title", required=True, help="Entry title")
know_add.add_argument("--partition", required=True, help="Partition path (e.g. projects/monitor-cinc)")
know_add.add_argument("--category", required=True,
                       choices=["preference", "pattern", "decision", "convention", "context"])
know_add.add_argument("--content", required=True, help="Markdown content")
know_add.add_argument("--tags", nargs="+", default=[], help="Tags for discovery")
know_add.add_argument("--confidence", type=float, default=1.0)
know_add.add_argument("--decay-exempt", action="store_true", dest="decay_exempt")

know_search = knowledge_sub.add_parser("search", help="Search knowledge entries")
know_search.add_argument("query", help="Search query")
know_search.add_argument("--partition", default=None, help="Filter by partition")
know_search.add_argument("--category", default=None, help="Filter by category")

know_show = knowledge_sub.add_parser("show", help="Show a knowledge entry")
know_show.add_argument("identifier", help="Entry ID or title substring")

know_list = knowledge_sub.add_parser("list", help="List knowledge entries")
know_list.add_argument("--partition", default=None, help="Filter by partition")
know_list.add_argument("--category", default=None, help="Filter by category")
know_list.add_argument("--include-archived", action="store_true", dest="include_archived")

know_archive = knowledge_sub.add_parser("archive", help="Archive a knowledge entry")
know_archive.add_argument("identifier", help="Entry ID or title substring")

know_restore = knowledge_sub.add_parser("restore", help="Restore an archived entry")
know_restore.add_argument("entry_id", help="Entry ID")

know_prune = knowledge_sub.add_parser("prune", help="Find and archive stale entries")
know_prune.add_argument("--dry-run", action="store_true", dest="dry_run")
```

- [ ] **Step 2: Add handler methods on AdaptivePreferenceCLI**

Add these methods to the `AdaptivePreferenceCLI` class:

```python
def cmd_knowledge_add(self, args):
    import socket
    from adaptive_preference_engine.knowledge import KnowledgeEntry
    entry = KnowledgeEntry(
        id=generate_id("know"),
        partition=args.partition,
        category=args.category,
        title=args.title,
        tags=args.tags,
        content=args.content,
        confidence=args.confidence,
        source="explicit",
        machine_origin=socket.gethostname(),
        decay_exempt=args.decay_exempt,
        token_estimate=len(args.content) // 4,
    )
    self.mgr.knowledge.save_knowledge(entry)
    print(f"Added: [{entry.partition}] {entry.title} ({entry.id})")

def cmd_knowledge_search(self, args):
    results = self.mgr.knowledge.search_knowledge(args.query)
    if args.partition:
        results = [r for r in results if r.partition == args.partition]
    if args.category:
        results = [r for r in results if r.category == args.category]
    if not results:
        print(f"No results for '{args.query}'")
        return
    print(f"Search: \"{args.query}\" ({len(results)} results)")
    print("-" * 60)
    for i, r in enumerate(results, 1):
        tags_str = ", ".join(r.tags) if r.tags else ""
        print(f"  {i}. [{r.partition}] {r.title}")
        print(f"     Tags: {tags_str} | {r.token_estimate} tokens | Confidence: {r.confidence}")

def cmd_knowledge_show(self, args):
    from datetime import datetime
    entry = self.mgr.knowledge.get_knowledge(args.identifier)
    if not entry:
        results = self.mgr.knowledge.search_knowledge(args.identifier)
        entry = results[0] if results else None
    if not entry:
        print(f"Not found: {args.identifier}")
        return
    # Increment access count and update last_used
    entry.access_count += 1
    entry.last_used = datetime.now().isoformat()
    self.mgr.knowledge.save_knowledge(entry)
    tags_str = ", ".join(entry.tags)
    print(f"-- {entry.title} " + "-" * max(0, 50 - len(entry.title)))
    print(f"  Partition:  {entry.partition}")
    print(f"  Category:   {entry.category}")
    print(f"  Confidence: {entry.confidence}")
    print(f"  Source:     {entry.source}")
    print(f"  Created:    {entry.created_at[:10]}")
    print(f"  Last used:  {entry.last_used[:10]} (accessed {entry.access_count} times)")
    print(f"  Tags:       {tags_str}")
    if entry.machine_origin:
        print(f"  Machine:    {entry.machine_origin}")
    print(f"  Tokens:     {entry.token_estimate}")
    print(f"  Archived:   {entry.archived}")
    print("-" * 60)
    print()
    print(entry.content)

def cmd_knowledge_list(self, args):
    include_archived = getattr(args, "include_archived", False)
    entries = self.mgr.knowledge.get_all_knowledge(include_archived=include_archived)
    if args.partition:
        entries = [e for e in entries if e.partition == args.partition]
    if args.category:
        entries = [e for e in entries if e.category == args.category]
    if not entries:
        print("No knowledge entries found.")
        return
    # Group by partition
    by_partition = {}
    for e in entries:
        by_partition.setdefault(e.partition, []).append(e)
    total_tokens = sum(e.token_estimate for e in entries)
    print(f"Knowledge Store: {len(entries)} entries ({total_tokens} tokens)")
    print("-" * 60)
    for partition in sorted(by_partition.keys()):
        items = by_partition[partition]
        ptokens = sum(e.token_estimate for e in items)
        print(f"  {partition}/  ({len(items)} entries, {ptokens} tokens)")
        for e in items:
            flag = " [archived]" if e.archived else ""
            print(f"    - {e.title} ({e.token_estimate}t, {e.category}){flag}")

def cmd_knowledge_archive(self, args):
    entry = self.mgr.knowledge.get_knowledge(args.identifier)
    if not entry:
        results = self.mgr.knowledge.search_knowledge(args.identifier)
        entry = results[0] if results else None
    if not entry:
        print(f"Not found: {args.identifier}")
        return
    self.mgr.knowledge.archive_knowledge(entry.id)
    print(f"Archived: [{entry.partition}] {entry.title}")

def cmd_knowledge_restore(self, args):
    self.mgr.knowledge.restore_knowledge(args.entry_id)
    print(f"Restored: {args.entry_id}")

def cmd_knowledge_prune(self, args):
    from datetime import datetime
    from scripts.config import APEConfig
    cfg = APEConfig.load(str(self.mgr.base_dir), sync_repo_path=self._get_sync_repo_path())
    entries = self.mgr.knowledge.get_all_knowledge()
    now = datetime.now()
    candidates = []
    for e in entries:
        if e.decay_exempt:
            continue
        threshold_days = cfg.get(f"pruning.{e.category}", 180)
        adjusted = threshold_days * (1 + e.confidence)
        try:
            last = datetime.fromisoformat(e.last_used)
            age_days = (now - last).days
        except (ValueError, TypeError):
            age_days = 0
        if age_days > adjusted:
            candidates.append((e, age_days, adjusted))
    if not candidates:
        print("No stale entries found.")
        return
    total_tokens = sum(e.token_estimate for e, _, _ in candidates)
    print(f"Prune Candidates ({len(candidates)} entries, {total_tokens} tokens):")
    print("-" * 60)
    for i, (e, age, thresh) in enumerate(candidates, 1):
        print(f"  {i}. [{e.partition}] {e.title} (unused {age}d, threshold {int(thresh)}d)")
    if args.dry_run:
        print("\n(dry run — no changes made)")
        return
    answer = input("\nArchive these entries? (y/n): ").strip().lower()
    if answer == "y":
        for e, _, _ in candidates:
            self.mgr.knowledge.archive_knowledge(e.id)
        print(f"Archived {len(candidates)} entries.")
    else:
        print("Skipped.")

def _get_sync_repo_path(self):
    """Read sync repo path from config, if configured."""
    config_file = self.mgr.base_dir / "sync_config.json"
    if config_file.exists():
        import json
        with open(config_file) as f:
            return json.load(f).get("repo_path")
    return None
```

- [ ] **Step 3: Add routing in main()**

In the routing block, after `elif args.command == "behavior":` block:

```python
elif args.command == "knowledge":
    if args.knowledge_subcommand == "add":
        cli.cmd_knowledge_add(args)
    elif args.knowledge_subcommand == "search":
        cli.cmd_knowledge_search(args)
    elif args.knowledge_subcommand == "show":
        cli.cmd_knowledge_show(args)
    elif args.knowledge_subcommand == "list":
        cli.cmd_knowledge_list(args)
    elif args.knowledge_subcommand == "archive":
        cli.cmd_knowledge_archive(args)
    elif args.knowledge_subcommand == "restore":
        cli.cmd_knowledge_restore(args)
    elif args.knowledge_subcommand == "prune":
        cli.cmd_knowledge_prune(args)
    else:
        knowledge_parser.print_help()
```

- [ ] **Step 4: Add prune top-level command**

Add a top-level `prune` parser that combines knowledge + preference pruning:

```python
prune_parser = subparsers.add_parser("prune", help="Prune stale entries across all domains")
prune_parser.add_argument("--dry-run", action="store_true", dest="dry_run")
```

Add handler:

```python
def cmd_prune_all(self, args):
    """Combined prune across knowledge and preferences."""
    print("Scanning knowledge entries...")
    self.cmd_knowledge_prune(args)
    # Preference pruning uses flat 180-day threshold on last_updated
    from datetime import datetime
    from scripts.config import APEConfig
    cfg = APEConfig.load(str(self.mgr.base_dir), sync_repo_path=self._get_sync_repo_path())
    pref_threshold = cfg.get("pruning.preference", 180)
    now = datetime.now()
    prefs = self.mgr.preferences.get_all_preferences()
    pref_candidates = []
    for p in prefs:
        if getattr(p, "decay_exempt", False):
            continue
        try:
            last = datetime.fromisoformat(p.last_updated)
            age_days = (now - last).days
        except (ValueError, TypeError):
            age_days = 0
        if age_days > pref_threshold:
            pref_candidates.append((p, age_days))
    if pref_candidates:
        print(f"\nStale Preferences ({len(pref_candidates)}):")
        print("-" * 60)
        for i, (p, age) in enumerate(pref_candidates, 1):
            print(f"  {i}. {p.path} (unused {age}d, threshold {pref_threshold}d)")
        if not args.dry_run:
            answer = input("\nRemove these preferences? (y/n): ").strip().lower()
            if answer == "y":
                for p, _ in pref_candidates:
                    self.mgr.delete_preference(p.id)
                print(f"Removed {len(pref_candidates)} preferences.")
```

Route: `elif args.command == "prune": cli.cmd_prune_all(args)`

- [ ] **Step 5: Smoke test**

```bash
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py knowledge add --title "Test Entry" --partition "projects/test" --category "convention" --content "This is a test" --tags test smoke
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py knowledge list
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py knowledge search "test"
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py knowledge show "Test Entry"
```

Expected: entry created, listed, searchable, showable

- [ ] **Step 6: Commit**

```bash
cd ~/github/adaptive-preference-engine && git add scripts/cli.py && git commit -m "feat: add knowledge CLI commands (add, search, show, list, archive, restore, prune)"
```

---

## Task 6: Sync Enhancement — knowledge.jsonl + sync diff

**Files:**
- Modify: `scripts/sync.py`
- Modify: `scripts/cli.py` (sync diff command)

- [ ] **Step 1: Add knowledge export to PreferenceSync.export()**

After the signals export block, add:

```python
knowledge_entries = mgr.knowledge.get_all_knowledge(include_archived=True)
_write_jsonl(dest_dir / "knowledge.jsonl", [k.to_dict() for k in knowledge_entries])
counts["knowledge"] = len(knowledge_entries)
```

- [ ] **Step 2: Add knowledge import to PreferenceSync.import_from()**

After the signals import loop, add:

```python
from adaptive_preference_engine.knowledge import KnowledgeEntry
counts["knowledge"] = 0
for d in _read_jsonl(src_dir / "knowledge.jsonl"):
    try:
        mgr.knowledge.save_knowledge(KnowledgeEntry.from_dict(d))
        counts["knowledge"] += 1
    except (ValueError, KeyError, TypeError) as e:
        print(f"  WARNING: Skipping malformed knowledge {d.get('id')}: {e}")
    except Exception as e:
        raise RuntimeError(
            f"Unexpected error importing knowledge {d.get('id')}: {e}"
        ) from e
```

- [ ] **Step 3: Add knowledge.jsonl to SyncRunner.push() git add list**

Change the `git_add` list to include `"knowledge.jsonl"`:

```python
git_add = ["all_preferences.jsonl", "associations.jsonl",
           "contexts.jsonl", "signals.jsonl", "knowledge.jsonl"]
```

Also add config.yaml sync:

```python
# Preserve config.yaml if it exists in the repo
if (self.repo / "config.yaml").exists():
    git_add.append("config.yaml")
```

- [ ] **Step 4: Add config.yaml loading to SyncRunner.pull()**

After the JSONL import, before agent restoration, add:

```python
# Load sync repo config overrides into local config
repo_config = self.repo / "config.yaml"
if repo_config.exists():
    from scripts.config import APEConfig
    APEConfig.save_defaults(str(self.mgr.base_dir))
```

- [ ] **Step 5: Add SyncRunner.diff() method**

```python
def diff(self) -> Dict:
    """Fetch remote and compare local vs remote record counts."""
    if not self.repo.exists():
        return {"status": "no_repo", "diffs": {}}
    try:
        _git(["fetch", "origin"], cwd=self.repo)
    except RuntimeError:
        pass  # offline is OK

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

    # Read remote versions (from fetched origin/main)
    diffs = {}
    for table, filename in file_map.items():
        path = self.repo / filename
        remote_count = len(_read_jsonl(path))
        diff = remote_count - local_counts[table]
        if diff != 0:
            diffs[table] = diff
    return {"status": "ok", "diffs": diffs, "local": local_counts}
```

- [ ] **Step 6: Add sync diff CLI command**

In `main()`, add `sync_sub.add_parser("diff", help="Show remote changes not yet pulled")`.

Add handler method:

```python
def cmd_sync_diff(self, args):
    from scripts.sync import SyncRunner
    sync_path = self._get_sync_repo_path()
    if not sync_path:
        print("Sync repo not configured. Run: adaptive-cli sync configure --repo-path <path>")
        return
    runner = SyncRunner(self.mgr, sync_path)
    result = runner.diff()
    if not result["diffs"]:
        print("Up to date — no remote changes.")
        return
    print("Remote Changes (not yet pulled)")
    print("-" * 40)
    for table, diff in result["diffs"].items():
        sign = "+" if diff > 0 else ""
        print(f"  {table}: {sign}{diff} entries")
    print(f"\nRun `adaptive-cli sync pull` to import.")
```

Route in sync block: `elif args.sync_subcommand == "diff": cli.cmd_sync_diff(args)`

- [ ] **Step 7: Update pending_counts() to include knowledge**

In `SyncRunner.pending_counts()`, add `"knowledge": "knowledge.jsonl"` to `file_map`.

- [ ] **Step 8: Commit**

```bash
cd ~/github/adaptive-preference-engine && git add scripts/sync.py scripts/cli.py && git commit -m "feat: sync knowledge.jsonl, add sync diff command, config.yaml support"
```

---

## Task 7: Stats Enhancement + Statusline Pruning Indicator

**Files:**
- Modify: `scripts/cli.py` (stats command)

- [ ] **Step 1: Update cmd_show_stats()**

Find the existing `cmd_show_stats` method and update it to include knowledge count and budget warnings:

```python
def cmd_show_stats(self, args):
    info = self.mgr.get_storage_info()
    from scripts.config import APEConfig
    cfg = APEConfig.load(str(self.mgr.base_dir), sync_repo_path=self._get_sync_repo_path())

    # Calculate token totals per domain
    knowledge_entries = self.mgr.knowledge.get_all_knowledge()
    knowledge_tokens = sum(e.token_estimate for e in knowledge_entries)
    # Estimate preference tokens (path + value ~ 20 tokens each)
    pref_tokens = info["preferences_count"] * 20
    signal_tokens = info["signals_count"] * 10

    budget_prefs = cfg.get("token_budgets.preferences", 500)
    budget_knowledge = cfg.get("token_budgets.knowledge", 3000)
    budget_total = cfg.get("token_budgets.total", 5000)

    warnings = []
    if pref_tokens > budget_prefs:
        warnings.append(f"preferences ({pref_tokens}/{budget_prefs} tokens)")
    if knowledge_tokens > budget_knowledge:
        warnings.append(f"knowledge ({knowledge_tokens}/{budget_knowledge} tokens)")
    if (pref_tokens + knowledge_tokens + signal_tokens) > budget_total:
        warnings.append(f"total ({pref_tokens + knowledge_tokens + signal_tokens}/{budget_total} tokens)")

    if getattr(args, "oneline", False):
        parts = f"{info['preferences_count']}p {info['associations_count']}a {info['signals_count']}s {info.get('knowledge_count', 0)}k"
        if warnings:
            parts += " [prune]"
        print(parts)
        return

    print("Storage Statistics")
    print("-" * 40)
    print(f"  Preferences:  {info['preferences_count']} (~{pref_tokens} tokens)")
    print(f"  Associations: {info['associations_count']}")
    print(f"  Contexts:     {info['contexts_count']}")
    print(f"  Signals:      {info['signals_count']}")
    print(f"  Knowledge:    {info.get('knowledge_count', 0)} ({knowledge_tokens} tokens)")
    print(f"  Behaviors:    {info.get('behaviors_count', 0)}")

    if warnings:
        print()
        print("Budget Warnings:")
        for w in warnings:
            print(f"  [!] Over budget: {w}")
        print("  Run `adaptive-cli prune` to review stale entries.")
```

- [ ] **Step 2: Verify statusline picks up new format**

The statusline at `~/.claude/statusline.sh` already reads `adaptive-cli stats --oneline`. The new format `Np Na Ns Nk [prune]` will automatically appear. No file changes needed — the `[prune]` indicator flows through.

- [ ] **Step 3: Commit**

```bash
cd ~/github/adaptive-preference-engine && git add scripts/cli.py && git commit -m "feat: enhance stats with knowledge count, token budgets, and prune indicator"
```

---

## Task 8: Migration Script

**Files:**
- Create: `scripts/migrate_learning.py`

- [ ] **Step 1: Write the migration script**

```python
#!/usr/bin/env python3
"""migrate_learning.py — One-time migration from learning plugin to APE knowledge store.

Usage:
    python3 scripts/migrate_learning.py --source ~/learning/glouie-assistant
    python3 scripts/migrate_learning.py --source ~/learning/glouie-assistant --dry-run
"""

import argparse
import hashlib
import json
import os
import re
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.storage import PreferenceStorageManager
from adaptive_preference_engine.knowledge import KnowledgeEntry


def load_yaml(path: Path) -> dict:
    """Load YAML file. Tries pyyaml first, falls back to basic parsing."""
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # Minimal YAML parsing for index.yaml (flat structure)
        raise RuntimeError("pyyaml required for migration. Install: pip install pyyaml")


def extract_content(md_path: Path) -> str:
    """Extract markdown content after YAML frontmatter."""
    text = md_path.read_text()
    # Split on --- delimiters
    parts = re.split(r'^---\s*$', text, maxsplit=2, flags=re.MULTILINE)
    if len(parts) >= 3:
        return parts[2].strip()
    return text.strip()


def migrate(source_dir: str, dry_run: bool = False) -> dict:
    source = Path(source_dir)
    index_path = source / "index.yaml"

    if not index_path.exists():
        print(f"ERROR: {index_path} not found")
        sys.exit(1)

    index = load_yaml(index_path)
    entries = index.get("entries", [])
    print(f"Found {len(entries)} entries in index.yaml")

    if not dry_run:
        mgr = PreferenceStorageManager()

    migrated = []
    errors = []
    hostname = socket.gethostname()

    for entry_meta in entries:
        file_path = source / entry_meta.get("file_path", "")
        if not file_path.exists():
            errors.append(f"Missing file: {file_path}")
            continue

        content = extract_content(file_path)
        if not content:
            errors.append(f"Empty content: {file_path}")
            continue

        knowledge = KnowledgeEntry(
            id=entry_meta["id"],
            partition=entry_meta.get("partition", "user"),
            category=entry_meta.get("category", "convention"),
            title=entry_meta.get("title", file_path.stem),
            tags=entry_meta.get("tags", []),
            content=content,
            confidence=entry_meta.get("confidence", 1.0),
            source="migrated",
            machine_origin=hostname,
            decay_exempt=entry_meta.get("decay_exempt", False),
            access_count=entry_meta.get("access_count", 0),
            token_estimate=entry_meta.get("token_estimate", len(content) // 4),
            created_at=entry_meta.get("created_at", ""),
            last_used=entry_meta.get("last_used", ""),
        )

        if dry_run:
            print(f"  [DRY RUN] Would migrate: [{knowledge.partition}] {knowledge.title} ({knowledge.token_estimate}t)")
        else:
            mgr.knowledge.save_knowledge(knowledge)
            print(f"  Migrated: [{knowledge.partition}] {knowledge.title} ({knowledge.token_estimate}t)")
        migrated.append(knowledge)

    if not dry_run:
        mgr.close()

    print(f"\n{'Would migrate' if dry_run else 'Migrated'}: {len(migrated)} entries")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors:
            print(f"  - {e}")

    return {"migrated": len(migrated), "errors": len(errors)}


def verify(expected_count: int) -> bool:
    """Verify migration by checking knowledge table count."""
    mgr = PreferenceStorageManager()
    entries = mgr.knowledge.get_all_knowledge(include_archived=True)
    mgr.close()
    actual = len(entries)
    if actual == expected_count:
        print(f"Verification PASSED: {actual} entries in knowledge table")
        return True
    else:
        print(f"Verification FAILED: expected {expected_count}, got {actual}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Migrate learning plugin to APE knowledge store")
    parser.add_argument("--source", required=True, help="Path to glouie-assistant repo")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    parser.add_argument("--verify-only", action="store_true", dest="verify_only",
                        help="Only verify existing migration")
    parser.add_argument("--expected", type=int, default=21,
                        help="Expected entry count for verification (default: 21)")
    args = parser.parse_args()

    if args.verify_only:
        ok = verify(args.expected)
        sys.exit(0 if ok else 1)

    result = migrate(args.source, dry_run=args.dry_run)

    if not args.dry_run and result["errors"] == 0:
        print("\nVerifying...")
        verify(result["migrated"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry run to verify parsing**

```bash
cd ~/github/adaptive-preference-engine && python3 scripts/migrate_learning.py --source ~/learning/glouie-assistant --dry-run
```

Expected: `[DRY RUN] Would migrate: ...` for all 21 entries, 0 errors

- [ ] **Step 3: Run actual migration**

```bash
cd ~/github/adaptive-preference-engine && python3 scripts/migrate_learning.py --source ~/learning/glouie-assistant
```

Expected: 21 migrated, 0 errors, verification PASSED

- [ ] **Step 4: Verify via CLI**

```bash
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py knowledge list
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py knowledge search "monitor-cinc"
```

Expected: 21 entries listed, monitor-cinc entries found

- [ ] **Step 5: Commit**

```bash
cd ~/github/adaptive-preference-engine && git add scripts/migrate_learning.py && git commit -m "feat: add migration script for learning plugin -> APE knowledge store"
```

---

## Task 9: Repo Cleanup — glouie-assistant

**Files:**
- Modify: `~/learning/glouie-assistant/` (multiple files)

- [ ] **Step 1: Export knowledge.jsonl to sync repo**

```bash
cd ~/github/adaptive-preference-engine && python3 -c "
from scripts.storage import PreferenceStorageManager
from scripts.sync import PreferenceSync
from pathlib import Path
mgr = PreferenceStorageManager()
dest = Path.home() / 'learning' / 'glouie-assistant'
# Export only knowledge
from adaptive_preference_engine.knowledge import KnowledgeEntry
import json
entries = mgr.knowledge.get_all_knowledge(include_archived=True)
out = dest / 'knowledge.jsonl'
with open(out, 'w') as f:
    for e in entries:
        f.write(json.dumps(e.to_dict()) + '\n')
print(f'Exported {len(entries)} entries to {out}')
mgr.close()
"
```

- [ ] **Step 2: Tag the pre-migration commit**

```bash
cd ~/learning/glouie-assistant && git tag pre-ape-migration
```

- [ ] **Step 3: Remove old learning plugin files**

```bash
cd ~/learning/glouie-assistant && rm -rf partitions/ index.yaml src/ config.yaml archive/
```

- [ ] **Step 4: Write new README.md**

```bash
cat > ~/learning/glouie-assistant/README.md << 'EOF'
# glouie-assistant

APE (Adaptive Preference Engine) sync repo — stores preferences, knowledge,
signals, and config for cross-machine synchronization.

## Structure

- `all_preferences.jsonl` — behavioral preferences
- `associations.jsonl` — preference associations
- `contexts.jsonl` — context stacks
- `signals.jsonl` — correction/feedback signals
- `knowledge.jsonl` — factual knowledge (project context, conventions, decisions)
- `agents/` — agent definitions synced to ~/.claude/agents/
- `claude_scripts/` — Claude Code scripts (statusline, settings)
- `config.yaml` — user config overrides (decay thresholds, token budgets)

## Usage

```bash
adaptive-cli sync configure --repo-path ~/learning/glouie-assistant
adaptive-cli sync push   # export local -> repo -> remote
adaptive-cli sync pull   # remote -> repo -> import local
adaptive-cli sync diff   # preview remote changes before pulling
```
EOF
```

- [ ] **Step 5: Write new config.yaml with APE override format**

```bash
cat > ~/learning/glouie-assistant/config.yaml << 'EOF'
# APE config overrides — synced across machines
# Defaults are in ~/.adaptive-cli/config.json
# Values here override the defaults.

token_budgets:
  preferences: 500
  knowledge: 3000
  signals: 200
  total: 5000

pruning:
  preference: 180
  pattern: 90
  decision: 60
  convention: 120
  context: 30
EOF
```

- [ ] **Step 6: Commit and push**

```bash
cd ~/learning/glouie-assistant && git add -A && git commit -m "migrate: convert learning plugin data to APE knowledge store

- Removed: partitions/, index.yaml, src/, config.yaml (old learning format)
- Added: knowledge.jsonl (21 entries migrated to APE format)
- Added: config.yaml (APE override format)
- Rewritten: README.md for APE sync repo
- Tag 'pre-ape-migration' marks the last learning-format commit"
cd ~/learning/glouie-assistant && git push origin main && git push origin pre-ape-migration
```

---

## Task 10: Deprecation — Remove Learning Plugin + Create /ape Skill

**Files:**
- Delete: `~/.claude/plugins/marketplaces/gskills/plugins/learning-agent/`
- Modify: `~/github/adaptive-preference-engine/SKILL.md`
- Modify: `~/github/adaptive-preference-engine/README.md`

- [ ] **Step 1: Remove the learning-agent plugin**

```bash
rm -rf ~/.claude/plugins/marketplaces/gskills/plugins/learning-agent/
```

- [ ] **Step 2: Rewrite SKILL.md for the unified /ape skill**

Replace the content of `SKILL.md` with the unified skill definition that covers both preference management (background) and knowledge management (user-initiated). The skill frontmatter `name` becomes `ape`. The description covers both domains. All existing preference/signal behavior is preserved. New sections document:

- `/ape status` — combined overview
- `/ape pref` — preference commands (existing)
- `/ape knowledge` — knowledge commands (new)
- `/ape sync` — sync commands (existing + diff)
- `/ape prune` — combined pruning
- `/ape stats` — storage stats with budget warnings

The SessionStart and PreCompact hooks continue using `adaptive-cli` directly — unchanged.

- [ ] **Step 3: Store the "develop this" workflow as a knowledge entry**

```bash
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py knowledge add \
  --title "develop — full feature development lifecycle" \
  --partition "workflows/develop" \
  --category "convention" \
  --tags develop lifecycle plan review implement mr \
  --decay-exempt \
  --content "## Trigger Phrases
- \"develop this\"
- \"build this out\"

## Scope
- personal: glouie/* repos (full workflow with SME gates)
- production: shared repos (adds compliance checks, stricter review)

## Phases
1. Plan - AI builds implementation plan from the request
2. Plan Review - Present to user, iterate until 95% confidence
3. Spec - Write detailed spec document
4. SME Spec Review - Dispatch domain subagents, exit gate: all rate A
5. Implement - Subagent-driven development in worktrees
6. Code SME Review - Dispatch code subagents, exit gate: all rate A
7. Commit and Push
8. Create MR
9. MR Feedback Loop - exit gate: merged or pending human approval only"
```

- [ ] **Step 4: Update README.md**

Add a "Knowledge Store" section and "Sync Repo" section to the existing README. Keep the existing content about preferences, signals, and behaviors.

- [ ] **Step 5: Configure sync repo path**

```bash
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py sync configure --repo-path ~/learning/glouie-assistant
```

- [ ] **Step 6: Push everything to sync repo**

```bash
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py sync push
```

- [ ] **Step 7: Commit APE changes**

```bash
cd ~/github/adaptive-preference-engine && git add SKILL.md README.md && git commit -m "feat: unified /ape skill, deprecate /learning and /adaptive-preferences

- SKILL.md rewritten for /ape unified entry point
- README updated with knowledge store and sync repo docs
- 'develop this' workflow stored as knowledge entry"
```

---

## Task 11: Integration Verification

**Files:** No new files

- [ ] **Step 1: Run all tests**

```bash
cd ~/github/adaptive-preference-engine && python3 -m pytest tests/ -v
```

Expected: all tests pass

- [ ] **Step 2: Verify knowledge entries**

```bash
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py knowledge list
```

Expected: 21 migrated entries + 1 workflow entry = 22 total

- [ ] **Step 3: Verify search**

```bash
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py knowledge search "monitor-cinc"
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py knowledge search "develop"
```

Expected: monitor-cinc entries found, develop workflow found

- [ ] **Step 4: Verify sync round-trip**

```bash
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py sync push
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py sync diff
```

Expected: push succeeds, diff shows "Up to date"

- [ ] **Step 5: Verify stats with budget indicators**

```bash
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py stats
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py stats --oneline
```

Expected: shows knowledge count, no budget warnings (under thresholds). Oneline format: `Np Na Ns Nk`

- [ ] **Step 6: Verify prune (dry run)**

```bash
cd ~/github/adaptive-preference-engine && python3 scripts/cli.py prune --dry-run
```

Expected: 0 candidates (all entries are decay_exempt)

- [ ] **Step 7: Verify learning plugin removed**

```bash
test -d ~/.claude/plugins/marketplaces/gskills/plugins/learning-agent && echo "FAIL: still exists" || echo "PASS: removed"
```

Expected: PASS: removed

- [ ] **Step 8: Final sync repo verification**

```bash
cd ~/learning/glouie-assistant && ls
cd ~/learning/glouie-assistant && wc -l knowledge.jsonl
cd ~/learning/glouie-assistant && git log --oneline -3
```

Expected: JSONL files present, 22 lines in knowledge.jsonl, migration commit visible
