"""Tests for memory consolidation. Run: pytest tests/test_memory_consolidation.py -v"""

import json
import subprocess
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
