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
