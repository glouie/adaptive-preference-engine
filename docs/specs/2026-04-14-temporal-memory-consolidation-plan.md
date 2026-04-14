# APE Temporal Support, Memory Consolidation & Confidential Store — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend APE with temporal expiry, dual-database confidential store, memory consolidation, and session-end sync hooks.

**Architecture:** Dual SQLite databases (`ape.db` public, `ape-confidential.db` confidential) with independent sync to separate git repos. Memory intercept via PostToolUse hook queues to inbox; ingestion at session boundaries. Temporal expiry via `expires_at`/`expires_when_tag` columns checked at session-start and pruning.

**Tech Stack:** Python 3 (stdlib only), SQLite, Bash, Claude Code hooks (JSON config)

**Spec:** `docs/specs/2026-04-14-temporal-memory-consolidation-design.md` (rev 3.1)

---

## File Map

### Files Modified

| File | Responsibility |
|---|---|
| `src/adaptive_preference_engine/knowledge.py` | Add 3 temporal fields to KnowledgeEntry dataclass |
| `scripts/storage.py` | Schema migration v6 (temporal columns), `db_path` param on KnowledgeStorage, `ConfidentialStorageManager` class, `sync_meta` table |
| `scripts/sync.py` | Dual-database export, dual-repo push/pull, lockfile serialization, conflict resolution |
| `scripts/cli.py` | CLI flags (`--expires-at`, `--expires-when`, `--expires-when-tag`, `--confidential`), subcommands (`knowledge import-memory`, `knowledge migrate-confidential`), tag validation |
| `scripts/session-start-hook.sh` | Expiry check, inbox ingestion, memory generation, project hash discovery |
| `scripts/compaction.py` | Accept `storage` parameter instead of hardcoded `mgr.knowledge` |
| `scripts/config.py` | Add `confidential` and `memory` config sections |
| `hooks/hooks.json` | Add Stop hook, add PostToolUse memory intercept entry |

### Files Created

| File | Responsibility |
|---|---|
| `scripts/session-end-hook.sh` | SessionEnd: ingest inbox, export both DBs, generate memory, push both repos |
| `scripts/posttool-memory-intercept.py` | Copy memory writes to inbox (fast path, no DB) |
| `scripts/memory_generator.py` | Generate `.md` files from knowledge entries for Claude Code memory |

### Test Files

| File | What it covers |
|---|---|
| `tests/test_temporal_expiry.py` | expires_at archiving, expires_when_tag signal matching, tag validation |
| `tests/test_confidential_storage.py` | Dual-database CRUD, pattern classification, ConfidentialStorageManager |
| `tests/test_memory_consolidation.py` | Inbox ingestion, memory generation, dedup, import-memory |
| `tests/test_sync_dual.py` | Dual-repo push/pull, lockfile, split-brain detection, conflict resolution |
| `tests/test_perf_expiry.py` | Performance acceptance test (<200ms for 500 entries) |

---

## Task 1: KnowledgeEntry Temporal Fields

**Files:**
- Modify: `src/adaptive_preference_engine/knowledge.py:14-58`
- Test: `tests/test_knowledge_storage.py` (extend existing)

- [ ] **Step 1: Write failing test for temporal fields**

In `tests/test_knowledge_storage.py`, add after `test_storage_info_includes_knowledge`:

```python
def test_temporal_fields_default_none(self, mgr):
    entry = make_entry(id="know_temporal")
    mgr.knowledge.save_entry(entry)
    result = mgr.knowledge.get_entry("know_temporal")
    assert result.expires_at is None
    assert result.expires_when is None
    assert result.expires_when_tag is None

def test_save_and_retrieve_temporal_fields(self, mgr):
    entry = make_entry(
        id="know_temp_full",
        expires_at="2026-05-01",
        expires_when="10.5 GA ships",
        expires_when_tag="10.5-shipped",
    )
    mgr.knowledge.save_entry(entry)
    result = mgr.knowledge.get_entry("know_temp_full")
    assert result.expires_at == "2026-05-01"
    assert result.expires_when == "10.5 GA ships"
    assert result.expires_when_tag == "10.5-shipped"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_knowledge_storage.py::TestKnowledgeStorage::test_temporal_fields_default_none tests/test_knowledge_storage.py::TestKnowledgeStorage::test_save_and_retrieve_temporal_fields -v`

Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'expires_at'`

- [ ] **Step 3: Add temporal fields to KnowledgeEntry**

In `src/adaptive_preference_engine/knowledge.py`, add after line 33 (`ref_path`):

```python
    expires_at: Optional[str] = None
    expires_when: Optional[str] = None
    expires_when_tag: Optional[str] = None
```

Update `to_dict()` to include the new fields — add after `"ref_path": self.ref_path,`:

```python
            "expires_at": self.expires_at,
            "expires_when": self.expires_when,
            "expires_when_tag": self.expires_when_tag,
```

- [ ] **Step 4: Update KnowledgeStorage SQL to include temporal columns**

In `scripts/storage.py`, update `save_entry()` (line 551). The INSERT and ON CONFLICT columns must include the 3 new fields. In the INSERT column list, add after `ref_path`:

```python
                     expires_at, expires_when, expires_when_tag)
```

In VALUES, add after `:ref_path`:

```python
                     :expires_at, :expires_when, :expires_when_tag)
```

In ON CONFLICT SET, add after `ref_path = excluded.ref_path`:

```python
                    expires_at      = excluded.expires_at,
                    expires_when    = excluded.expires_when,
                    expires_when_tag = excluded.expires_when_tag
```

- [ ] **Step 5: Add schema migration v6 for temporal columns**

In `scripts/storage.py`, update `_CURRENT_VERSION = 5` to `_CURRENT_VERSION = 6` (line 677).

In `_apply_migrations()`, add after the `if current < 5:` block (after line 801):

```python
        if current < 6:
            # v6: temporal expiry columns on knowledge
            for col in ("expires_at TEXT", "expires_when TEXT", "expires_when_tag TEXT"):
                try:
                    self._conn.execute(f"ALTER TABLE knowledge ADD COLUMN {col}")
                    self._conn.commit()
                except sqlite3.OperationalError:
                    pass  # Column already exists (fresh DB)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (6, datetime.now().isoformat()),
                )
```

Also update the CREATE TABLE in the v3 migration (line 734) to include the new columns in the DDL for fresh databases. Add after `ref_path TEXT`:

```sql
                    expires_at      TEXT,
                    expires_when    TEXT,
                    expires_when_tag TEXT
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_knowledge_storage.py -v`

Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add src/adaptive_preference_engine/knowledge.py scripts/storage.py tests/test_knowledge_storage.py
git commit -m "feat(knowledge): add temporal expiry fields (expires_at, expires_when, expires_when_tag)"
```

---

## Task 2: Tag Validation

**Files:**
- Create: `scripts/tag_validation.py`
- Modify: `scripts/cli.py` (knowledge add)
- Test: `tests/test_temporal_expiry.py` (new file)

- [ ] **Step 1: Write failing tests for tag validation**

Create `tests/test_temporal_expiry.py`:

```python
"""Tests for temporal expiry and tag validation. Run: pytest tests/test_temporal_expiry.py -v"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.tag_validation import validate_tag, TAG_REGEX


class TestTagValidation:
    def test_valid_alphanumeric(self):
        assert validate_tag("release-10.5") is True

    def test_valid_simple(self):
        assert validate_tag("shipped") is True

    def test_valid_dotted(self):
        assert validate_tag("v10.5.3") is True

    def test_reject_underscore(self):
        assert validate_tag("foo_bar") is False

    def test_reject_percent(self):
        assert validate_tag("%prod%") is False

    def test_reject_space(self):
        assert validate_tag("foo bar") is False

    def test_reject_empty(self):
        assert validate_tag("") is False

    def test_reject_starts_with_hyphen(self):
        assert validate_tag("-invalid") is False

    def test_reject_starts_with_dot(self):
        assert validate_tag(".hidden") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_temporal_expiry.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.tag_validation'`

- [ ] **Step 3: Implement tag validation module**

Create `scripts/tag_validation.py`:

```python
"""Tag validation for APE knowledge entries and signal tags."""

import re

TAG_REGEX = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9.\-]*$')


def validate_tag(tag: str) -> bool:
    """Return True if tag matches the allowed pattern.

    Allowed: alphanumeric start, then alphanumeric plus '.' and '-'.
    Rejected: underscore and percent (SQLite LIKE wildcards), spaces, empty.
    """
    if not tag:
        return False
    return TAG_REGEX.match(tag) is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_temporal_expiry.py -v`

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add scripts/tag_validation.py tests/test_temporal_expiry.py
git commit -m "feat(knowledge): add tag validation (reject LIKE wildcards)"
```

---

## Task 3: Temporal Expiry — Archive Expired Entries

**Files:**
- Modify: `scripts/storage.py` (KnowledgeStorage)
- Test: `tests/test_temporal_expiry.py` (extend)

- [ ] **Step 1: Write failing test for archive_expired**

Append to `tests/test_temporal_expiry.py`:

```python
from scripts.storage import PreferenceStorageManager
from adaptive_preference_engine.knowledge import KnowledgeEntry
from scripts.models import generate_id


def make_entry(**kwargs) -> KnowledgeEntry:
    defaults = dict(
        id=generate_id("know"),
        partition="projects/test",
        category="convention",
        title="Test",
        tags=["test"],
        content="Content",
        confidence=1.0,
        token_estimate=25,
    )
    defaults.update(kwargs)
    return KnowledgeEntry(**defaults)


@pytest.fixture
def mgr(tmp_path):
    return PreferenceStorageManager(str(tmp_path))


class TestArchiveExpired:
    def test_archives_past_expires_at(self, mgr):
        mgr.knowledge.save_entry(make_entry(
            id="know_expired", expires_at="2020-01-01"
        ))
        mgr.knowledge.save_entry(make_entry(
            id="know_future", expires_at="2099-12-31"
        ))
        mgr.knowledge.save_entry(make_entry(id="know_no_expiry"))
        archived_count = mgr.knowledge.archive_expired()
        assert archived_count == 1
        assert mgr.knowledge.get_entry("know_expired").archived is True
        assert mgr.knowledge.get_entry("know_future").archived is False
        assert mgr.knowledge.get_entry("know_no_expiry").archived is False

    def test_skips_already_archived(self, mgr):
        mgr.knowledge.save_entry(make_entry(
            id="know_old", expires_at="2020-01-01", archived=True
        ))
        archived_count = mgr.knowledge.archive_expired()
        assert archived_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_temporal_expiry.py::TestArchiveExpired -v`

Expected: FAIL — `AttributeError: 'KnowledgeStorage' object has no attribute 'archive_expired'`

- [ ] **Step 3: Implement archive_expired on KnowledgeStorage**

In `scripts/storage.py`, add after `delete_entry()` (line 659):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_temporal_expiry.py -v`

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add scripts/storage.py tests/test_temporal_expiry.py
git commit -m "feat(knowledge): archive_expired method for temporal expiry"
```

---

## Task 4: Temporal Expiry — Signal Tag Matching for Pruning

**Files:**
- Modify: `scripts/storage.py` (KnowledgeStorage)
- Test: `tests/test_temporal_expiry.py` (extend)

- [ ] **Step 1: Write failing test for find_triggered_entries**

Append to `tests/test_temporal_expiry.py`:

```python
class TestSignalTagMatching:
    def test_finds_entry_with_matching_signal(self, mgr):
        entry = make_entry(
            id="know_triggered",
            expires_when_tag="10.5-shipped",
            created_at="2026-01-01T00:00:00",
        )
        mgr.knowledge.save_entry(entry)
        # Insert a signal with matching tag after the entry's created_at
        mgr.signals._conn.execute(
            """INSERT INTO signals (id, signal_type, task_context, context_tags,
               satisfaction, timestamp) VALUES (?, ?, ?, ?, ?, ?)""",
            ("sig_1", "feedback", "release", "deploy,10.5-shipped,ops", 0.9,
             "2026-04-01T00:00:00"),
        )
        mgr.signals._conn.commit()
        triggered = mgr.knowledge.find_triggered_entries(mgr.signals._conn)
        assert len(triggered) == 1
        assert triggered[0].id == "know_triggered"

    def test_ignores_signal_before_entry_created(self, mgr):
        entry = make_entry(
            id="know_not_triggered",
            expires_when_tag="10.5-shipped",
            created_at="2026-06-01T00:00:00",
        )
        mgr.knowledge.save_entry(entry)
        mgr.signals._conn.execute(
            """INSERT INTO signals (id, signal_type, task_context, context_tags,
               satisfaction, timestamp) VALUES (?, ?, ?, ?, ?, ?)""",
            ("sig_old", "feedback", "release", "deploy,10.5-shipped", 0.9,
             "2026-01-01T00:00:00"),
        )
        mgr.signals._conn.commit()
        triggered = mgr.knowledge.find_triggered_entries(mgr.signals._conn)
        assert len(triggered) == 0

    def test_no_partial_tag_match(self, mgr):
        entry = make_entry(
            id="know_partial",
            expires_when_tag="10.5",
            created_at="2026-01-01T00:00:00",
        )
        mgr.knowledge.save_entry(entry)
        mgr.signals._conn.execute(
            """INSERT INTO signals (id, signal_type, task_context, context_tags,
               satisfaction, timestamp) VALUES (?, ?, ?, ?, ?, ?)""",
            ("sig_2", "feedback", "release", "deploy,10.50-beta", 0.9,
             "2026-04-01T00:00:00"),
        )
        mgr.signals._conn.commit()
        triggered = mgr.knowledge.find_triggered_entries(mgr.signals._conn)
        assert len(triggered) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_temporal_expiry.py::TestSignalTagMatching -v`

Expected: FAIL — `AttributeError: 'KnowledgeStorage' object has no attribute 'find_triggered_entries'`

- [ ] **Step 3: Implement find_triggered_entries**

In `scripts/storage.py`, add after `archive_expired()`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_temporal_expiry.py -v`

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add scripts/storage.py tests/test_temporal_expiry.py
git commit -m "feat(knowledge): find_triggered_entries for signal-tag pruning"
```

---

## Task 5: CLI — Temporal Flags and Tag Validation

**Files:**
- Modify: `scripts/cli.py` (knowledge add argparse + handler)
- Test: `tests/test_temporal_expiry.py` (extend)

- [ ] **Step 1: Write failing test for CLI temporal flags**

Append to `tests/test_temporal_expiry.py`:

```python
import subprocess

class TestCLITemporalFlags:
    def test_knowledge_add_with_expires_at(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "scripts/cli.py", "knowledge", "add",
             "--title", "Freeze", "--content", "No merges",
             "--partition", "test", "--category", "context",
             "--expires-at", "2026-05-01"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
            env={**dict(__import__("os").environ),
                 "ADAPTIVE_CLI_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "expires_at" in result.stdout or "Saved" in result.stdout

    def test_knowledge_add_rejects_invalid_tag(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "scripts/cli.py", "knowledge", "add",
             "--title", "Bad Tag", "--content", "Test",
             "--partition", "test", "--category", "context",
             "--expires-when-tag", "foo_bar"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
            env={**dict(__import__("os").environ),
                 "ADAPTIVE_CLI_DIR": str(tmp_path)},
        )
        assert result.returncode != 0 or "invalid" in result.stderr.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_temporal_expiry.py::TestCLITemporalFlags -v`

Expected: FAIL

- [ ] **Step 3: Add argparse flags to cli.py**

In `scripts/cli.py`, find the `knowledge add` subparser (around line 1778-1786). Add after the existing arguments:

```python
    add_p.add_argument("--expires-at", help="ISO date for calendar-based expiry (YYYY-MM-DD)")
    add_p.add_argument("--expires-when", help="Human-readable expiry trigger description")
    add_p.add_argument("--expires-when-tag", help="Signal tag to watch for event-based expiry")
    add_p.add_argument("--confidential", action="store_true", help="Route to confidential store")
```

- [ ] **Step 4: Update cmd_knowledge_add handler**

In `scripts/cli.py`, find `cmd_knowledge_add` (around line 1183). Add tag validation before creating the entry:

```python
    # Validate expires_when_tag if provided
    if args.expires_when_tag:
        from scripts.tag_validation import validate_tag
        if not validate_tag(args.expires_when_tag):
            print(f"ERROR: Invalid tag '{args.expires_when_tag}'. "
                  "Tags must match [a-zA-Z0-9][a-zA-Z0-9.-]* "
                  "(no underscores or percent signs).", file=sys.stderr)
            return
```

In the KnowledgeEntry construction (around line 1186-1199), add the temporal fields:

```python
        expires_at=args.expires_at,
        expires_when=args.expires_when,
        expires_when_tag=args.expires_when_tag,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_temporal_expiry.py -v`

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add scripts/cli.py tests/test_temporal_expiry.py
git commit -m "feat(cli): add --expires-at, --expires-when, --expires-when-tag flags with tag validation"
```

---

## Task 6: Confidential Storage Manager

**Files:**
- Modify: `scripts/storage.py` (add ConfidentialStorageManager, sync_meta table)
- Modify: `scripts/config.py` (add confidential config section)
- Create: `tests/test_confidential_storage.py`

- [ ] **Step 1: Write failing test for ConfidentialStorageManager**

Create `tests/test_confidential_storage.py`:

```python
"""Tests for dual-database confidential storage. Run: pytest tests/test_confidential_storage.py -v"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.storage import PreferenceStorageManager, ConfidentialStorageManager
from adaptive_preference_engine.knowledge import KnowledgeEntry
from scripts.models import generate_id


def make_entry(**kwargs) -> KnowledgeEntry:
    defaults = dict(
        id=generate_id("know"),
        partition="projects/test",
        category="convention",
        title="Test",
        tags=["test"],
        content="Content",
        confidence=1.0,
        token_estimate=25,
    )
    defaults.update(kwargs)
    return KnowledgeEntry(**defaults)


@pytest.fixture
def public_mgr(tmp_path):
    return PreferenceStorageManager(str(tmp_path))


@pytest.fixture
def confidential_mgr(tmp_path):
    return ConfidentialStorageManager(str(tmp_path / "confidential"))


class TestConfidentialStorage:
    def test_independent_databases(self, public_mgr, confidential_mgr):
        public_mgr.knowledge.save_entry(make_entry(id="pub_1", title="Public"))
        confidential_mgr.knowledge.save_entry(make_entry(id="conf_1", title="Confidential"))
        assert len(public_mgr.knowledge.get_all_entries()) == 1
        assert len(confidential_mgr.knowledge.get_all_entries()) == 1
        assert public_mgr.knowledge.get_entry("conf_1") is None
        assert confidential_mgr.knowledge.get_entry("pub_1") is None

    def test_confidential_has_temporal_fields(self, confidential_mgr):
        entry = make_entry(id="conf_temp", expires_at="2026-12-31")
        confidential_mgr.knowledge.save_entry(entry)
        result = confidential_mgr.knowledge.get_entry("conf_temp")
        assert result.expires_at == "2026-12-31"

    def test_confidential_archive_expired(self, confidential_mgr):
        confidential_mgr.knowledge.save_entry(make_entry(
            id="conf_old", expires_at="2020-01-01"
        ))
        count = confidential_mgr.knowledge.archive_expired()
        assert count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_confidential_storage.py -v`

Expected: FAIL — `ImportError: cannot import name 'ConfidentialStorageManager'`

- [ ] **Step 3: Implement ConfidentialStorageManager**

In `scripts/storage.py`, add after the `PreferenceStorageManager` class (after the class ends):

```python
class ConfidentialStorageManager:
    """Lightweight storage manager for the confidential database.

    Only exposes a KnowledgeStorage — confidential DB has no preferences,
    associations, contexts, or signals (those live in the public DB).
    """

    _CURRENT_VERSION = 6

    def __init__(self, base_dir: Optional[str] = None) -> None:
        if base_dir is None:
            base_dir = os.path.expanduser("~/.adaptive-cli")
        self.base_dir = Path(base_dir)
        db_path = self.base_dir / "ape-confidential.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        _raw_conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _raw_conn.row_factory = sqlite3.Row
        self._conn = _LockedConnection(_raw_conn, self._lock)
        # Create knowledge table directly (no other tables needed)
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

    def close(self) -> None:
        if not self._closed:
            self._conn.close()
            self._closed = True

    def update_sync_meta(self, push_at: Optional[str] = None, pull_at: Optional[str] = None) -> None:
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

    def get_sync_meta(self) -> dict:
        row = self._conn.execute("SELECT * FROM sync_meta").fetchone()
        if row:
            return {"last_push_at": row["last_push_at"], "last_pull_at": row["last_pull_at"]}
        return {"last_push_at": None, "last_pull_at": None}
```

- [ ] **Step 4: Add sync_meta table to PreferenceStorageManager too**

In `scripts/storage.py`, in the v6 migration block (added in Task 1), also create `sync_meta`:

```python
            # sync_meta table for split-brain detection
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS sync_meta (
                    last_push_at TEXT,
                    last_pull_at TEXT
                );
            """)
```

Add the same `update_sync_meta` and `get_sync_meta` methods to `PreferenceStorageManager`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_confidential_storage.py -v`

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add scripts/storage.py tests/test_confidential_storage.py
git commit -m "feat(storage): add ConfidentialStorageManager with sync_meta table"
```

---

## Task 7: Confidential Pattern Classification

**Files:**
- Modify: `scripts/config.py` (add confidential config)
- Create: `scripts/confidential_classifier.py`
- Test: `tests/test_confidential_storage.py` (extend)

- [ ] **Step 1: Write failing test for pattern classification**

Append to `tests/test_confidential_storage.py`:

```python
from scripts.confidential_classifier import is_confidential


class TestPatternClassification:
    def test_matches_notes_vault(self):
        assert is_confidential("Path is ~/notes-vault/webex/meeting.md") is True

    def test_matches_users_path(self):
        assert is_confidential("Config at /Users/glouie/.config/foo") is True

    def test_matches_internal_url(self):
        assert is_confidential("Dashboard at cd.splunkdev.com/grafana") is True

    def test_matches_cisco_email(self):
        assert is_confidential("Contact glouie@cisco.com") is True

    def test_no_match_generic_content(self):
        assert is_confidential("Use pytest for testing Python code") is False

    def test_custom_patterns(self):
        assert is_confidential("secret-project", patterns=["secret-project"]) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_confidential_storage.py::TestPatternClassification -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement classifier**

Create `scripts/confidential_classifier.py`:

```python
"""Classify knowledge entries as confidential based on content pattern matching."""

from typing import List, Optional

DEFAULT_PATTERNS = [
    "~/notes-vault",
    "~/learning/",
    "/Users/",
    "cd.splunkdev.com",
    "@cisco.com",
]


def is_confidential(content: str, patterns: Optional[List[str]] = None) -> bool:
    """Return True if content matches any confidential pattern."""
    check_patterns = patterns if patterns is not None else DEFAULT_PATTERNS
    for pattern in check_patterns:
        if pattern in content:
            return True
    return False
```

- [ ] **Step 4: Add confidential config section to config.py**

In `scripts/config.py`, add to the `_DEFAULTS` dict in `APEConfig` (around line 67):

```python
    "confidential": {
        "db_path": "~/.adaptive-cli/ape-confidential.db",
        "repo_path": "~/gitlab/gskills",
        "store_dir": ".ape-confidential",
        "patterns": [
            "~/notes-vault",
            "~/learning/",
            "/Users/",
            "cd.splunkdev.com",
            "@cisco.com",
        ],
        "auto_classify": True,
    },
    "memory": {
        "inbox_path": "~/.adaptive-cli/memory-inbox",
        "intercept_writes": True,
    },
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_confidential_storage.py -v`

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add scripts/confidential_classifier.py scripts/config.py tests/test_confidential_storage.py
git commit -m "feat(confidential): pattern-based classification and config"
```

---

## Task 8: Dual-Database Sync — Export and Push

**Files:**
- Modify: `scripts/sync.py` (dual-repo push/pull, lockfile)
- Create: `tests/test_sync_dual.py`

- [ ] **Step 1: Write failing test for dual-repo export**

Create `tests/test_sync_dual.py`:

```python
"""Tests for dual-database sync. Run: pytest tests/test_sync_dual.py -v"""

import sys
import json
import fcntl
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.storage import PreferenceStorageManager, ConfidentialStorageManager
from scripts.sync import PreferenceSync, ConfidentialSync
from adaptive_preference_engine.knowledge import KnowledgeEntry
from scripts.models import generate_id


def make_entry(**kwargs) -> KnowledgeEntry:
    defaults = dict(
        id=generate_id("know"), partition="projects/test",
        category="convention", title="Test", tags=["test"],
        content="Content", confidence=1.0, token_estimate=25,
    )
    defaults.update(kwargs)
    return KnowledgeEntry(**defaults)


@pytest.fixture
def public_mgr(tmp_path):
    return PreferenceStorageManager(str(tmp_path / "public"))


@pytest.fixture
def confidential_mgr(tmp_path):
    return ConfidentialStorageManager(str(tmp_path / "confidential"))


class TestConfidentialSync:
    def test_export_confidential_knowledge(self, confidential_mgr, tmp_path):
        confidential_mgr.knowledge.save_entry(make_entry(
            id="conf_1", title="Secret Path", content="/Users/glouie/notes"
        ))
        dest = tmp_path / "conf_repo"
        dest.mkdir()
        counts = ConfidentialSync.export(confidential_mgr, dest)
        assert counts["knowledge"] == 1
        jsonl_path = dest / "knowledge.jsonl"
        assert jsonl_path.exists()
        with open(jsonl_path) as f:
            records = [json.loads(line) for line in f]
        assert len(records) == 1
        assert records[0]["title"] == "Secret Path"

    def test_import_confidential_knowledge(self, confidential_mgr, tmp_path):
        dest = tmp_path / "conf_repo"
        dest.mkdir()
        entry = make_entry(id="conf_imp", title="Imported")
        record = entry.to_dict()
        record["tags"] = json.dumps(record["tags"])
        with open(dest / "knowledge.jsonl", "w") as f:
            f.write(json.dumps(record) + "\n")
        counts = ConfidentialSync.import_from(confidential_mgr, dest)
        assert counts.get("knowledge", 0) >= 1
        result = confidential_mgr.knowledge.get_entry("conf_imp")
        assert result is not None
        assert result.title == "Imported"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_sync_dual.py -v`

Expected: FAIL — `ImportError: cannot import name 'ConfidentialSync'`

- [ ] **Step 3: Implement ConfidentialSync**

In `scripts/sync.py`, add after the `PreferenceSync` class:

```python
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
```

- [ ] **Step 4: Add repo lockfile helper**

In `scripts/sync.py`, add a lockfile helper near the top (after imports):

```python
import fcntl

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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_sync_dual.py -v`

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add scripts/sync.py tests/test_sync_dual.py
git commit -m "feat(sync): ConfidentialSync export/import and RepoLock"
```

---

## Task 9: Memory Generator

**Files:**
- Create: `scripts/memory_generator.py`
- Create: `tests/test_memory_consolidation.py`

- [ ] **Step 1: Write failing test for memory generation**

Create `tests/test_memory_consolidation.py`:

```python
"""Tests for memory consolidation. Run: pytest tests/test_memory_consolidation.py -v"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.storage import PreferenceStorageManager, ConfidentialStorageManager
from scripts.memory_generator import generate_memory_files, parse_memory_file
from adaptive_preference_engine.knowledge import KnowledgeEntry
from scripts.models import generate_id


def make_entry(**kwargs) -> KnowledgeEntry:
    defaults = dict(
        id=generate_id("know"), partition="projects/test",
        category="convention", title="Test", tags=["test"],
        content="Content", confidence=1.0, token_estimate=25,
    )
    defaults.update(kwargs)
    return KnowledgeEntry(**defaults)


@pytest.fixture
def public_mgr(tmp_path):
    return PreferenceStorageManager(str(tmp_path / "pub"))


@pytest.fixture
def confidential_mgr(tmp_path):
    return ConfidentialStorageManager(str(tmp_path / "conf"))


class TestMemoryGeneration:
    def test_generates_md_files(self, public_mgr, tmp_path):
        public_mgr.knowledge.save_entry(make_entry(
            id="know_1", title="Test Rule", content="Always test first",
            category="convention",
        ))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        count = generate_memory_files(public_mgr, None, memory_dir)
        assert count == 1
        files = list(memory_dir.glob("*.md"))
        # Filter out MEMORY.md
        non_index = [f for f in files if f.name != "MEMORY.md"]
        assert len(non_index) == 1

    def test_generates_memory_index(self, public_mgr, tmp_path):
        public_mgr.knowledge.save_entry(make_entry(
            id="know_1", title="Test Rule", content="Always test first",
        ))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        generate_memory_files(public_mgr, None, memory_dir)
        index = memory_dir / "MEMORY.md"
        assert index.exists()
        content = index.read_text()
        assert "Test Rule" in content

    def test_skips_archived_entries(self, public_mgr, tmp_path):
        public_mgr.knowledge.save_entry(make_entry(
            id="know_active", title="Active",
        ))
        public_mgr.knowledge.save_entry(make_entry(
            id="know_arch", title="Archived", archived=True,
        ))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        count = generate_memory_files(public_mgr, None, memory_dir)
        assert count == 1

    def test_includes_confidential_entries(self, public_mgr, confidential_mgr, tmp_path):
        public_mgr.knowledge.save_entry(make_entry(
            id="pub_1", title="Public Fact",
        ))
        confidential_mgr.knowledge.save_entry(make_entry(
            id="conf_1", title="Secret Path",
        ))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        count = generate_memory_files(public_mgr, confidential_mgr, memory_dir)
        assert count == 2

    def test_atomic_write(self, public_mgr, tmp_path):
        """No .tmp files should remain after generation."""
        public_mgr.knowledge.save_entry(make_entry(id="know_1", title="Test"))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        generate_memory_files(public_mgr, None, memory_dir)
        tmp_files = list(memory_dir.glob(".*.tmp"))
        assert len(tmp_files) == 0


class TestParseMemoryFile:
    def test_parses_frontmatter(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text(
            "---\nname: Test Rule\ndescription: A test\ntype: feedback\n---\n\nAlways test first.\n"
        )
        result = parse_memory_file(md)
        assert result["name"] == "Test Rule"
        assert result["type"] == "feedback"
        assert result["content"] == "Always test first."

    def test_maps_feedback_to_preference(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("---\nname: Pref\ndescription: d\ntype: feedback\n---\n\nContent\n")
        result = parse_memory_file(md)
        assert result["category"] == "preference"

    def test_maps_user_to_context(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("---\nname: User\ndescription: d\ntype: user\n---\n\nContent\n")
        result = parse_memory_file(md)
        assert result["category"] == "context"
        assert result["partition"] == "user"

    def test_maps_project_to_context(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("---\nname: Proj\ndescription: d\ntype: project\n---\n\nContent\n")
        result = parse_memory_file(md)
        assert result["category"] == "context"
        assert "projects/" in result["partition"]

    def test_maps_reference(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("---\nname: Ref\ndescription: d\ntype: reference\n---\n\nContent\n")
        result = parse_memory_file(md)
        assert result["category"] == "reference"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_memory_consolidation.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.memory_generator'`

- [ ] **Step 3: Implement memory_generator.py**

Create `scripts/memory_generator.py`:

```python
"""Generate Claude Code memory .md files from APE knowledge entries."""

import os
import re
import tempfile
from pathlib import Path
from typing import Optional, Dict, List

# Category -> memory type mapping
CATEGORY_TO_TYPE = {
    "preference": "feedback",
    "convention": "feedback",
    "pattern": "feedback",
    "decision": "project",
    "context": "project",
    "reference": "reference",
}

# Memory type -> APE category/partition mapping
TYPE_TO_CATEGORY = {
    "feedback": "preference",
    "user": "context",
    "project": "context",
    "reference": "reference",
}


def generate_memory_files(
    public_mgr,
    confidential_mgr,
    memory_dir: Path,
) -> int:
    """Generate .md files from knowledge entries into memory_dir.

    Returns count of files generated.
    """
    memory_dir = Path(memory_dir)
    memory_dir.mkdir(parents=True, exist_ok=True)

    entries = public_mgr.knowledge.get_all_entries(include_archived=False)
    if confidential_mgr:
        entries += confidential_mgr.knowledge.get_all_entries(include_archived=False)

    generated = 0
    index_lines = []

    for entry in entries:
        mem_type = CATEGORY_TO_TYPE.get(entry.category, "project")
        slug = re.sub(r'[^a-z0-9]+', '_', entry.title.lower()).strip('_')
        filename = f"{mem_type}_{slug}.md"

        content = (
            f"---\n"
            f"name: {entry.title}\n"
            f"description: {entry.content[:80]}\n"
            f"type: {mem_type}\n"
            f"---\n\n"
            f"{entry.content}\n"
        )

        # Atomic write: temp file + rename
        target = memory_dir / filename
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=f".{filename}.", suffix=".tmp", dir=str(memory_dir)
        )
        try:
            os.write(tmp_fd, content.encode("utf-8"))
            os.close(tmp_fd)
            os.rename(tmp_path, str(target))
        except Exception:
            os.close(tmp_fd) if not os.get_inheritable(tmp_fd) else None
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        index_lines.append(f"- [{entry.title}]({filename}) -- {entry.content[:60]}")
        generated += 1

    # Generate MEMORY.md index
    index_content = "# Memory Index\n\n" + "\n".join(index_lines) + "\n"
    index_target = memory_dir / "MEMORY.md"
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".MEMORY.md.", suffix=".tmp", dir=str(memory_dir)
    )
    try:
        os.write(tmp_fd, index_content.encode("utf-8"))
        os.close(tmp_fd)
        os.rename(tmp_path, str(index_target))
    except Exception:
        try:
            os.close(tmp_fd)
        except OSError:
            pass
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return generated


def parse_memory_file(file_path: Path) -> Dict:
    """Parse a Claude Code memory .md file into APE knowledge fields.

    Returns dict with: name, description, type, category, partition, content.
    """
    text = Path(file_path).read_text()

    # Split frontmatter and body
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter_text = parts[1].strip()
            body = parts[2].strip()
        else:
            frontmatter_text = ""
            body = text
    else:
        frontmatter_text = ""
        body = text

    # Parse YAML frontmatter (simple key: value)
    fm = {}
    for line in frontmatter_text.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip()

    mem_type = fm.get("type", "project")
    category = TYPE_TO_CATEGORY.get(mem_type, "context")

    # Determine partition from type
    if mem_type == "user":
        partition = "user"
    elif mem_type == "project":
        partition = "projects/unknown"
    else:
        partition = "general"

    return {
        "name": fm.get("name", Path(file_path).stem),
        "description": fm.get("description", ""),
        "type": mem_type,
        "category": category,
        "partition": partition,
        "content": body,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_memory_consolidation.py -v`

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add scripts/memory_generator.py tests/test_memory_consolidation.py
git commit -m "feat(memory): memory generator and parser for Claude Code .md files"
```

---

## Task 10: PostToolUse Memory Intercept Hook

**Files:**
- Create: `scripts/posttool-memory-intercept.py`
- Test: `tests/test_memory_consolidation.py` (extend)

- [ ] **Step 1: Write failing test for memory intercept**

Append to `tests/test_memory_consolidation.py`:

```python
import json
import subprocess


class TestMemoryIntercept:
    def test_copies_memory_file_to_inbox(self, tmp_path):
        # Set up dirs
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        memory_dir = tmp_path / ".claude" / "projects" / "abc123" / "memory"
        memory_dir.mkdir(parents=True)
        # Write a memory file
        mem_file = memory_dir / "feedback_test.md"
        mem_file.write_text("---\nname: Test\ntype: feedback\n---\n\nContent\n")
        # Simulate hook input
        hook_input = json.dumps({
            "tool": "Write",
            "tool_input": {"file_path": str(mem_file)},
        })
        result = subprocess.run(
            [sys.executable, "scripts/posttool-memory-intercept.py"],
            input=hook_input, capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
            env={**dict(__import__("os").environ),
                 "ADAPTIVE_CLI_INBOX": str(inbox)},
        )
        assert result.returncode == 0
        inbox_files = list(inbox.glob("*.md"))
        assert len(inbox_files) == 1
        assert "abc123" in inbox_files[0].name

    def test_skips_memory_index(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        hook_input = json.dumps({
            "tool": "Write",
            "tool_input": {"file_path": "/home/.claude/projects/abc/memory/MEMORY.md"},
        })
        result = subprocess.run(
            [sys.executable, "scripts/posttool-memory-intercept.py"],
            input=hook_input, capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
            env={**dict(__import__("os").environ),
                 "ADAPTIVE_CLI_INBOX": str(inbox)},
        )
        assert result.returncode == 0
        assert len(list(inbox.glob("*"))) == 0

    def test_skips_non_memory_path(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        hook_input = json.dumps({
            "tool": "Write",
            "tool_input": {"file_path": "/home/user/code/main.py"},
        })
        result = subprocess.run(
            [sys.executable, "scripts/posttool-memory-intercept.py"],
            input=hook_input, capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
            env={**dict(__import__("os").environ),
                 "ADAPTIVE_CLI_INBOX": str(inbox)},
        )
        assert result.returncode == 0
        assert len(list(inbox.glob("*"))) == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_memory_consolidation.py::TestMemoryIntercept -v`

Expected: FAIL

- [ ] **Step 3: Implement posttool-memory-intercept.py**

Create `scripts/posttool-memory-intercept.py`:

```python
#!/usr/bin/env python3
"""PostToolUse hook: copy memory writes to inbox for batched ingestion.

Reads hook JSON from stdin. If the tool wrote to a memory directory,
copies the file to ~/.adaptive-cli/memory-inbox/ with an atomic
temp-file + rename. Does NOT ingest into APE — that happens at
session boundaries.

Exit 0 always (non-blocking hook).
"""

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        return

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return

    # Only intercept memory directory writes
    if "/memory/" not in file_path:
        return

    # Skip MEMORY.md index
    if file_path.endswith("MEMORY.md"):
        return

    # Extract project hash from path: .../projects/<hash>/memory/<file>
    match = re.search(r'/projects/([^/]+)/memory/([^/]+)$', file_path)
    if not match:
        return

    project_hash = match.group(1)
    basename = match.group(2)
    unique_name = f"{project_hash}_{basename}"

    # Determine inbox path
    inbox_dir = os.environ.get(
        "ADAPTIVE_CLI_INBOX",
        os.path.expanduser("~/.adaptive-cli/memory-inbox"),
    )
    inbox = Path(inbox_dir)
    inbox.mkdir(parents=True, exist_ok=True)

    source = Path(file_path)
    if not source.exists():
        return

    # Atomic copy: temp file + rename
    target = inbox / unique_name
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=f".{unique_name}.", suffix=".tmp", dir=str(inbox)
    )
    try:
        with os.fdopen(tmp_fd, 'wb') as f:
            f.write(source.read_bytes())
        os.rename(tmp_path, str(target))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


if __name__ == "__main__":
    main()
```

Make it executable:

```bash
chmod +x scripts/posttool-memory-intercept.py
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_memory_consolidation.py -v`

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add scripts/posttool-memory-intercept.py tests/test_memory_consolidation.py
git commit -m "feat(memory): PostToolUse hook for memory intercept to inbox"
```

---

## Task 11: Inbox Ingestion Logic

**Files:**
- Create: `scripts/inbox_ingester.py`
- Test: `tests/test_memory_consolidation.py` (extend)

- [ ] **Step 1: Write failing test for inbox ingestion**

Append to `tests/test_memory_consolidation.py`:

```python
import hashlib
from scripts.inbox_ingester import ingest_inbox


class TestInboxIngestion:
    def test_ingests_feedback_to_public(self, public_mgr, confidential_mgr, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        md = inbox / "abc123_feedback_test.md"
        md.write_text("---\nname: Test Rule\ndescription: d\ntype: feedback\n---\n\nAlways test.\n")
        ingested = ingest_inbox(inbox, public_mgr, confidential_mgr)
        assert ingested == 1
        entries = public_mgr.knowledge.get_all_entries()
        assert len(entries) == 1
        assert entries[0].title == "Test Rule"
        assert entries[0].category == "preference"
        # Inbox file should be deleted after ingestion
        assert not md.exists()

    def test_routes_confidential_content(self, public_mgr, confidential_mgr, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        md = inbox / "abc123_user_paths.md"
        md.write_text("---\nname: Paths\ndescription: d\ntype: user\n---\n\n/Users/glouie/notes\n")
        ingested = ingest_inbox(inbox, public_mgr, confidential_mgr)
        assert ingested == 1
        # Should be in confidential due to /Users/ pattern
        assert len(confidential_mgr.knowledge.get_all_entries()) == 1
        assert len(public_mgr.knowledge.get_all_entries()) == 0

    def test_dedup_skips_existing(self, public_mgr, confidential_mgr, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        # First ingest
        md = inbox / "abc123_test.md"
        md.write_text("---\nname: Dup\ndescription: d\ntype: feedback\n---\n\nContent\n")
        ingest_inbox(inbox, public_mgr, confidential_mgr)
        # Second ingest of same content
        md.write_text("---\nname: Dup\ndescription: d\ntype: feedback\n---\n\nContent\n")
        ingested = ingest_inbox(inbox, public_mgr, confidential_mgr)
        assert ingested == 0  # Skipped as duplicate

    def test_skips_tmp_files(self, public_mgr, confidential_mgr, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        (inbox / ".partial.tmp").write_text("incomplete")
        ingested = ingest_inbox(inbox, public_mgr, confidential_mgr)
        assert ingested == 0

    def test_empty_inbox(self, public_mgr, confidential_mgr, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        ingested = ingest_inbox(inbox, public_mgr, confidential_mgr)
        assert ingested == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_memory_consolidation.py::TestInboxIngestion -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.inbox_ingester'`

- [ ] **Step 3: Implement inbox_ingester.py**

Create `scripts/inbox_ingester.py`:

```python
"""Ingest memory inbox files into APE knowledge databases."""

import hashlib
from pathlib import Path
from typing import Optional

from scripts.memory_generator import parse_memory_file
from scripts.confidential_classifier import is_confidential
from scripts.models import generate_id
from adaptive_preference_engine.knowledge import KnowledgeEntry


def _content_hash(title: str, content: str, category: str, partition: str) -> str:
    """SHA-256 hash of title+content+category+partition for dedup."""
    data = f"{title}\n{content}\n{category}\n{partition}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _entry_exists(public_mgr, confidential_mgr, content_hash: str) -> bool:
    """Check if an entry with this content hash exists in either DB."""
    for mgr in (public_mgr, confidential_mgr):
        if mgr is None:
            continue
        for entry in mgr.knowledge.get_all_entries(include_archived=True):
            h = _content_hash(entry.title, entry.content, entry.category, entry.partition)
            if h == content_hash:
                return True
    return False


def ingest_inbox(
    inbox_dir: Path,
    public_mgr,
    confidential_mgr,
) -> int:
    """Ingest all .md files from inbox into appropriate database.

    Returns count of entries ingested (skips duplicates and tmp files).
    """
    inbox = Path(inbox_dir)
    if not inbox.exists():
        return 0

    ingested = 0
    for md_file in sorted(inbox.glob("*.md")):
        # Skip tmp/hidden files
        if md_file.name.startswith("."):
            continue

        parsed = parse_memory_file(md_file)
        title = parsed["name"]
        content = parsed["content"]
        category = parsed["category"]
        partition = parsed["partition"]

        # Dedup check
        ch = _content_hash(title, content, category, partition)
        if _entry_exists(public_mgr, confidential_mgr, ch):
            md_file.unlink()
            continue

        # Route to correct DB
        if confidential_mgr and is_confidential(content):
            target_mgr = confidential_mgr
        else:
            target_mgr = public_mgr

        entry = KnowledgeEntry(
            id=generate_id("know"),
            partition=partition,
            category=category,
            title=title,
            tags=[],
            content=content,
            token_estimate=len(content.split()),
        )
        target_mgr.knowledge.save_entry(entry)
        md_file.unlink()
        ingested += 1

    return ingested
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_memory_consolidation.py -v`

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add scripts/inbox_ingester.py tests/test_memory_consolidation.py
git commit -m "feat(memory): inbox ingester with dedup and confidential routing"
```

---

## Task 12: Session Hooks (Start + End)

**Files:**
- Modify: `scripts/session-start-hook.sh`
- Create: `scripts/session-end-hook.sh`
- Modify: `hooks/hooks.json`

- [ ] **Step 1: Update session-start-hook.sh**

In `scripts/session-start-hook.sh`, add after the initialization check block (after line 39), before preference loading:

```bash
# --- Temporal expiry: archive expired entries in both DBs ---
python3 "$PLUGIN_ROOT/scripts/cli.py" knowledge expire --quiet 2>/dev/null || true

# --- Inbox: ingest any pending memory files from crashed sessions ---
python3 "$PLUGIN_ROOT/scripts/cli.py" knowledge ingest-inbox --quiet 2>/dev/null || true

# --- Memory generation: generate .md files for Claude Code ---
# Discover project memory directory
CLAUDE_PROJECT_MEMORY_DIR=""
for dir in "$HOME/.claude/projects"/*/memory; do
    if [ -d "$dir" ]; then
        # Check if this project dir corresponds to $PWD
        project_dir="$(dirname "$dir")"
        # Claude Code uses the working directory path to derive the hash
        if [ -f "$project_dir/.project_path" ]; then
            stored_path="$(cat "$project_dir/.project_path" 2>/dev/null)"
            if [ "$stored_path" = "$PWD" ]; then
                CLAUDE_PROJECT_MEMORY_DIR="$dir"
                break
            fi
        fi
    fi
done
export CLAUDE_PROJECT_MEMORY_DIR

if [ -n "$CLAUDE_PROJECT_MEMORY_DIR" ]; then
    python3 "$PLUGIN_ROOT/scripts/cli.py" knowledge generate-memory \
        --memory-dir "$CLAUDE_PROJECT_MEMORY_DIR" --quiet 2>/dev/null || true
fi
```

- [ ] **Step 2: Create session-end-hook.sh**

Create `scripts/session-end-hook.sh`:

```bash
#!/usr/bin/env bash
# Session-end hook: ingest inbox, export, generate memory, push both repos.
# Runs on Claude Code Stop event. Non-blocking — errors are logged, not fatal.
set -uo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
CLI="$PLUGIN_ROOT/scripts/cli.py"

# 1. Ingest pending inbox files
python3 "$CLI" knowledge ingest-inbox --quiet 2>/dev/null || true

# 2. Generate memory .md files
if [ -n "${CLAUDE_PROJECT_MEMORY_DIR:-}" ]; then
    python3 "$CLI" knowledge generate-memory \
        --memory-dir "$CLAUDE_PROJECT_MEMORY_DIR" --quiet 2>/dev/null || true
fi

# 3. Sync push (handles both public and confidential repos)
python3 "$CLI" sync push --quiet 2>/dev/null || true

# 4. Clear inbox
rm -f "$HOME/.adaptive-cli/memory-inbox/"*.md 2>/dev/null || true
```

Make executable:

```bash
chmod +x scripts/session-end-hook.sh
```

- [ ] **Step 3: Update hooks.json**

Read and modify `hooks/hooks.json` to add the Stop hook and memory intercept PostToolUse entry. The final structure should be:

```json
{
  "description": "APE hooks: session lifecycle, signal detection, memory intercept",
  "hooks": {
    "SessionStart": [
      {
        "type": "command",
        "command": "$CLAUDE_PLUGIN_ROOT/scripts/session-start-hook.sh"
      },
      {
        "type": "prompt",
        "content": "The adaptive preference engine is active. ..."
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PLUGIN_ROOT/scripts/posttool-signal-detector.py"
          }
        ]
      },
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PLUGIN_ROOT/scripts/posttool-memory-intercept.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PLUGIN_ROOT/scripts/session-end-hook.sh"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 4: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add scripts/session-start-hook.sh scripts/session-end-hook.sh hooks/hooks.json
git commit -m "feat(hooks): session-end hook, memory intercept, expiry on start"
```

---

## Task 13: CLI Subcommands (expire, ingest-inbox, generate-memory, import-memory, migrate-confidential)

**Files:**
- Modify: `scripts/cli.py`

- [ ] **Step 1: Add `knowledge expire` subcommand**

In `scripts/cli.py`, in the knowledge subparser section (around line 1806), add:

```python
    expire_p = knowledge_sub.add_parser("expire", help="Archive expired entries")
    expire_p.add_argument("--quiet", action="store_true")
```

Add handler function:

```python
def cmd_knowledge_expire(args, mgr):
    count = mgr.knowledge.archive_expired()
    # Also check confidential DB
    conf_count = 0
    try:
        from scripts.storage import ConfidentialStorageManager
        conf_mgr = ConfidentialStorageManager()
        conf_count = conf_mgr.knowledge.archive_expired()
        conf_mgr.close()
    except Exception:
        pass
    if not getattr(args, "quiet", False):
        total = count + conf_count
        if total > 0:
            print(f"Archived {total} expired entries ({count} public, {conf_count} confidential)")
        else:
            print("No expired entries found")
```

- [ ] **Step 2: Add `knowledge ingest-inbox` subcommand**

```python
    ingest_p = knowledge_sub.add_parser("ingest-inbox", help="Ingest pending memory inbox files")
    ingest_p.add_argument("--quiet", action="store_true")
```

Handler:

```python
def cmd_knowledge_ingest_inbox(args, mgr):
    from scripts.inbox_ingester import ingest_inbox
    from scripts.storage import ConfidentialStorageManager
    inbox = Path(os.path.expanduser("~/.adaptive-cli/memory-inbox"))
    try:
        conf_mgr = ConfidentialStorageManager()
    except Exception:
        conf_mgr = None
    count = ingest_inbox(inbox, mgr, conf_mgr)
    if conf_mgr:
        conf_mgr.close()
    if not getattr(args, "quiet", False) and count > 0:
        print(f"Ingested {count} entries from inbox")
```

- [ ] **Step 3: Add `knowledge generate-memory` subcommand**

```python
    genmem_p = knowledge_sub.add_parser("generate-memory", help="Generate memory .md files")
    genmem_p.add_argument("--memory-dir", required=True, help="Target memory directory")
    genmem_p.add_argument("--quiet", action="store_true")
```

Handler:

```python
def cmd_knowledge_generate_memory(args, mgr):
    from scripts.memory_generator import generate_memory_files
    from scripts.storage import ConfidentialStorageManager
    try:
        conf_mgr = ConfidentialStorageManager()
    except Exception:
        conf_mgr = None
    memory_dir = Path(args.memory_dir)
    count = generate_memory_files(mgr, conf_mgr, memory_dir)
    if conf_mgr:
        conf_mgr.close()
    if not getattr(args, "quiet", False):
        print(f"Generated {count} memory files in {memory_dir}")
```

- [ ] **Step 4: Add `knowledge import-memory` subcommand**

```python
    import_p = knowledge_sub.add_parser("import-memory", help="Import existing Claude Code memory")
    import_p.add_argument("--scan", action="store_true", help="Scan all project memory dirs")
    import_p.add_argument("--quiet", action="store_true")
```

Handler:

```python
def cmd_knowledge_import_memory(args, mgr):
    import hashlib
    from scripts.memory_generator import parse_memory_file
    from scripts.confidential_classifier import is_confidential
    from scripts.storage import ConfidentialStorageManager
    from scripts.models import generate_id

    try:
        conf_mgr = ConfidentialStorageManager()
    except Exception:
        conf_mgr = None

    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.exists():
        print("No Claude Code projects found")
        return

    imported = 0
    skipped = 0
    for memory_dir in claude_projects.glob("*/memory"):
        for md_file in memory_dir.glob("*.md"):
            if md_file.name == "MEMORY.md":
                continue
            parsed = parse_memory_file(md_file)
            title = parsed["name"]
            content = parsed["content"]
            category = parsed["category"]
            partition = parsed["partition"]

            # Dedup
            data = f"{title}\n{content}\n{category}\n{partition}"
            ch = hashlib.sha256(data.encode()).hexdigest()
            exists = False
            for m in (mgr, conf_mgr):
                if m is None:
                    continue
                store = m.knowledge if hasattr(m, 'knowledge') else m
                for e in store.get_all_entries(include_archived=True):
                    h = hashlib.sha256(
                        f"{e.title}\n{e.content}\n{e.category}\n{e.partition}".encode()
                    ).hexdigest()
                    if h == ch:
                        exists = True
                        break
                if exists:
                    break

            if exists:
                skipped += 1
                continue

            target = conf_mgr if (conf_mgr and is_confidential(content)) else mgr
            entry = KnowledgeEntry(
                id=generate_id("know"),
                partition=partition,
                category=category,
                title=title,
                tags=[],
                content=content,
                token_estimate=len(content.split()),
            )
            target.knowledge.save_entry(entry)
            imported += 1

    if conf_mgr:
        conf_mgr.close()
    if not getattr(args, "quiet", False):
        print(f"Imported {imported} entries ({skipped} duplicates skipped)")
```

- [ ] **Step 5: Add `knowledge migrate-confidential` subcommand**

```python
    migrate_p = knowledge_sub.add_parser("migrate-confidential",
        help="Migrate confidential YAML store to SQLite")
```

Handler:

```python
def cmd_knowledge_migrate_confidential(args, mgr):
    import yaml
    from scripts.storage import ConfidentialStorageManager
    from scripts.models import generate_id

    conf_mgr = ConfidentialStorageManager()
    yaml_path = Path(os.path.expanduser("~/gitlab/gskills/.ape-confidential/knowledge.yaml"))

    if not yaml_path.exists():
        print("No confidential YAML store found — nothing to migrate")
        conf_mgr.close()
        return

    with open(yaml_path) as f:
        data = yaml.safe_load(f) or []

    migrated = 0
    for item in data:
        entry = KnowledgeEntry(
            id=item.get("id", generate_id("know")),
            partition=item.get("partition", "confidential"),
            category=item.get("category", "context"),
            title=item.get("title", "Untitled"),
            tags=item.get("tags", []),
            content=item.get("content", ""),
            token_estimate=len(item.get("content", "").split()),
        )
        conf_mgr.knowledge.save_entry(entry)
        migrated += 1

    conf_mgr.close()
    print(f"Migrated {migrated} entries from YAML to ape-confidential.db")
```

- [ ] **Step 6: Wire subcommands to handlers in the dispatch block**

Find the `args.command` dispatch section in `cli.py` and add entries for each new subcommand, matching the pattern of existing commands.

- [ ] **Step 7: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add scripts/cli.py
git commit -m "feat(cli): add expire, ingest-inbox, generate-memory, import-memory, migrate-confidential subcommands"
```

---

## Task 14: Performance Acceptance Test

**Files:**
- Create: `tests/test_perf_expiry.py`

- [ ] **Step 1: Write performance test**

Create `tests/test_perf_expiry.py`:

```python
"""Performance acceptance test for temporal expiry. Run: pytest tests/test_perf_expiry.py -v"""

import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.storage import PreferenceStorageManager, ConfidentialStorageManager
from adaptive_preference_engine.knowledge import KnowledgeEntry
from scripts.models import generate_id


def make_entry(**kwargs) -> KnowledgeEntry:
    defaults = dict(
        id=generate_id("know"), partition="projects/test",
        category="convention", title="Test", tags=["test"],
        content="Content " * 20, confidence=1.0, token_estimate=40,
    )
    defaults.update(kwargs)
    return KnowledgeEntry(**defaults)


class TestExpiryPerformance:
    def test_archive_expired_under_200ms(self, tmp_path):
        """Spec requirement: <200ms for 500 entries per DB, 100 with expires_at."""
        pub_mgr = PreferenceStorageManager(str(tmp_path / "pub"))
        conf_mgr = ConfidentialStorageManager(str(tmp_path / "conf"))

        # Seed public DB: 500 entries, 100 with expires_at (50 past, 50 future)
        for i in range(400):
            pub_mgr.knowledge.save_entry(make_entry(
                id=f"pub_{i}", title=f"Entry {i}",
            ))
        for i in range(50):
            pub_mgr.knowledge.save_entry(make_entry(
                id=f"pub_exp_past_{i}", title=f"Expired {i}",
                expires_at="2020-01-01",
            ))
        for i in range(50):
            pub_mgr.knowledge.save_entry(make_entry(
                id=f"pub_exp_future_{i}", title=f"Future {i}",
                expires_at="2099-12-31",
            ))

        # Seed confidential DB: same distribution
        for i in range(400):
            conf_mgr.knowledge.save_entry(make_entry(
                id=f"conf_{i}", title=f"Conf {i}",
            ))
        for i in range(50):
            conf_mgr.knowledge.save_entry(make_entry(
                id=f"conf_exp_past_{i}", title=f"Conf Expired {i}",
                expires_at="2020-01-01",
            ))
        for i in range(50):
            conf_mgr.knowledge.save_entry(make_entry(
                id=f"conf_exp_future_{i}", title=f"Conf Future {i}",
                expires_at="2099-12-31",
            ))

        # Measure archive pass on both DBs
        start = time.monotonic()
        pub_count = pub_mgr.knowledge.archive_expired()
        conf_count = conf_mgr.knowledge.archive_expired()
        elapsed_ms = (time.monotonic() - start) * 1000

        assert pub_count == 50
        assert conf_count == 50
        assert elapsed_ms < 200, f"Expiry check took {elapsed_ms:.1f}ms (budget: 200ms)"

        pub_mgr.close()
        conf_mgr.close()
```

- [ ] **Step 2: Run performance test**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_perf_expiry.py -v`

Expected: PASS with timing well under 200ms (SQLite UPDATE with WHERE clause is fast)

- [ ] **Step 3: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add tests/test_perf_expiry.py
git commit -m "test: performance acceptance test for temporal expiry (<200ms)"
```

---

## Task 15: Update Compaction for Dual-Database

**Files:**
- Modify: `scripts/compaction.py`

- [ ] **Step 1: Update CompactionEngine to accept storage parameter**

In `scripts/compaction.py`, modify the constructor (around line 46) to accept an optional `knowledge_storage` parameter:

```python
def __init__(self, mgr=None, knowledge_storage=None):
```

If `knowledge_storage` is provided, use it instead of `mgr.knowledge`. Update all internal references from `self.mgr.knowledge` to `self.knowledge`:

```python
    if knowledge_storage:
        self.knowledge = knowledge_storage
    else:
        self.knowledge = self.mgr.knowledge
```

- [ ] **Step 2: Update compaction callers to pass storage for confidential**

In `scripts/cli.py`, where compaction is triggered (around line 1203), check if the entry was confidential and pass the appropriate storage:

```python
    # After save, trigger compaction check
    if args.confidential:
        from scripts.storage import ConfidentialStorageManager
        conf_mgr = ConfidentialStorageManager()
        engine = CompactionEngine(knowledge_storage=conf_mgr.knowledge)
    else:
        engine = CompactionEngine(mgr=mgr)
    engine.check_and_compact()
```

- [ ] **Step 3: Run existing compaction tests to verify no regression**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_compaction.py -v`

Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add scripts/compaction.py scripts/cli.py
git commit -m "refactor(compaction): accept storage parameter for dual-database support"
```

---

## Task 16: Integration Test — Full Session Lifecycle

**Files:**
- Create: `tests/test_integration_lifecycle.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_integration_lifecycle.py`:

```python
"""Integration test: full session lifecycle. Run: pytest tests/test_integration_lifecycle.py -v"""

import sys
import json
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.storage import PreferenceStorageManager, ConfidentialStorageManager
from scripts.memory_generator import generate_memory_files
from scripts.inbox_ingester import ingest_inbox
from adaptive_preference_engine.knowledge import KnowledgeEntry
from scripts.models import generate_id


def make_entry(**kwargs) -> KnowledgeEntry:
    defaults = dict(
        id=generate_id("know"), partition="projects/test",
        category="convention", title="Test", tags=["test"],
        content="Content", confidence=1.0, token_estimate=25,
    )
    defaults.update(kwargs)
    return KnowledgeEntry(**defaults)


class TestSessionLifecycle:
    def test_full_lifecycle(self, tmp_path):
        """Simulate: session-start -> agent writes memory -> session-end."""
        pub_mgr = PreferenceStorageManager(str(tmp_path / "pub"))
        conf_mgr = ConfidentialStorageManager(str(tmp_path / "conf"))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        inbox = tmp_path / "inbox"
        inbox.mkdir()

        # Pre-existing knowledge
        pub_mgr.knowledge.save_entry(make_entry(
            id="existing_1", title="Existing Rule", content="Use pytest",
        ))
        pub_mgr.knowledge.save_entry(make_entry(
            id="expired_1", title="Old Freeze", expires_at="2020-01-01",
        ))

        # --- SESSION START ---
        # 1. Archive expired
        archived = pub_mgr.knowledge.archive_expired()
        assert archived == 1

        # 2. Ingest stale inbox (empty for this test)
        ingest_inbox(inbox, pub_mgr, conf_mgr)

        # 3. Generate memory
        count = generate_memory_files(pub_mgr, conf_mgr, memory_dir)
        assert count == 1  # Only non-archived
        assert (memory_dir / "MEMORY.md").exists()

        # --- DURING SESSION ---
        # Agent writes a memory file, hook copies to inbox
        agent_memory = memory_dir / "feedback_new.md"
        agent_memory.write_text(
            "---\nname: New Pref\ndescription: d\ntype: feedback\n---\n\nPrefer tables.\n"
        )
        # Simulate hook: copy to inbox
        import shutil
        shutil.copy2(str(agent_memory), str(inbox / "abc123_feedback_new.md"))

        # --- SESSION END ---
        # 1. Ingest inbox
        ingested = ingest_inbox(inbox, pub_mgr, conf_mgr)
        assert ingested == 1

        # 2. Regenerate memory
        count = generate_memory_files(pub_mgr, conf_mgr, memory_dir)
        assert count == 2  # existing + new

        # 3. Verify state
        all_entries = pub_mgr.knowledge.get_all_entries()
        assert len(all_entries) == 2
        titles = {e.title for e in all_entries}
        assert "Existing Rule" in titles
        assert "New Pref" in titles

        pub_mgr.close()
        conf_mgr.close()
```

- [ ] **Step 2: Run integration test**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_integration_lifecycle.py -v`

Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
git add tests/test_integration_lifecycle.py
git commit -m "test: integration test for full session lifecycle"
```

---

## Task 17: Run Full Test Suite and Final Commit

- [ ] **Step 1: Run all tests**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/ -v --tb=short`

Expected: ALL PASS (existing + new tests)

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `cd ~/.claude/plugins/marketplaces/adaptive-preference-engine && python -m pytest tests/test_knowledge_storage.py tests/test_compaction.py tests/test_sync.py -v`

Expected: ALL PASS

- [ ] **Step 3: Final commit with version bump**

Update `plugin.json` version:

```bash
cd ~/.claude/plugins/marketplaces/adaptive-preference-engine
# Bump version in .claude-plugin/plugin.json
git add -A
git commit -m "feat(ape): temporal expiry, dual-database confidential store, memory consolidation v0.6.0"
```
