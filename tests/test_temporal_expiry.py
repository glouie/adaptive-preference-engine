"""Tests for temporal expiry and tag validation. Run: pytest tests/test_temporal_expiry.py -v"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.tag_validation import validate_tag, TAG_REGEX


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
