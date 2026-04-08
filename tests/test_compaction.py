"""Tests for CompactionEngine. Run: pytest tests/test_compaction.py -v"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adaptive_preference_engine.knowledge import KnowledgeEntry
from scripts.compaction import CompactionEngine, MAX_ROUNDS
from scripts.config import AdaptiveConfig, APEConfig
from scripts.models import generate_id
from scripts.storage import PreferenceStorageManager


def make_entry(**kwargs) -> KnowledgeEntry:
    """Helper to create test knowledge entries."""
    defaults = dict(
        id=generate_id("test"),
        partition="projects/test",
        category="convention",
        title="Test Entry",
        tags=["test"],
        content="Some test content here.",
        confidence=1.0,
        token_estimate=50,
        ref_path=None,
    )
    defaults.update(kwargs)
    return KnowledgeEntry(**defaults)


@pytest.fixture
def temp_env(tmp_path):
    """Create temp storage and sync repo with git initialized."""
    # Create storage dir
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()

    # Create sync repo dir with git init
    sync_repo = tmp_path / "sync_repo"
    sync_repo.mkdir()

    # Initialize git repo
    subprocess.run(
        ["git", "init"],
        cwd=str(sync_repo),
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(sync_repo),
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(sync_repo),
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(sync_repo),
        check=True,
        capture_output=True
    )

    # Create config with sync_repo_path and low budgets
    config_path = storage_dir / "config.json"
    config_data = {
        "sync_repo_path": str(sync_repo),
        "token_budgets": {
            "knowledge": 200,
            "partition": 100,
        }
    }
    config_path.write_text(json.dumps(config_data, indent=2))

    # Create storage manager
    mgr = PreferenceStorageManager(str(storage_dir))

    return {
        "storage_dir": storage_dir,
        "sync_repo": sync_repo,
        "mgr": mgr,
    }


class TestCompactionEngine:
    def test_no_compaction_under_budget(self, temp_env):
        """Test that no compaction happens when under budget."""
        mgr = temp_env["mgr"]

        # Add single entry at 50 tokens (under 200 budget)
        entry = make_entry(
            id="entry_1",
            partition="projects/test",
            token_estimate=50
        )
        mgr.knowledge.save_entry(entry)

        # Create engine and check compaction
        engine = CompactionEngine(mgr)
        compacted = engine.check_and_compact()

        assert len(compacted) == 0, "Should not compact when under budget"

    def test_compacts_largest_partition(self, temp_env):
        """Test that compaction targets the largest partition when over budget."""
        mgr = temp_env["mgr"]
        sync_repo = temp_env["sync_repo"]

        # Add 3 entries: 2 in "projects/big" (80t each), 1 in "projects/small" (50t)
        # Total: 210 tokens (over 200 budget)
        mgr.knowledge.save_entry(
            make_entry(
                id="big_1",
                partition="projects/big",
                title="Big Entry 1",
                token_estimate=80
            )
        )
        mgr.knowledge.save_entry(
            make_entry(
                id="big_2",
                partition="projects/big",
                title="Big Entry 2",
                token_estimate=80
            )
        )
        mgr.knowledge.save_entry(
            make_entry(
                id="small_1",
                partition="projects/small",
                title="Small Entry",
                token_estimate=50
            )
        )

        # Create engine and compact
        engine = CompactionEngine(mgr)
        compacted = engine.check_and_compact()

        # Verify "projects/big" was compacted
        assert "projects/big" in compacted, "Should compact the largest partition"
        assert "projects/small" not in compacted, "Should not compact small partition"

        # Verify original entries are archived
        big_1 = mgr.knowledge.get_entry("big_1")
        big_2 = mgr.knowledge.get_entry("big_2")
        assert big_1.archived, "Original entry should be archived"
        assert big_2.archived, "Original entry should be archived"

        # Verify consolidated entry exists
        all_entries = mgr.knowledge.get_all_entries(include_archived=False)
        consolidated_entries = [
            e for e in all_entries
            if e.partition == "projects/big" and e.ref_path
        ]
        assert len(consolidated_entries) == 1, "Should have 1 consolidated entry"

        consolidated = consolidated_entries[0]
        assert consolidated.ref_path, "Consolidated entry should have ref_path"
        assert consolidated.category == "consolidated"
        assert "Consolidated" in consolidated.title

        # Verify ref file exists
        ref_file = sync_repo / consolidated.ref_path
        assert ref_file.exists(), f"Ref file should exist at {ref_file}"

        # Verify ref file content
        content = ref_file.read_text()
        assert "Big Entry 1" in content
        assert "Big Entry 2" in content
        assert "projects/big" in content

    def test_ref_content_readable(self, temp_env):
        """Test that read_ref_content returns full content from ref file."""
        mgr = temp_env["mgr"]

        # Add 2 entries to trigger compaction (110 * 2 = 220 > 200 budget)
        mgr.knowledge.save_entry(
            make_entry(
                id="entry_1",
                partition="projects/test",
                title="Entry One",
                content="Content for entry one.",
                token_estimate=110
            )
        )
        mgr.knowledge.save_entry(
            make_entry(
                id="entry_2",
                partition="projects/test",
                title="Entry Two",
                content="Content for entry two.",
                token_estimate=110
            )
        )

        # Compact
        engine = CompactionEngine(mgr)
        compacted = engine.check_and_compact()
        assert len(compacted) == 1

        # Find consolidated entry
        all_entries = mgr.knowledge.get_all_entries(include_archived=False)
        consolidated = [e for e in all_entries if e.ref_path][0]

        # Read ref content
        content = engine.read_ref_content(consolidated)
        assert content is not None, "Should read ref content"
        assert "Entry One" in content
        assert "Entry Two" in content
        assert "Content for entry one." in content
        assert "Content for entry two." in content

    def test_loop_safety_cap(self, temp_env):
        """Test that compaction loop caps at MAX_ROUNDS."""
        mgr = temp_env["mgr"]

        # Create 10 single-entry partitions at 30t each (total 300 > 200 budget)
        # These can't be compacted (need 2+ entries), so loop should cap
        for i in range(10):
            mgr.knowledge.save_entry(
                make_entry(
                    id=f"entry_{i}",
                    partition=f"projects/single_{i}",
                    title=f"Single Entry {i}",
                    token_estimate=30
                )
            )

        # Compact should try and fail, but cap at MAX_ROUNDS
        engine = CompactionEngine(mgr)
        compacted = engine.check_and_compact()

        # No partitions should be compacted (all have single entries)
        assert len(compacted) == 0, "Should not compact single-entry partitions"

        # Verify all entries are still non-archived
        all_entries = mgr.knowledge.get_all_entries(include_archived=False)
        assert len(all_entries) == 10, "All entries should remain non-archived"

    def test_re_compaction(self, temp_env):
        """Test re-compaction when adding more entries to an already-compacted partition."""
        mgr = temp_env["mgr"]
        sync_repo = temp_env["sync_repo"]

        # First compaction: add 2 entries (110 * 2 = 220 > 200 budget)
        mgr.knowledge.save_entry(
            make_entry(
                id="entry_1",
                partition="projects/test",
                title="Entry 1",
                token_estimate=110
            )
        )
        mgr.knowledge.save_entry(
            make_entry(
                id="entry_2",
                partition="projects/test",
                title="Entry 2",
                token_estimate=110
            )
        )

        engine = CompactionEngine(mgr)
        compacted = engine.check_and_compact()
        assert "projects/test" in compacted

        # Get the consolidated entry
        all_entries = mgr.knowledge.get_all_entries(include_archived=False)
        first_consolidated = [e for e in all_entries if e.ref_path][0]
        first_ref_path = first_consolidated.ref_path

        # Add 2 more entries to same partition (triggers re-compaction)
        mgr.knowledge.save_entry(
            make_entry(
                id="entry_3",
                partition="projects/test",
                title="Entry 3",
                token_estimate=110
            )
        )
        mgr.knowledge.save_entry(
            make_entry(
                id="entry_4",
                partition="projects/test",
                title="Entry 4",
                token_estimate=110
            )
        )

        # Re-compact
        compacted = engine.check_and_compact()
        assert "projects/test" in compacted

        # Verify the consolidated entry was updated (not a new one created)
        all_entries = mgr.knowledge.get_all_entries(include_archived=False)
        consolidated_entries = [e for e in all_entries if e.ref_path]
        assert len(consolidated_entries) == 1, "Should still have 1 consolidated entry"

        # Verify ref file contains the new entries (Entry 3 and 4)
        # Note: Entry 1 and 2 were archived in first compaction, so only new entries
        # are included in re-compaction
        ref_file = sync_repo / first_ref_path
        content = ref_file.read_text()
        assert "Entry 3" in content
        assert "Entry 4" in content
        assert "re-compaction" in content.lower(), "Should indicate this is a re-compaction"

    def test_no_sync_repo_configured(self, tmp_path):
        """Test that compaction is skipped if no sync_repo_path configured."""
        # Create storage without sync_repo_path
        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()

        mgr = PreferenceStorageManager(str(storage_dir))

        # Add entries over budget
        mgr.knowledge.save_entry(
            make_entry(id="e1", partition="p/test", token_estimate=2000)
        )
        mgr.knowledge.save_entry(
            make_entry(id="e2", partition="p/test", token_estimate=2000)
        )

        engine = CompactionEngine(mgr)
        compacted = engine.check_and_compact()

        # Should return empty list (no compaction)
        assert len(compacted) == 0, "Should skip compaction when no sync_repo_path"
