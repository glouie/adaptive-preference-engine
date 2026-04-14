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

    def test_sync_meta(self, confidential_mgr):
        confidential_mgr.update_sync_meta(push_at="2026-04-14T12:00:00")
        meta = confidential_mgr.get_sync_meta()
        assert meta["last_push_at"] == "2026-04-14T12:00:00"
        assert meta["last_pull_at"] is None
