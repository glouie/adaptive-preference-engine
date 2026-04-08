"""Tests for KnowledgeStorage CRUD. Run: pytest tests/test_knowledge_storage.py -v"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.storage import PreferenceStorageManager
from adaptive_preference_engine.knowledge import KnowledgeEntry
from scripts.models import generate_id


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
    )
    defaults.update(kwargs)
    return KnowledgeEntry(**defaults)


@pytest.fixture
def mgr(tmp_path):
    return PreferenceStorageManager(str(tmp_path))


class TestKnowledgeStorage:
    def test_save_and_retrieve(self, mgr):
        entry = make_entry(id="know_001", title="Test Entry")
        mgr.knowledge.save_entry(entry)
        result = mgr.knowledge.get_entry("know_001")
        assert result is not None
        assert result.title == "Test Entry"
        assert result.tags == ["test"]

    def test_get_all_excludes_archived(self, mgr):
        mgr.knowledge.save_entry(make_entry(id="know_a", title="Active"))
        mgr.knowledge.save_entry(make_entry(id="know_b", title="Archived", archived=True))
        results = mgr.knowledge.get_all_entries()
        assert len(results) == 1
        assert results[0].id == "know_a"

    def test_get_all_includes_archived(self, mgr):
        mgr.knowledge.save_entry(make_entry(id="know_a"))
        mgr.knowledge.save_entry(make_entry(id="know_b", archived=True))
        results = mgr.knowledge.get_all_entries(include_archived=True)
        assert len(results) == 2

    def test_search_by_tags(self, mgr):
        mgr.knowledge.save_entry(make_entry(id="know_1", tags=["cinc", "ops"]))
        mgr.knowledge.save_entry(make_entry(id="know_2", tags=["textual", "tui"]))
        results = mgr.knowledge.search_by_tags(["cinc"])
        assert len(results) == 1
        assert results[0].id == "know_1"

    def test_archive_and_restore(self, mgr):
        mgr.knowledge.save_entry(make_entry(id="know_1"))
        mgr.knowledge.archive_entry("know_1")
        result = mgr.knowledge.get_entry("know_1")
        assert result.archived is True
        mgr.knowledge.unarchive_entry("know_1")
        result = mgr.knowledge.get_entry("know_1")
        assert result.archived is False

    def test_get_by_partition(self, mgr):
        mgr.knowledge.save_entry(make_entry(id="know_1", partition="projects/cinc"))
        mgr.knowledge.save_entry(make_entry(id="know_2", partition="domains/tools"))
        results = mgr.knowledge.get_entries_by_partition("projects/cinc")
        assert len(results) == 1
        assert results[0].id == "know_1"

    def test_get_by_category(self, mgr):
        mgr.knowledge.save_entry(make_entry(id="know_1", category="convention"))
        mgr.knowledge.save_entry(make_entry(id="know_2", category="decision"))
        results = mgr.knowledge.get_entries_by_category("convention")
        assert len(results) == 1
        assert results[0].id == "know_1"

    def test_upsert_on_save(self, mgr):
        entry = make_entry(id="know_1", title="Original")
        mgr.knowledge.save_entry(entry)
        entry.title = "Updated"
        mgr.knowledge.save_entry(entry)
        result = mgr.knowledge.get_entry("know_1")
        assert result.title == "Updated"

    def test_record_access(self, mgr):
        mgr.knowledge.save_entry(make_entry(id="know_1"))
        mgr.knowledge.record_access("know_1")
        mgr.knowledge.record_access("know_1")
        result = mgr.knowledge.get_entry("know_1")
        assert result.access_count == 2

    def test_delete_entry(self, mgr):
        mgr.knowledge.save_entry(make_entry(id="know_1"))
        mgr.knowledge.delete_entry("know_1")
        assert mgr.knowledge.get_entry("know_1") is None

    def test_storage_info_includes_knowledge(self, mgr):
        mgr.knowledge.save_entry(make_entry(id="know_1"))
        info = mgr.get_storage_info()
        assert "knowledge_count" in info
        assert info["knowledge_count"] == 1
