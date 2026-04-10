"""Tests for context detection and filtered loading. Run: pytest tests/test_context_detection.py -v"""

import sys
from pathlib import Path
import subprocess
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adaptive_preference_engine.storage import PreferenceStorageManager
from adaptive_preference_engine.services.context_detection import (
    detect_context,
    is_universal_prefix,
    matches_context,
    UNIVERSAL_PREFIXES,
)
from adaptive_preference_engine.services.loading import PreferenceLoader
from adaptive_preference_engine.models import Preference


def make_pref(id, path, confidence=0.8, tier="hot", value="test"):
    return Preference(
        id=id,
        path=path,
        parent_id=None,
        name=path.split(".")[-1],
        type="property",
        value=value,
        confidence=confidence,
        tier=tier,
    )


@pytest.fixture
def storage(tmp_path):
    return PreferenceStorageManager(str(tmp_path))


@pytest.fixture
def loader(storage):
    return PreferenceLoader(storage)


class TestDetectContext:
    def test_detect_context_git_repo(self, tmp_path):
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)

        tags = detect_context(str(tmp_path))

        assert tmp_path.name in tags

    def test_detect_context_python_project(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname = 'test'")

        tags = detect_context(str(tmp_path))

        assert "python" in tags

    def test_detect_context_javascript_project(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')

        tags = detect_context(str(tmp_path))

        assert "javascript" in tags

    def test_detect_context_claude_md(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# My Project\n\nSome content")

        tags = detect_context(str(tmp_path))

        assert "my-project" in tags

    def test_detect_context_claude_md_with_spaces(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Skills Marketplace Plugin\n\nContent")

        tags = detect_context(str(tmp_path))

        assert "skills-marketplace-plugin" in tags

    def test_detect_context_no_git(self, tmp_path):
        tags = detect_context(str(tmp_path))

        assert not any(tag == tmp_path.name for tag in tags)

    def test_detect_context_multiple_markers(self, tmp_path):
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "pyproject.toml").write_text("[tool]")
        (tmp_path / "package.json").write_text('{}')
        (tmp_path / "CLAUDE.md").write_text("# Test Project")

        tags = detect_context(str(tmp_path))

        assert "python" in tags
        assert "javascript" in tags
        assert "test-project" in tags
        assert tmp_path.name in tags

    def test_detect_context_go_project(self, tmp_path):
        (tmp_path / "go.mod").write_text("module test")

        tags = detect_context(str(tmp_path))

        assert "go" in tags

    def test_detect_context_rust_project(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "test"')

        tags = detect_context(str(tmp_path))

        assert "rust" in tags

    def test_detect_context_claude_md_no_header(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("Some content without header")

        tags = detect_context(str(tmp_path))

        assert len([t for t in tags if "-" in t]) == 0

    def test_detect_context_claude_md_special_chars(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Test@Project#123")

        tags = detect_context(str(tmp_path))

        assert "testproject123" in tags


class TestIsUniversalPrefix:
    def test_is_universal_prefix_workflow_git(self):
        assert is_universal_prefix("workflow.git.commit_style") is True

    def test_is_universal_prefix_general(self):
        assert is_universal_prefix("general.code_quality") is True

    def test_is_universal_prefix_tools_cli(self):
        assert is_universal_prefix("tools.cli.jira") is True

    def test_is_universal_prefix_not_universal(self):
        assert is_universal_prefix("project.specific.setting") is False

    def test_is_universal_prefix_partial_match(self):
        assert is_universal_prefix("workflow.git") is True

    def test_is_universal_prefix_custom_list(self):
        custom = ["custom.prefix", "another.prefix"]
        assert is_universal_prefix("custom.prefix.value", custom) is True
        assert is_universal_prefix("workflow.git", custom) is False

    def test_is_universal_prefix_empty_list(self):
        assert is_universal_prefix("workflow.git", []) is False


class TestMatchesContext:
    def test_matches_context_universal(self):
        assert matches_context("workflow.git.commit", ["python", "project-x"]) is True

    def test_matches_context_segment_match(self):
        assert matches_context("tools.sharepoint.upload_method", ["sharepoint"]) is True

    def test_matches_context_substring_match(self):
        assert matches_context("tools.slack_ops.channels", ["slack"]) is True

    def test_matches_context_no_match(self):
        assert matches_context("tools.gitlab.mr_review", ["jira", "python"]) is False

    def test_matches_context_case_insensitive(self):
        assert matches_context("tools.SharePoint.upload", ["sharepoint"]) is True
        assert matches_context("tools.sharepoint.upload", ["SharePoint"]) is True

    def test_matches_context_multiple_tags(self):
        assert matches_context("project.python.formatter", ["python", "javascript"]) is True

    def test_matches_context_universal_overrides(self):
        assert matches_context("general.code_style", ["unrelated"]) is True

    def test_matches_context_exact_segment_priority(self):
        assert matches_context("project.javascript.linter", ["javascript"]) is True

    def test_matches_context_empty_tags(self):
        assert matches_context("project.specific.setting", []) is False

    def test_matches_context_custom_prefixes(self):
        custom = ["custom.workflow"]
        assert matches_context("custom.workflow.step", ["unrelated"], custom) is True
        assert matches_context("workflow.git", ["unrelated"], custom) is False


class TestLoadAllByTier:
    def test_load_all_by_tier_hot_only(self, storage, loader):
        prefs = [
            make_pref("hot_1", "test.hot1", tier="hot"),
            make_pref("hot_2", "test.hot2", tier="hot"),
            make_pref("warm_1", "test.warm1", tier="warm"),
            make_pref("cold_1", "test.cold1", tier="cold"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        results = loader.load_all_by_tier("hot")

        assert len(results) == 2
        assert all(r["tier"] == "hot" for r in results)
        assert {r["id"] for r in results} == {"hot_1", "hot_2"}

    def test_load_all_by_tier_warm_only(self, storage, loader):
        prefs = [
            make_pref("hot_1", "test.hot1", tier="hot"),
            make_pref("warm_1", "test.warm1", tier="warm"),
            make_pref("warm_2", "test.warm2", tier="warm"),
            make_pref("cold_1", "test.cold1", tier="cold"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        results = loader.load_all_by_tier("warm")

        assert len(results) == 2
        assert all(r["tier"] == "warm" for r in results)

    def test_load_all_by_tier_cold_only(self, storage, loader):
        prefs = [
            make_pref("hot_1", "test.hot1", tier="hot"),
            make_pref("cold_1", "test.cold1", tier="cold"),
            make_pref("cold_2", "test.cold2", tier="cold"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        results = loader.load_all_by_tier("cold")

        assert len(results) == 2
        assert all(r["tier"] == "cold" for r in results)

    def test_load_all_by_tier_with_context(self, storage, loader):
        prefs = [
            make_pref("hot_py", "project.python.formatter", tier="hot"),
            make_pref("hot_js", "project.javascript.linter", tier="hot"),
            make_pref("hot_gen", "general.code_style", tier="hot"),
            make_pref("hot_git", "workflow.git.commit", tier="hot"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        results = loader.load_all_by_tier("hot", context_tags=["python"])

        result_ids = {r["id"] for r in results}
        assert "hot_py" in result_ids
        assert "hot_gen" in result_ids
        assert "hot_git" in result_ids
        assert "hot_js" not in result_ids

    def test_load_all_by_tier_empty(self, storage, loader):
        prefs = [
            make_pref("hot_1", "test.hot1", tier="hot"),
            make_pref("hot_2", "test.hot2", tier="hot"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        results = loader.load_all_by_tier("warm")

        assert results == []

    def test_load_all_by_tier_sorted_by_confidence(self, storage, loader):
        prefs = [
            make_pref("hot_low", "test.hot_low", confidence=0.5, tier="hot"),
            make_pref("hot_high", "test.hot_high", confidence=0.9, tier="hot"),
            make_pref("hot_mid", "test.hot_mid", confidence=0.7, tier="hot"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        results = loader.load_all_by_tier("hot")

        assert len(results) == 3
        assert results[0]["id"] == "hot_high"
        assert results[1]["id"] == "hot_mid"
        assert results[2]["id"] == "hot_low"

    def test_load_all_by_tier_no_prefs(self, loader):
        results = loader.load_all_by_tier("hot")

        assert results == []

    def test_load_all_by_tier_context_filter_multiple_tags(self, storage, loader):
        prefs = [
            make_pref("pref_py", "project.python.linter", tier="hot"),
            make_pref("pref_js", "project.javascript.bundler", tier="hot"),
            make_pref("pref_go", "project.go.formatter", tier="hot"),
            make_pref("pref_gen", "general.code_quality", tier="hot"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        results = loader.load_all_by_tier("hot", context_tags=["python", "javascript"])

        result_ids = {r["id"] for r in results}
        assert "pref_py" in result_ids
        assert "pref_js" in result_ids
        assert "pref_gen" in result_ids
        assert "pref_go" not in result_ids

    def test_load_all_by_tier_context_no_matches(self, storage, loader):
        prefs = [
            make_pref("pref_py", "project.python.linter", tier="hot"),
            make_pref("pref_js", "project.javascript.bundler", tier="hot"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        results = loader.load_all_by_tier("hot", context_tags=["rust"])

        assert results == []

    def test_load_all_by_tier_includes_required_fields(self, storage, loader):
        pref = make_pref("test_pref", "test.path", confidence=0.75, tier="hot", value="test_value")
        pref.pinned = True
        storage.preferences.save_preference(pref)

        results = loader.load_all_by_tier("hot")

        assert len(results) == 1
        result = results[0]
        assert result["id"] == "test_pref"
        assert result["path"] == "test.path"
        assert result["value"] == "test_value"
        assert result["confidence"] == 0.75
        assert result["tier"] == "hot"
        assert result["pinned"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
