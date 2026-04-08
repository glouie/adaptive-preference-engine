"""Tests for KnowledgeEntry model. Run: pytest tests/test_knowledge_model.py -v"""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from adaptive_preference_engine.knowledge import KnowledgeEntry


class TestKnowledgeEntry:
    def test_create_with_defaults(self):
        entry = KnowledgeEntry(id="know_abc", partition="projects/test", category="convention",
                               title="Test", tags=["test"], content="content")
        assert entry.confidence == 1.0
        assert entry.source == "explicit"
        assert entry.archived is False
        assert entry.decay_exempt is False
        assert entry.access_count == 0

    def test_to_dict_round_trip(self):
        entry = KnowledgeEntry(id="know_abc", partition="user", category="preference",
                               title="Prefs", tags=["pref", "style"], content="tables",
                               confidence=0.9, source="migrated", machine_origin="mac",
                               decay_exempt=True, access_count=5, token_estimate=42)
        d = entry.to_dict()
        restored = KnowledgeEntry.from_dict(d)
        assert restored.id == entry.id
        assert restored.tags == ["pref", "style"]
        assert restored.decay_exempt is True
        assert restored.machine_origin == "mac"

    def test_from_dict_ignores_unknown_fields(self):
        d = {"id": "x", "partition": "p", "category": "c", "title": "t",
             "tags": ["a"], "content": "c", "unknown": "ignored"}
        entry = KnowledgeEntry.from_dict(d)
        assert entry.id == "x"

    def test_tags_stored_as_list(self):
        entry = KnowledgeEntry(id="x", partition="p", category="c", title="t",
                               tags=["a", "b"], content="c")
        assert isinstance(entry.to_dict()["tags"], list)

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
