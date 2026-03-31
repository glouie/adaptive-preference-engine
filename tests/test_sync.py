"""Tests for config and sync modules. Run: pytest tests/test_sync.py -v"""

import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.config import AdaptiveConfig
from scripts.storage import PreferenceStorageManager
from scripts.sync import PreferenceSync
from scripts.models import generate_id, Association, ContextStack, Signal, Preference
from datetime import datetime


def _make_pref(id=None):
    return Preference(
        id=id or generate_id("p"),
        path="comm.output.bullets",
        parent_id=None,
        name="bullets",
        type="variant",
    )


def _make_signal(id=None):
    return Signal(
        id=id or generate_id("s"),
        timestamp=datetime.now().isoformat(),
        type="correction",
    )


@pytest.fixture
def src_mgr(tmp_path):
    return PreferenceStorageManager(str(tmp_path / "src"))


@pytest.fixture
def dst_mgr(tmp_path):
    return PreferenceStorageManager(str(tmp_path / "dst"))


class TestPreferenceSyncExportImport:
    def test_export_creates_jsonl_files(self, src_mgr, tmp_path):
        src_mgr.preferences.save_preference(_make_pref(id="p1"))
        src_mgr.signals.save_signal(_make_signal(id="s1"))
        export_dir = tmp_path / "export"
        PreferenceSync.export(src_mgr, export_dir)
        assert (export_dir / "all_preferences.jsonl").exists()
        assert (export_dir / "signals.jsonl").exists()

    def test_export_content_is_valid_jsonl(self, src_mgr, tmp_path):
        src_mgr.preferences.save_preference(_make_pref(id="p_export"))
        export_dir = tmp_path / "export"
        PreferenceSync.export(src_mgr, export_dir)
        lines = (export_dir / "all_preferences.jsonl").read_text().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["id"] == "p_export"

    def test_import_upserts_into_sqlite(self, src_mgr, dst_mgr, tmp_path):
        src_mgr.preferences.save_preference(_make_pref(id="p_import"))
        export_dir = tmp_path / "export"
        PreferenceSync.export(src_mgr, export_dir)
        imported = PreferenceSync.import_from(dst_mgr, export_dir)
        assert imported["preferences"] == 1
        assert dst_mgr.preferences.get_preference("p_import") is not None

    def test_import_is_idempotent(self, src_mgr, dst_mgr, tmp_path):
        src_mgr.preferences.save_preference(_make_pref(id="p_idem"))
        export_dir = tmp_path / "export"
        PreferenceSync.export(src_mgr, export_dir)
        PreferenceSync.import_from(dst_mgr, export_dir)
        PreferenceSync.import_from(dst_mgr, export_dir)
        assert len(dst_mgr.preferences.get_all_preferences()) == 1

    def test_round_trip_preserves_all_tables(self, src_mgr, dst_mgr, tmp_path):
        src_mgr.preferences.save_preference(_make_pref(id="p1"))
        src_mgr.associations.save_association(Association(
            id="a1", from_id="p1", to_id="p2",
            strength_forward=0.8, strength_backward=0.3,
        ))
        src_mgr.contexts.save_context(ContextStack(
            id="c1", name="Base", scope="base", stack_level=0,
        ))
        src_mgr.signals.save_signal(_make_signal(id="s1"))
        export_dir = tmp_path / "export"
        PreferenceSync.export(src_mgr, export_dir)
        counts = PreferenceSync.import_from(dst_mgr, export_dir)
        assert counts == {"preferences": 1, "associations": 1, "contexts": 1, "signals": 1}


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
