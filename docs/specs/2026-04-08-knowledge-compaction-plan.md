# Knowledge Compaction & Index-Reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically compact knowledge entries when token budget is exceeded, storing full content as ref files in the sync repo while keeping lightweight summaries in the DB. Inject relevant knowledge into agent sessions on demand.

**Architecture:** New `ref_path` column on knowledge table enables index-reference pattern. A `CompactionEngine` checks budgets after every `knowledge add` / `sync pull`, compacts the largest partitions first, writes ref files to the sync repo, and auto-commits. `PreferenceLoader.load_for_agent` is extended to match and inject knowledge based on context tags.

**Tech Stack:** Python 3.12, SQLite, git (subprocess), pytest

**Spec:** `docs/specs/2026-04-08-knowledge-compaction-design.md`

**Test runner:** `cd /Users/glouie/github/adaptive-preference-engine && pytest tests/<file> -v`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/adaptive_preference_engine/knowledge.py` | Modify | Add `ref_path` field to KnowledgeEntry |
| `scripts/storage.py` | Modify | Schema migration v5, update SQL for `ref_path` |
| `scripts/config.py` | Modify | Add `partition` and `context_injection` budget defaults |
| `scripts/compaction.py` | Create | CompactionEngine: budget check, partition selection, ref file writing, git commit |
| `scripts/cli.py` | Modify | Wire compaction into `knowledge add`, update `show/list/search/stats` |
| `scripts/sync.py` | Modify | Export/import `ref_path`, trigger compaction after import |
| `src/adaptive_preference_engine/services/loading.py` | Modify | Knowledge context injection in `load_for_agent` |
| `scripts/agent_hook.py` | Modify | Pass knowledge through to agent context |
| `tests/test_compaction.py` | Create | CompactionEngine tests |
| `tests/test_knowledge_model.py` | Modify | Test `ref_path` field |
| `tests/test_knowledge_storage.py` | Modify | Test `ref_path` persistence |
| `tests/test_knowledge_injection.py` | Create | Knowledge context injection tests |

---

### Task 1: Schema — Add `ref_path` to KnowledgeEntry and DB

**Files:**
- Modify: `src/adaptive_preference_engine/knowledge.py:14-56`
- Modify: `scripts/storage.py:105-121` (base schema), `scripts/storage.py:547-665` (KnowledgeStorage), `scripts/storage.py:675-785` (migrations)
- Modify: `tests/test_knowledge_model.py`
- Modify: `tests/test_knowledge_storage.py`

- [ ] **Step 1: Add `ref_path` field to KnowledgeEntry dataclass**

In `src/adaptive_preference_engine/knowledge.py`, add after `archived: bool = False` (line 32):

```python
    ref_path: Optional[str] = None
```

Add `Optional` to the typing import on line 4. Add `ref_path` to `to_dict()` and ensure `from_dict` handles it via the existing `_filter_fields` mechanism.

- [ ] **Step 2: Write failing test for ref_path round-trip**

In `tests/test_knowledge_model.py`, add:

```python
    def test_ref_path_default_none(self):
        entry = KnowledgeEntry(id="x", partition="p", category="c", title="t",
                               tags=["a"], content="c")
        assert entry.ref_path is None
        d = entry.to_dict()
        assert d["ref_path"] is None
        restored = KnowledgeEntry.from_dict(d)
        assert restored.ref_path is None

    def test_ref_path_set(self):
        entry = KnowledgeEntry(id="x", partition="p", category="c", title="t",
                               tags=["a"], content="summary", ref_path="partitions/p/consolidated.md")
        assert entry.ref_path == "partitions/p/consolidated.md"
        d = entry.to_dict()
        restored = KnowledgeEntry.from_dict(d)
        assert restored.ref_path == "partitions/p/consolidated.md"
```

Run: `pytest tests/test_knowledge_model.py -v`
Expected: FAIL (ref_path not in dataclass yet if step 1 not done, or PASS if done together)

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/test_knowledge_model.py -v`
Expected: All pass

- [ ] **Step 4: Add `ref_path` column to base schema in storage.py**

In `scripts/storage.py`, the `_SCHEMA` string (line 105-121), add after the `archived` line:

```sql
    ref_path        TEXT
```

- [ ] **Step 5: Add migration v5 for existing DBs**

In `scripts/storage.py`, in `_apply_migrations()`, after the `current < 4` block (ends ~line 785), add:

```python
        if current < 5:
            # v5: ref_path column for knowledge compaction
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
```

Update `_CURRENT_VERSION = 5` (line 675).

- [ ] **Step 6: Update KnowledgeStorage SQL to include ref_path**

In `scripts/storage.py`, update `save_entry()` INSERT/UPDATE to include `ref_path` in both column lists and values. Update `_row_to_entry()` — no special handling needed since `ref_path` is already a TEXT that maps to `Optional[str]`.

- [ ] **Step 7: Write storage test for ref_path persistence**

In `tests/test_knowledge_storage.py`, update the `make_entry` helper to accept `ref_path`:

```python
def make_entry(**kwargs) -> KnowledgeEntry:
    defaults = dict(
        id=generate_id("know"),
        partition="projects/test",
        category="convention",
        title="Test Knowledge",
        tags=["test"],
        content="Some test content here.",
        confidence=1.0,
        token_estimate=25,
        ref_path=None,  # ADD THIS
    )
    defaults.update(kwargs)
    return KnowledgeEntry(**defaults)
```

Then add:

```python
    def test_save_and_retrieve_with_ref_path(self, mgr):
        entry = make_entry(id="know_ref", ref_path="partitions/test/consolidated.md")
        mgr.knowledge.save_entry(entry)
        result = mgr.knowledge.get_entry("know_ref")
        assert result.ref_path == "partitions/test/consolidated.md"

    def test_ref_path_default_none(self, mgr):
        entry = make_entry(id="know_no_ref")
        mgr.knowledge.save_entry(entry)
        result = mgr.knowledge.get_entry("know_no_ref")
        assert result.ref_path is None
```

- [ ] **Step 8: Run all knowledge tests**

Run: `pytest tests/test_knowledge_model.py tests/test_knowledge_storage.py -v`
Expected: All pass

- [ ] **Step 9: Commit**

```bash
git add src/adaptive_preference_engine/knowledge.py scripts/storage.py tests/test_knowledge_model.py tests/test_knowledge_storage.py
git commit -m "feat: add ref_path column to knowledge schema (migration v5)"
```

---

### Task 2: Config — Add new budget defaults

**Files:**
- Modify: `scripts/config.py:67-81`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Add partition and context_injection to _DEFAULTS**

In `scripts/config.py`, update `_DEFAULTS["token_budgets"]` to:

```python
    "token_budgets": {
        "preferences": 500,
        "knowledge": 3000,
        "partition": 1000,
        "context_injection": 2000,
        "signals": 200,
        "total": 5000,
    },
```

- [ ] **Step 2: Write test for new defaults**

In `tests/test_config.py`, add:

```python
    def test_partition_budget_default(self):
        cfg = APEConfig.load(str(self.tmp))
        assert cfg.get("token_budgets.partition") == 1000

    def test_context_injection_budget_default(self):
        cfg = APEConfig.load(str(self.tmp))
        assert cfg.get("token_budgets.context_injection") == 2000
```

- [ ] **Step 3: Run tests and commit**

Run: `pytest tests/test_config.py -v`

```bash
git add scripts/config.py tests/test_config.py
git commit -m "feat: add partition and context_injection token budget defaults"
```

---

### Task 3: CompactionEngine — Core logic

**Files:**
- Create: `scripts/compaction.py`
- Create: `tests/test_compaction.py`

- [ ] **Step 1: Write CompactionEngine with budget check**

Create `scripts/compaction.py`:

```python
"""Knowledge compaction engine — keeps token usage under budget."""

import json
import logging
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from adaptive_preference_engine.knowledge import KnowledgeEntry
from scripts.config import APEConfig, AdaptiveConfig
from scripts.models import generate_id
from scripts.storage import PreferenceStorageManager

logger = logging.getLogger(__name__)
MAX_ROUNDS = 5


class CompactionEngine:
    def __init__(self, storage: PreferenceStorageManager):
        self.storage = storage
        self.cfg = APEConfig.load(str(storage.base_dir))
        adaptive_cfg = AdaptiveConfig(str(storage.base_dir))
        self.sync_repo = Path(adaptive_cfg.sync_repo_path) if adaptive_cfg.sync_repo_path else None

    def check_and_compact(self) -> List[str]:
        """Main entry point. Returns list of compacted partitions."""
        if not self.sync_repo:
            logger.warning("No sync_repo_path configured — skipping compaction")
            return []

        budget = self.cfg.get("token_budgets.knowledge", 3000)
        partition_budget = self.cfg.get("token_budgets.partition", 1000)
        compacted = []

        for _ in range(MAX_ROUNDS):
            entries = self.storage.knowledge.get_all_entries()
            total = sum(e.token_estimate for e in entries)
            if total <= budget:
                break

            # Group by partition
            by_partition = defaultdict(list)
            for e in entries:
                if e.ref_path is None:  # only uncompacted
                    by_partition[e.partition].append(e)

            # Phase 1: compact partitions over their threshold
            over = [(p, es) for p, es in by_partition.items()
                    if sum(e.token_estimate for e in es) > partition_budget and len(es) > 1]
            over.sort(key=lambda x: sum(e.token_estimate for e in x[1]), reverse=True)

            if over:
                partition, p_entries = over[0]
                self._compact_partition(partition, p_entries)
                compacted.append(partition)
                continue

            # Phase 2: no partition over threshold — compact largest
            candidates = [(p, es) for p, es in by_partition.items() if len(es) > 1]
            candidates.sort(key=lambda x: sum(e.token_estimate for e in x[1]), reverse=True)

            if candidates:
                partition, p_entries = candidates[0]
                self._compact_partition(partition, p_entries)
                compacted.append(partition)
                continue

            # Nothing left to compact
            logger.warning("Budget still exceeded but no compactable partitions remain")
            break

        return compacted

    def _compact_partition(self, partition: str, entries: List[KnowledgeEntry]) -> None:
        """Compact entries into a ref file + consolidated DB entry."""
        ref_rel = f"partitions/{partition}/consolidated.md"
        ref_path = self.sync_repo / ref_rel
        ref_path.parent.mkdir(parents=True, exist_ok=True)

        # If ref file exists (re-compaction), read existing content
        existing_content = ""
        if ref_path.exists():
            existing_content = ref_path.read_text(encoding="utf-8")

        # Build new sections
        new_sections = []
        for e in entries:
            new_sections.append(f"## {e.title}\n\n{e.content}")
        new_content = "\n\n".join(new_sections)

        if existing_content:
            full_content = existing_content.rstrip() + "\n\n" + new_content
        else:
            full_content = f"# Knowledge: {partition}\n\n{new_content}"

        ref_path.write_text(full_content, encoding="utf-8")

        # Build summary
        titles = [e.title for e in entries]
        summary = ", ".join(titles)
        all_tags = sorted(set(t for e in entries for t in e.tags))
        max_confidence = max(e.confidence for e in entries)

        # Check if a consolidated entry already exists for this partition
        existing_consolidated = [
            e for e in self.storage.knowledge.get_all_entries()
            if e.partition == partition and e.ref_path is not None
        ]

        if existing_consolidated:
            # Re-compaction: update existing consolidated entry
            consolidated = existing_consolidated[0]
            old_titles = consolidated.content
            consolidated.content = f"{old_titles}, {summary}" if old_titles else summary
            consolidated.tags = sorted(set(consolidated.tags + all_tags))
            consolidated.token_estimate = len(consolidated.content) // 4
            consolidated.confidence = max(consolidated.confidence, max_confidence)
            consolidated.last_used = datetime.now().isoformat()
            self.storage.knowledge.save_entry(consolidated)
        else:
            # New consolidated entry
            slug = partition.replace("/", "_").strip("_")
            consolidated = KnowledgeEntry(
                id=f"compact_{slug}_{int(datetime.now().timestamp())}",
                partition=partition,
                category=entries[0].category,
                title=f"{partition.rstrip('/').split('/')[-1].replace('-', ' ').title()} (consolidated)",
                tags=all_tags,
                content=summary,
                confidence=max_confidence,
                source="compaction",
                decay_exempt=True,
                token_estimate=len(summary) // 4,
                ref_path=ref_rel,
            )
            self.storage.knowledge.save_entry(consolidated)

        # Archive originals
        for e in entries:
            self.storage.knowledge.archive_entry(e.id)

        # Compute savings
        original_tokens = sum(e.token_estimate for e in entries)
        saved = original_tokens - consolidated.token_estimate

        # Auto-commit
        self._git_commit(ref_rel, partition, len(entries), saved)
        logger.info(f"Compacted {partition}: {len(entries)} entries -> 1, saved {saved}t")

    def _git_commit(self, ref_rel: str, partition: str, count: int, saved: int) -> None:
        try:
            subprocess.run(
                ["git", "-C", str(self.sync_repo), "add", ref_rel],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "-C", str(self.sync_repo), "commit", "-m",
                 f"ape: compact {partition} ({count} entries -> 1, saved {saved}t)"],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as exc:
            logger.warning(f"Git commit failed for compaction: {exc.stderr}")

    def read_ref_content(self, entry: KnowledgeEntry) -> Optional[str]:
        """Read full content from ref file. Returns None if file missing."""
        if not entry.ref_path or not self.sync_repo:
            return None
        ref_path = self.sync_repo / entry.ref_path
        if not ref_path.exists():
            logger.warning(f"Ref file missing: {ref_path}")
            return None
        return ref_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Write tests for CompactionEngine**

Create `tests/test_compaction.py`:

```python
"""Tests for CompactionEngine. Run: pytest tests/test_compaction.py -v"""

import sys
from pathlib import Path
import pytest
import json

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.storage import PreferenceStorageManager
from scripts.compaction import CompactionEngine
from adaptive_preference_engine.knowledge import KnowledgeEntry
from scripts.models import generate_id


def make_entry(id, partition="projects/test", content="test content", tokens=100, **kw):
    defaults = dict(
        id=id, partition=partition, category="convention",
        title=f"Entry {id}", tags=["test"], content=content,
        confidence=1.0, token_estimate=tokens,
    )
    defaults.update(kw)
    return KnowledgeEntry(**defaults)


@pytest.fixture
def env(tmp_path):
    """Set up storage + fake sync repo."""
    base = tmp_path / "ape"
    base.mkdir()
    sync = tmp_path / "sync_repo"
    sync.mkdir()
    # Init git in sync repo
    import subprocess
    subprocess.run(["git", "init", str(sync)], capture_output=True)
    subprocess.run(["git", "-C", str(sync), "commit", "--allow-empty", "-m", "init"], capture_output=True)
    # Write config with sync_repo_path
    config = base / "config.json"
    config.write_text(json.dumps({
        "sync_repo_path": str(sync),
        "token_budgets": {"knowledge": 200, "partition": 100},
    }))
    mgr = PreferenceStorageManager(str(base))
    return mgr, sync


class TestCompactionEngine:
    def test_no_compaction_under_budget(self, env):
        mgr, sync = env
        mgr.knowledge.save_entry(make_entry("k1", tokens=50))
        engine = CompactionEngine(mgr)
        result = engine.check_and_compact()
        assert result == []

    def test_compacts_largest_partition(self, env):
        mgr, sync = env
        mgr.knowledge.save_entry(make_entry("k1", partition="projects/big", tokens=80))
        mgr.knowledge.save_entry(make_entry("k2", partition="projects/big", tokens=80))
        mgr.knowledge.save_entry(make_entry("k3", partition="projects/small", tokens=50))
        engine = CompactionEngine(mgr)
        result = engine.check_and_compact()
        assert "projects/big" in result
        # Originals archived
        all_active = mgr.knowledge.get_all_entries()
        active_ids = [e.id for e in all_active]
        assert "k1" not in active_ids
        assert "k2" not in active_ids
        assert "k3" in active_ids
        # Consolidated entry exists
        consolidated = [e for e in all_active if e.ref_path is not None]
        assert len(consolidated) == 1
        assert consolidated[0].partition == "projects/big"
        # Ref file written
        ref_file = sync / consolidated[0].ref_path
        assert ref_file.exists()

    def test_ref_content_readable(self, env):
        mgr, sync = env
        mgr.knowledge.save_entry(make_entry("k1", partition="p/a", content="alpha", tokens=120))
        mgr.knowledge.save_entry(make_entry("k2", partition="p/a", content="beta", tokens=120))
        engine = CompactionEngine(mgr)
        engine.check_and_compact()
        consolidated = [e for e in mgr.knowledge.get_all_entries() if e.ref_path][0]
        content = engine.read_ref_content(consolidated)
        assert "alpha" in content
        assert "beta" in content

    def test_loop_safety_cap(self, env):
        mgr, sync = env
        # All single-entry partitions — nothing to compact
        for i in range(10):
            mgr.knowledge.save_entry(make_entry(f"k{i}", partition=f"p/{i}", tokens=30))
        engine = CompactionEngine(mgr)
        result = engine.check_and_compact()
        assert len(result) <= 5  # MAX_ROUNDS cap
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_compaction.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add scripts/compaction.py tests/test_compaction.py
git commit -m "feat: add CompactionEngine with budget-triggered partition compaction"
```

---

### Task 4: Wire compaction into `knowledge add`

**Files:**
- Modify: `scripts/cli.py:1165-1182`

- [ ] **Step 1: Import and call CompactionEngine after save**

In `scripts/cli.py`, at the end of `cmd_knowledge_add()` (after `print(f"Added: ...")`), add:

```python
        # Trigger compaction check
        try:
            from scripts.compaction import CompactionEngine
            engine = CompactionEngine(self.storage)
            compacted = engine.check_and_compact()
            for p in compacted:
                print(f"  Compacted: {p}")
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(f"Compaction check failed: {exc}")
```

- [ ] **Step 2: Test manually (no automated test needed — engine is tested in Task 3)**

Run: `adaptive-cli knowledge add --partition test/manual --category convention --title "Test" --tags test --content "hello world"`

- [ ] **Step 3: Commit**

```bash
git add scripts/cli.py
git commit -m "feat: trigger compaction check after knowledge add"
```

---

### Task 5: Wire compaction into `sync pull`

**Files:**
- Modify: `scripts/sync.py:69-131`

- [ ] **Step 1: Add post-import compaction call**

In `scripts/sync.py`, in `import_from()`, after the knowledge import loop (after line ~131), add:

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add scripts/sync.py
git commit -m "feat: trigger compaction after sync pull imports knowledge"
```

---

### Task 6: CLI updates — `show`, `list`, `search`, `stats`

**Files:**
- Modify: `scripts/cli.py:1184-1260` (show/list/search), `scripts/cli.py:377-426` (stats)

- [ ] **Step 1: Update `knowledge show` to load ref content**

In `cmd_knowledge_show()`, after displaying the entry fields, add ref_path handling:

```python
        if entry.ref_path:
            print(f"  Ref Path:   {entry.ref_path}")
            try:
                from scripts.compaction import CompactionEngine
                engine = CompactionEngine(self.storage)
                full = engine.read_ref_content(entry)
                if full:
                    print(f"\n  --- Full content (loaded from {entry.ref_path}) ---\n")
                    print(full)
                else:
                    print(f"\n  WARNING: Ref file not found at {entry.ref_path}")
            except Exception:
                print(f"  Content:    {entry.content}")
```

- [ ] **Step 2: Update `knowledge list` to show [ref] indicator**

In `cmd_knowledge_list()`, in the entry display line, append `[ref]` when `e.ref_path` is not None:

```python
                flag = " [ref]" if e.ref_path else ""
                # existing: flag already used for archived indicator
                # append ref indicator
```

Find the existing line that prints each entry (around line 1256) and add the ref flag.

- [ ] **Step 3: Update `stats --oneline` — no change needed**

The stats already count `token_estimate` which is the summary size for compacted entries. The `[prune]` indicator will naturally disappear once compaction brings totals under budget. No code change required.

- [ ] **Step 4: Commit**

```bash
git add scripts/cli.py
git commit -m "feat: knowledge show loads ref content, list shows [ref] indicator"
```

---

### Task 7: Sync — export/import ref_path

**Files:**
- Modify: `scripts/sync.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Verify export already works**

`sync.export()` calls `k.to_dict()` which already includes `ref_path` (from Task 1). `sync.import_from()` calls `KnowledgeEntry.from_dict(d)` which handles unknown/new fields via `_filter_fields`. Verify with a test.

- [ ] **Step 2: Write test for ref_path sync round-trip**

In `tests/test_sync.py`, add:

```python
    def test_knowledge_ref_path_round_trip(self, env):
        mgr, sync_dir = env
        entry = make_knowledge_entry(id="know_ref", ref_path="partitions/test/consolidated.md")
        mgr.knowledge.save_entry(entry)
        PreferenceSync.export(mgr, sync_dir)
        # Clear and reimport
        mgr.knowledge.delete_entry("know_ref")
        PreferenceSync.import_from(mgr, sync_dir)
        result = mgr.knowledge.get_entry("know_ref")
        assert result is not None
        assert result.ref_path == "partitions/test/consolidated.md"
```

Add `make_knowledge_entry` helper if not present (similar to test_compaction.py's `make_entry`).

- [ ] **Step 3: Add warning for missing ref file on import**

In `sync.import_from()`, after importing a knowledge entry with `ref_path`, check if the file exists in the sync dir:

```python
                if hasattr(entry, 'ref_path') and entry.ref_path:
                    ref_file = src_dir / entry.ref_path
                    if not ref_file.exists():
                        print(f"  WARNING: Knowledge entry {entry.id} references {entry.ref_path} but file not found")
```

- [ ] **Step 4: Run tests and commit**

Run: `pytest tests/test_sync.py -v`

```bash
git add scripts/sync.py tests/test_sync.py
git commit -m "feat: sync exports/imports ref_path, warns on missing ref files"
```

---

### Task 8: Knowledge context injection in load_for_agent

**Files:**
- Modify: `src/adaptive_preference_engine/services/loading.py:226-253`
- Modify: `scripts/agent_hook.py:21-43`
- Create: `tests/test_knowledge_injection.py`

- [ ] **Step 1: Add knowledge loading method to PreferenceLoader**

In `src/adaptive_preference_engine/services/loading.py`, add method to `PreferenceLoader`:

```python
    def load_knowledge_for_context(
        self,
        context_tags: List[str],
        sync_repo_path: Optional[str] = None,
        max_tokens: int = 2000,
    ) -> List[Dict[str, Any]]:
        """Load knowledge entries matching context tags, reading ref files for compacted entries."""
        from adaptive_preference_engine.knowledge import KnowledgeEntry

        all_entries = self.storage.knowledge.get_all_entries()
        tags_lower = {t.lower() for t in context_tags}

        # Score entries by relevance
        scored = []
        for entry in all_entries:
            # Match: partition contains a context tag, or tags overlap
            partition_parts = set(entry.partition.lower().replace("/", " ").split())
            entry_tags = {t.lower() for t in entry.tags}
            partition_match = bool(partition_parts & tags_lower)
            tag_match = bool(entry_tags & tags_lower)

            if not (partition_match or tag_match):
                continue

            score = (
                (2 if partition_match else 0)
                + (1 if tag_match else 0)
                + entry.confidence * 0.5
                + min(entry.access_count, 10) * 0.05
            )
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Collect within token budget
        results = []
        used_tokens = 0
        for score, entry in scored:
            if entry.ref_path and sync_repo_path:
                ref_file = Path(sync_repo_path) / entry.ref_path
                if ref_file.exists():
                    content = ref_file.read_text(encoding="utf-8")
                    source = "ref_file"
                else:
                    content = entry.content
                    source = "summary_only"
            else:
                content = entry.content
                source = "inline"

            est_tokens = len(content) // 4
            if used_tokens + est_tokens > max_tokens:
                break

            results.append({
                "title": entry.title,
                "partition": entry.partition,
                "content": content,
                "source": source,
            })
            used_tokens += est_tokens
            self.storage.knowledge.record_access(entry.id)

        return results
```

- [ ] **Step 2: Extend load_for_agent to include knowledge**

In `load_for_agent()`, after building `agent_context`, add:

```python
        # Load matching knowledge
        from scripts.config import AdaptiveConfig
        adaptive_cfg = AdaptiveConfig(str(self.storage.base_dir))
        sync_repo = adaptive_cfg.sync_repo_path

        from scripts.config import APEConfig
        ape_cfg = APEConfig.load(str(self.storage.base_dir))
        injection_budget = ape_cfg.get("token_budgets.context_injection", 2000)

        knowledge = self.load_knowledge_for_context(
            context_tags=context_tags,
            sync_repo_path=sync_repo,
            max_tokens=injection_budget,
        )
        agent_context["knowledge"] = knowledge
```

- [ ] **Step 3: Write tests**

Create `tests/test_knowledge_injection.py`:

```python
"""Tests for knowledge context injection. Run: pytest tests/test_knowledge_injection.py -v"""

import sys, json
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.storage import PreferenceStorageManager
from adaptive_preference_engine.services.loading import PreferenceLoader
from adaptive_preference_engine.knowledge import KnowledgeEntry


def make_entry(id, partition, tags, content="test", tokens=50, **kw):
    return KnowledgeEntry(
        id=id, partition=partition, category="convention",
        title=f"Entry {id}", tags=tags, content=content,
        confidence=1.0, token_estimate=tokens, **kw,
    )


@pytest.fixture
def env(tmp_path):
    base = tmp_path / "ape"
    base.mkdir()
    config = base / "config.json"
    config.write_text(json.dumps({"sync_repo_path": str(tmp_path / "sync")}))
    (tmp_path / "sync").mkdir()
    mgr = PreferenceStorageManager(str(base))
    loader = PreferenceLoader(mgr)
    return mgr, loader, tmp_path / "sync"


class TestKnowledgeInjection:
    def test_matches_by_tag(self, env):
        mgr, loader, sync = env
        mgr.knowledge.save_entry(make_entry("k1", "projects/foo", ["python"]))
        mgr.knowledge.save_entry(make_entry("k2", "projects/bar", ["rust"]))
        results = loader.load_knowledge_for_context(["python"])
        assert len(results) == 1
        assert results[0]["title"] == "Entry k1"

    def test_matches_by_partition(self, env):
        mgr, loader, sync = env
        mgr.knowledge.save_entry(make_entry("k1", "projects/webex-notes", ["tui"]))
        results = loader.load_knowledge_for_context(["webex-notes"])
        assert len(results) == 1

    def test_loads_ref_file_content(self, env):
        mgr, loader, sync = env
        ref_dir = sync / "partitions" / "p"
        ref_dir.mkdir(parents=True)
        (ref_dir / "consolidated.md").write_text("Full detailed content here")
        mgr.knowledge.save_entry(make_entry(
            "k1", "p", ["test"], content="summary",
            ref_path="partitions/p/consolidated.md",
        ))
        results = loader.load_knowledge_for_context(
            ["test"], sync_repo_path=str(sync),
        )
        assert len(results) == 1
        assert "Full detailed content" in results[0]["content"]
        assert results[0]["source"] == "ref_file"

    def test_respects_token_budget(self, env):
        mgr, loader, sync = env
        # Each entry ~100 tokens of content
        for i in range(10):
            mgr.knowledge.save_entry(make_entry(
                f"k{i}", "projects/big", ["test"],
                content="x" * 400, tokens=100,
            ))
        results = loader.load_knowledge_for_context(
            ["test"], max_tokens=500,
        )
        assert len(results) < 10

    def test_no_match_returns_empty(self, env):
        mgr, loader, sync = env
        mgr.knowledge.save_entry(make_entry("k1", "projects/foo", ["python"]))
        results = loader.load_knowledge_for_context(["unrelated"])
        assert results == []
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_knowledge_injection.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_preference_engine/services/loading.py scripts/agent_hook.py tests/test_knowledge_injection.py
git commit -m "feat: inject matching knowledge into agent context with token budget"
```

---

### Task 9 (final): Integration test + cleanup

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/glouie/github/adaptive-preference-engine
pytest tests/ -v --tb=short
```

Fix any failures.

- [ ] **Step 2: Verify compaction resolves the current [prune] warning**

```bash
adaptive-cli knowledge list
adaptive-cli stats --oneline
# Should still show [prune] until a knowledge add triggers compaction
# Manually trigger: adaptive-cli knowledge add --partition test/trigger --category convention --title "Trigger" --tags test --content "trigger compaction"
adaptive-cli stats --oneline
# [prune] should be gone
```

- [ ] **Step 3: Clean up test entry and commit**

```bash
adaptive-cli knowledge archive "Trigger"
git add -A
git commit -m "test: verify compaction resolves [prune] statusline warning"
```
