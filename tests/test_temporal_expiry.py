"""Tests for temporal expiry and tag validation. Run: pytest tests/test_temporal_expiry.py -v"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.tag_validation import validate_tag, TAG_REGEX
from scripts.storage import PreferenceStorageManager
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
def mgr(tmp_path):
    return PreferenceStorageManager(str(tmp_path))


class TestTagValidation:
    def test_valid_alphanumeric(self):
        assert validate_tag("release-10.5") is True

    def test_valid_simple(self):
        assert validate_tag("shipped") is True

    def test_valid_dotted(self):
        assert validate_tag("v10.5.3") is True

    def test_reject_underscore(self):
        assert validate_tag("foo_bar") is False

    def test_reject_percent(self):
        assert validate_tag("%prod%") is False

    def test_reject_space(self):
        assert validate_tag("foo bar") is False

    def test_reject_empty(self):
        assert validate_tag("") is False

    def test_reject_starts_with_hyphen(self):
        assert validate_tag("-invalid") is False

    def test_reject_starts_with_dot(self):
        assert validate_tag(".hidden") is False


class TestArchiveExpired:
    def test_archives_past_expires_at(self, mgr):
        mgr.knowledge.save_entry(make_entry(
            id="know_expired", expires_at="2020-01-01"
        ))
        mgr.knowledge.save_entry(make_entry(
            id="know_future", expires_at="2099-12-31"
        ))
        mgr.knowledge.save_entry(make_entry(id="know_no_expiry"))
        archived_count = mgr.knowledge.archive_expired()
        assert archived_count == 1
        assert mgr.knowledge.get_entry("know_expired").archived is True
        assert mgr.knowledge.get_entry("know_future").archived is False
        assert mgr.knowledge.get_entry("know_no_expiry").archived is False

    def test_skips_already_archived(self, mgr):
        mgr.knowledge.save_entry(make_entry(
            id="know_old", expires_at="2020-01-01", archived=True
        ))
        archived_count = mgr.knowledge.archive_expired()
        assert archived_count == 0
