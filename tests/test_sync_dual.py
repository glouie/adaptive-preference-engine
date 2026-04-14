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
