"""Tests for memory consolidation. Run: pytest tests/test_memory_consolidation.py -v"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.storage import PreferenceStorageManager, ConfidentialStorageManager
from scripts.memory_generator import generate_memory_files, parse_memory_file
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

    def test_cleans_stale_md_files(self, public_mgr, tmp_path):
        """When an entry is archived/deleted, its .md file should be removed."""
        # First generation: create an entry
        public_mgr.knowledge.save_entry(make_entry(
            id="know_1", title="Active Entry", content="Active content",
        ))
        public_mgr.knowledge.save_entry(make_entry(
            id="know_2", title="Will Be Archived", content="Soon to be stale",
        ))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        count = generate_memory_files(public_mgr, None, memory_dir)
        assert count == 2

        # Verify both files exist
        md_files = [f for f in memory_dir.glob("*.md") if f.name != "MEMORY.md"]
        assert len(md_files) == 2

        # Archive one entry
        entry2 = public_mgr.knowledge.get_entry("know_2")
        entry2.archived = True
        public_mgr.knowledge.save_entry(entry2)

        # Second generation: should remove the stale file
        count = generate_memory_files(public_mgr, None, memory_dir)
        assert count == 1

        # Verify only one non-index .md file remains
        md_files = [f for f in memory_dir.glob("*.md") if f.name != "MEMORY.md"]
        assert len(md_files) == 1
        assert "active_entry" in md_files[0].name.lower()

        # MEMORY.md should still exist
        assert (memory_dir / "MEMORY.md").exists()


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
