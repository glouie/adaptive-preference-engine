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
