"""Tests for demand loading methods. Run: pytest tests/test_demand_loading.py -v"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adaptive_preference_engine.storage import PreferenceStorageManager
from adaptive_preference_engine.services.loading import PreferenceLoader
from adaptive_preference_engine.services.tiering import TieringEngine
from adaptive_preference_engine.models import Preference, LearningData


def make_pref(id, path, confidence=0.5, use_count=0, tier="hot"):
    p = Preference(
        id=id,
        path=path,
        parent_id=None,
        name=path.split(".")[-1],
        type="property",
        value=f"value for {path}",
        confidence=confidence,
        tier=tier,
    )
    p.learning.use_count = use_count
    return p


@pytest.fixture
def storage(tmp_path):
    return PreferenceStorageManager(str(tmp_path))


@pytest.fixture
def loader(storage):
    return PreferenceLoader(storage)


@pytest.fixture
def engine(storage):
    return TieringEngine(storage)


class TestLoadSinglePref:
    def test_load_single_pref_exists(self, storage, loader):
        pref = make_pref("pref_1", "test.single", confidence=0.7, tier="warm")
        storage.preferences.save_preference(pref)

        result = loader.load_single_pref("test.single")

        assert result is not None
        assert result["id"] == "pref_1"
        assert result["path"] == "test.single"
        assert result["value"] == "value for test.single"
        assert result["confidence"] == 0.7
        assert result["tier"] == "warm"
        assert result["pinned"] is False
        assert result["note"] == "Loaded on demand"

    def test_load_single_pref_not_found(self, loader):
        result = loader.load_single_pref("nonexistent.path")

        assert result is None

    def test_load_single_pref_exact_match(self, storage, loader):
        prefs = [
            make_pref("pref_1", "test.exact", tier="hot"),
            make_pref("pref_2", "test.exact.child", tier="warm"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        result = loader.load_single_pref("test.exact")

        assert result is not None
        assert result["id"] == "pref_1"
        assert result["path"] == "test.exact"

    def test_load_single_pref_cold_tier(self, storage, loader):
        pref = make_pref("cold_pref", "test.cold", confidence=0.3, tier="cold")
        storage.preferences.save_preference(pref)

        result = loader.load_single_pref("test.cold")

        assert result is not None
        assert result["tier"] == "cold"
        assert result["id"] == "cold_pref"

    def test_load_single_pref_pinned(self, storage, loader):
        pref = make_pref("pinned_pref", "test.pinned", tier="hot")
        pref.pinned = True
        storage.preferences.save_preference(pref)

        result = loader.load_single_pref("test.pinned")

        assert result is not None
        assert result["pinned"] is True


class TestLoadByContextTag:
    def test_load_by_context_tag(self, storage, loader):
        prefs = [
            make_pref("py_1", "project.python.linter", tier="warm"),
            make_pref("py_2", "tools.python.formatter", tier="cold"),
            make_pref("js_1", "project.javascript.bundler", tier="hot"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        results = loader.load_by_context_tag("python")

        assert len(results) == 2
        result_ids = {r["id"] for r in results}
        assert "py_1" in result_ids
        assert "py_2" in result_ids
        assert "js_1" not in result_ids

    def test_load_by_context_tag_no_matches(self, storage, loader):
        prefs = [
            make_pref("py_1", "project.python.linter", tier="hot"),
            make_pref("js_1", "project.javascript.bundler", tier="warm"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        results = loader.load_by_context_tag("rust")

        assert results == []

    def test_load_by_context_tag_sorted_by_confidence(self, storage, loader):
        prefs = [
            make_pref("py_low", "project.python.low", confidence=0.4, tier="cold"),
            make_pref("py_high", "project.python.high", confidence=0.9, tier="hot"),
            make_pref("py_mid", "project.python.mid", confidence=0.6, tier="warm"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        results = loader.load_by_context_tag("python")

        assert len(results) == 3
        assert results[0]["id"] == "py_high"
        assert results[1]["id"] == "py_mid"
        assert results[2]["id"] == "py_low"

    def test_load_by_context_tag_all_tiers(self, storage, loader):
        prefs = [
            make_pref("git_hot", "workflow.git.commit", tier="hot"),
            make_pref("git_warm", "workflow.git.rebase", tier="warm"),
            make_pref("git_cold", "workflow.git.stash", tier="cold"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        results = loader.load_by_context_tag("git")

        assert len(results) == 3
        tiers = {r["tier"] for r in results}
        assert tiers == {"hot", "warm", "cold"}

    def test_load_by_context_tag_universal_prefix(self, storage, loader):
        prefs = [
            make_pref("gen_1", "general.code_quality", tier="hot"),
            make_pref("wf_1", "workflow.git.push", tier="warm"),
            make_pref("proj_1", "project.python.linter", tier="cold"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        results = loader.load_by_context_tag("unrelated_tag")

        assert len(results) == 2
        result_ids = {r["id"] for r in results}
        assert "gen_1" in result_ids
        assert "wf_1" in result_ids
        assert "proj_1" not in result_ids

    def test_load_by_context_tag_empty_storage(self, loader):
        results = loader.load_by_context_tag("any_tag")

        assert results == []


class TestGetInventory:
    def test_get_inventory_warm_cold(self, storage, loader):
        prefs = [
            make_pref("hot_1", "test.hot1", tier="hot"),
            make_pref("hot_2", "test.hot2", tier="hot"),
            make_pref("warm_1", "test.warm1", tier="warm"),
            make_pref("warm_2", "test.warm2", tier="warm"),
            make_pref("cold_1", "test.cold1", tier="cold"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        inventory = loader.get_inventory()

        assert "tiers" in inventory
        assert "total_available" in inventory
        assert len(inventory["tiers"]["warm"]) == 2
        assert len(inventory["tiers"]["cold"]) == 1
        assert "hot" not in inventory["tiers"]
        assert inventory["total_available"] == 3
        assert "test.warm1" in inventory["tiers"]["warm"]
        assert "test.warm2" in inventory["tiers"]["warm"]
        assert "test.cold1" in inventory["tiers"]["cold"]

    def test_get_inventory_custom_tiers(self, storage, loader):
        prefs = [
            make_pref("hot_1", "test.hot1", tier="hot"),
            make_pref("warm_1", "test.warm1", tier="warm"),
            make_pref("cold_1", "test.cold1", tier="cold"),
            make_pref("cold_2", "test.cold2", tier="cold"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        inventory = loader.get_inventory(tiers=["cold"])

        assert "tiers" in inventory
        assert len(inventory["tiers"]) == 1
        assert "cold" in inventory["tiers"]
        assert len(inventory["tiers"]["cold"]) == 2
        assert inventory["total_available"] == 2

    def test_get_inventory_empty(self, storage, loader):
        prefs = [
            make_pref("hot_1", "test.hot1", tier="hot"),
            make_pref("hot_2", "test.hot2", tier="hot"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        inventory = loader.get_inventory()

        assert inventory["tiers"]["warm"] == []
        assert inventory["tiers"]["cold"] == []
        assert inventory["total_available"] == 0

    def test_get_inventory_sorted_paths(self, storage, loader):
        prefs = [
            make_pref("w3", "test.warm.zzz", tier="warm"),
            make_pref("w1", "test.warm.aaa", tier="warm"),
            make_pref("w2", "test.warm.mmm", tier="warm"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        inventory = loader.get_inventory()

        warm_paths = inventory["tiers"]["warm"]
        assert warm_paths == ["test.warm.aaa", "test.warm.mmm", "test.warm.zzz"]

    def test_get_inventory_hot_only(self, storage, loader):
        prefs = [
            make_pref("hot_1", "test.hot1", tier="hot"),
            make_pref("hot_2", "test.hot2", tier="hot"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        inventory = loader.get_inventory(tiers=["hot"])

        assert len(inventory["tiers"]["hot"]) == 2
        assert inventory["total_available"] == 2

    def test_get_inventory_multiple_tiers(self, storage, loader):
        prefs = [
            make_pref("hot_1", "test.hot1", tier="hot"),
            make_pref("warm_1", "test.warm1", tier="warm"),
            make_pref("cold_1", "test.cold1", tier="cold"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        inventory = loader.get_inventory(tiers=["hot", "warm"])

        assert "hot" in inventory["tiers"]
        assert "warm" in inventory["tiers"]
        assert "cold" not in inventory["tiers"]
        assert inventory["total_available"] == 2


class TestFullSessionLifecycle:
    def test_full_session_lifecycle(self, storage, loader, engine):
        prefs = [
            make_pref("high_conf", "session.high_confidence", confidence=0.85, use_count=0, tier="hot"),
            make_pref("mid_conf", "session.mid_confidence", confidence=0.55, use_count=3, tier="hot"),
            make_pref("low_conf", "session.low_confidence", confidence=0.35, use_count=0, tier="hot"),
            make_pref("inactive", "session.inactive", confidence=0.70, use_count=5, tier="hot"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        result = engine.backfill()

        assert "high_conf" in result["unchanged"]
        assert "mid_conf" in result["demoted"]
        assert "low_conf" in result["demoted"]
        assert "inactive" in result["unchanged"]

        high_conf = storage.preferences.get_preference("high_conf")
        mid_conf = storage.preferences.get_preference("mid_conf")
        low_conf = storage.preferences.get_preference("low_conf")
        inactive = storage.preferences.get_preference("inactive")

        assert high_conf.tier == "hot"
        assert mid_conf.tier == "warm"
        assert low_conf.tier == "cold"
        assert inactive.tier == "hot"

        hot_only = loader.load_all_by_tier("hot")
        hot_ids = {p["id"] for p in hot_only}
        assert "high_conf" in hot_ids
        assert "inactive" in hot_ids
        assert "mid_conf" not in hot_ids
        assert "low_conf" not in hot_ids

        inventory = loader.get_inventory()
        assert "session.mid_confidence" in inventory["tiers"]["warm"]
        assert "session.low_confidence" in inventory["tiers"]["cold"]

        cold_pref = loader.load_single_pref("session.low_confidence")
        assert cold_pref is not None
        assert cold_pref["tier"] == "cold"
        assert cold_pref["confidence"] == 0.35

        low_conf_obj = storage.preferences.get_preference("low_conf")
        low_conf_obj.learning.use_count += 1
        low_conf_obj.last_signal_at = datetime.now().isoformat()
        storage.preferences.save_preference(low_conf_obj)

        low_conf_obj = storage.preferences.get_preference("low_conf")
        low_conf_obj.confidence = 0.75
        storage.preferences.save_preference(low_conf_obj)

        recalc_result = engine.recalculate()

        assert "low_conf" in recalc_result["promoted"]

        promoted_pref = storage.preferences.get_preference("low_conf")
        assert promoted_pref.tier == "hot"
        assert promoted_pref.confidence == 0.75

        inactive_obj = storage.preferences.get_preference("inactive")
        old_signal = (datetime.now() - timedelta(days=35)).isoformat()
        inactive_obj.last_signal_at = old_signal
        storage.preferences.save_preference(inactive_obj)

        recalc_result2 = engine.recalculate()

        assert "inactive" in recalc_result2["demoted"]

        demoted_inactive = storage.preferences.get_preference("inactive")
        assert demoted_inactive.tier == "cold"

        final_summary = engine.get_tier_summary()
        assert final_summary["hot"] == 2
        assert final_summary["warm"] == 1
        assert final_summary["cold"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
