"""Tests for config and sync modules. Run: pytest tests/test_sync.py -v"""

import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.config import AdaptiveConfig


class TestAdaptiveConfig:
    def test_default_sync_repo_is_none(self, tmp_path):
        cfg = AdaptiveConfig(tmp_path)
        assert cfg.sync_repo_path is None

    def test_set_and_get_sync_repo_path(self, tmp_path):
        cfg = AdaptiveConfig(tmp_path)
        cfg.sync_repo_path = "/some/path/glouie-assistant/preferences"
        # Re-load from disk to verify persistence
        cfg2 = AdaptiveConfig(tmp_path)
        assert cfg2.sync_repo_path == "/some/path/glouie-assistant/preferences"

    def test_config_file_is_json(self, tmp_path):
        cfg = AdaptiveConfig(tmp_path)
        cfg.sync_repo_path = "/foo/bar"
        raw = json.loads((tmp_path / "config.json").read_text())
        assert raw["sync_repo_path"] == "/foo/bar"
