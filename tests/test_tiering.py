"""Tests for TieringEngine preference classification. Run: pytest tests/test_tiering.py -v"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adaptive_preference_engine.storage import PreferenceStorageManager
from adaptive_preference_engine.services.tiering import TieringEngine
from adaptive_preference_engine.models import Preference, LearningData


def make_pref(id, path, confidence=0.5, use_count=0, tier="hot", pinned=False, last_signal_at=None):
    p = Preference(
        id=id,
        path=path,
        parent_id=None,
        name=path.split(".")[-1],
        type="property",
        value="test",
        confidence=confidence,
        tier=tier,
        pinned=pinned,
        last_signal_at=last_signal_at,
    )
    p.learning.use_count = use_count
    return p


@pytest.fixture
def storage(tmp_path):
    return PreferenceStorageManager(str(tmp_path))


@pytest.fixture
def engine(storage):
    return TieringEngine(storage)


class TestTieringClassification:
    def test_classify_hot_by_confidence(self, engine):
        tier = engine.classify(confidence=0.70, uses=0, pinned=False, last_signal_at=None)
        assert tier == "hot"

    def test_classify_hot_by_uses(self, engine):
        tier = engine.classify(confidence=0.50, uses=8, pinned=False, last_signal_at=None)
        assert tier == "hot"

    def test_classify_warm(self, engine):
        tier = engine.classify(confidence=0.50, uses=3, pinned=False, last_signal_at=None)
        assert tier == "warm"

    def test_classify_cold_below_threshold(self, engine):
        tier = engine.classify(confidence=0.40, uses=0, pinned=False, last_signal_at=None)
        assert tier == "cold"

    def test_classify_cold_by_inactivity(self, engine):
        last_signal = (datetime.now() - timedelta(days=35)).isoformat()
        tier = engine.classify(confidence=0.60, uses=3, pinned=False, last_signal_at=last_signal)
        assert tier == "cold"

    def test_classify_pinned_always_hot(self, engine):
        tier = engine.classify(confidence=0.10, uses=0, pinned=True, last_signal_at=None)
        assert tier == "hot"

    def test_classify_hot_demoted_by_inactivity(self, engine):
        last_signal = (datetime.now() - timedelta(days=20)).isoformat()
        tier = engine.classify(confidence=0.80, uses=0, pinned=False, last_signal_at=last_signal)
        assert tier == "warm"

    def test_classify_high_uses_demoted_by_inactivity(self, engine):
        last_signal = (datetime.now() - timedelta(days=16)).isoformat()
        tier = engine.classify(confidence=0.50, uses=10, pinned=False, last_signal_at=last_signal)
        assert tier == "warm"


class TestTieringMutations:
    def test_promote(self, storage, engine):
        pref = make_pref("pref_1", "test.cold", tier="cold")
        storage.preferences.save_preference(pref)

        result = engine.promote("pref_1")
        assert result is True

        updated = storage.preferences.get_preference("pref_1")
        assert updated.tier == "warm"

    def test_promote_warm_to_hot(self, storage, engine):
        pref = make_pref("pref_2", "test.warm", tier="warm")
        storage.preferences.save_preference(pref)

        result = engine.promote("pref_2")
        assert result is True

        updated = storage.preferences.get_preference("pref_2")
        assert updated.tier == "hot"

    def test_promote_hot_fails(self, storage, engine):
        pref = make_pref("pref_3", "test.hot", tier="hot")
        storage.preferences.save_preference(pref)

        result = engine.promote("pref_3")
        assert result is False

        updated = storage.preferences.get_preference("pref_3")
        assert updated.tier == "hot"

    def test_demote(self, storage, engine):
        pref = make_pref("pref_4", "test.hot", tier="hot")
        storage.preferences.save_preference(pref)

        result = engine.demote("pref_4")
        assert result is True

        updated = storage.preferences.get_preference("pref_4")
        assert updated.tier == "warm"

    def test_demote_warm_to_cold(self, storage, engine):
        pref = make_pref("pref_5", "test.warm", tier="warm")
        storage.preferences.save_preference(pref)

        result = engine.demote("pref_5")
        assert result is True

        updated = storage.preferences.get_preference("pref_5")
        assert updated.tier == "cold"

    def test_demote_cold_fails(self, storage, engine):
        pref = make_pref("pref_6", "test.cold", tier="cold")
        storage.preferences.save_preference(pref)

        result = engine.demote("pref_6")
        assert result is False

        updated = storage.preferences.get_preference("pref_6")
        assert updated.tier == "cold"

    def test_promote_nonexistent_fails(self, engine):
        result = engine.promote("nonexistent")
        assert result is False

    def test_demote_nonexistent_fails(self, engine):
        result = engine.demote("nonexistent")
        assert result is False


class TestTieringPinning:
    def test_pin_unpin(self, storage, engine):
        pref = make_pref("pref_7", "test.pin", confidence=0.40, tier="cold")
        storage.preferences.save_preference(pref)

        result = engine.pin("pref_7")
        assert result is True

        updated = storage.preferences.get_preference("pref_7")
        assert updated.pinned is True
        assert updated.tier == "hot"

        result = engine.unpin("pref_7")
        assert result is True

        updated = storage.preferences.get_preference("pref_7")
        assert updated.pinned is False
        assert updated.tier == "cold"

    def test_pin_already_pinned_hot_fails(self, storage, engine):
        pref = make_pref("pref_8", "test.already_pinned", confidence=0.50, tier="hot", pinned=True)
        storage.preferences.save_preference(pref)

        result = engine.pin("pref_8")
        assert result is False

    def test_pin_cold_to_hot(self, storage, engine):
        pref = make_pref("pref_9", "test.cold_pin", confidence=0.30, tier="cold", pinned=False)
        storage.preferences.save_preference(pref)

        result = engine.pin("pref_9")
        assert result is True

        updated = storage.preferences.get_preference("pref_9")
        assert updated.tier == "hot"
        assert updated.pinned is True

    def test_unpin_not_pinned_fails(self, storage, engine):
        pref = make_pref("pref_10", "test.not_pinned", tier="hot", pinned=False)
        storage.preferences.save_preference(pref)

        result = engine.unpin("pref_10")
        assert result is False

    def test_pin_nonexistent_fails(self, engine):
        result = engine.pin("nonexistent")
        assert result is False

    def test_unpin_nonexistent_fails(self, engine):
        result = engine.unpin("nonexistent")
        assert result is False


class TestTieringBulkOperations:
    def test_backfill_assigns_correct_tiers(self, storage, engine):
        prefs = [
            make_pref("pref_a", "test.a", confidence=0.80, use_count=0),
            make_pref("pref_b", "test.b", confidence=0.50, use_count=3),
            make_pref("pref_c", "test.c", confidence=0.30, use_count=0),
            make_pref("pref_d", "test.d", confidence=0.70, use_count=0),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        result = engine.backfill()

        pref_a = storage.preferences.get_preference("pref_a")
        pref_b = storage.preferences.get_preference("pref_b")
        pref_c = storage.preferences.get_preference("pref_c")
        pref_d = storage.preferences.get_preference("pref_d")

        assert pref_a.tier == "hot"
        assert pref_b.tier == "warm"
        assert pref_c.tier == "cold"
        assert pref_d.tier == "hot"

        assert "pref_a" in result["unchanged"]
        assert "pref_b" in result["demoted"]
        assert "pref_c" in result["demoted"]
        assert "pref_d" in result["unchanged"]

    def test_recalculate_changes_tiers(self, storage, engine):
        prefs = [
            make_pref("pref_x", "test.x", confidence=0.80, tier="hot"),
            make_pref("pref_y", "test.y", confidence=0.50, use_count=3, tier="warm"),
            make_pref("pref_z", "test.z", confidence=0.30, tier="cold"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        pref_x = storage.preferences.get_preference("pref_x")
        pref_x.confidence = 0.40
        storage.preferences.save_preference(pref_x)

        pref_y = storage.preferences.get_preference("pref_y")
        pref_y.learning.use_count = 10
        storage.preferences.save_preference(pref_y)

        result = engine.recalculate()

        assert "pref_x" in result["demoted"]
        assert "pref_y" in result["promoted"]
        assert "pref_z" in result["unchanged"]

        updated_x = storage.preferences.get_preference("pref_x")
        updated_y = storage.preferences.get_preference("pref_y")
        updated_z = storage.preferences.get_preference("pref_z")

        assert updated_x.tier == "cold"
        assert updated_y.tier == "hot"
        assert updated_z.tier == "cold"

    def test_recalculate_with_inactivity(self, storage, engine):
        old_signal = (datetime.now() - timedelta(days=35)).isoformat()
        pref = make_pref("pref_old", "test.old", confidence=0.70, tier="hot", last_signal_at=old_signal)
        storage.preferences.save_preference(pref)

        result = engine.recalculate()

        assert "pref_old" in result["demoted"]
        updated = storage.preferences.get_preference("pref_old")
        assert updated.tier == "cold"


class TestTieringSummary:
    def test_get_tier_summary(self, storage, engine):
        prefs = [
            make_pref("hot_1", "test.hot1", tier="hot"),
            make_pref("hot_2", "test.hot2", tier="hot"),
            make_pref("warm_1", "test.warm1", tier="warm"),
            make_pref("warm_2", "test.warm2", tier="warm"),
            make_pref("warm_3", "test.warm3", tier="warm"),
            make_pref("cold_1", "test.cold1", tier="cold"),
        ]

        for p in prefs:
            storage.preferences.save_preference(p)

        summary = engine.get_tier_summary()

        assert summary["hot"] == 2
        assert summary["warm"] == 3
        assert summary["cold"] == 1

    def test_get_tier_summary_empty(self, engine):
        summary = engine.get_tier_summary()

        assert summary["hot"] == 0
        assert summary["warm"] == 0
        assert summary["cold"] == 0


class TestTieringEdgeCases:
    def test_classify_invalid_last_signal_format(self, engine):
        tier = engine.classify(
            confidence=0.60,
            uses=5,
            pinned=False,
            last_signal_at="invalid-date"
        )
        assert tier == "warm"

    def test_classify_exact_threshold_confidence(self, engine):
        tier = engine.classify(confidence=0.45, uses=0, pinned=False, last_signal_at=None)
        assert tier == "warm"

    def test_classify_exact_threshold_uses(self, engine):
        tier = engine.classify(confidence=0.50, uses=8, pinned=False, last_signal_at=None)
        assert tier == "hot"

    def test_classify_14_day_inactivity_boundary(self, engine):
        last_signal = (datetime.now() - timedelta(days=14)).isoformat()
        tier = engine.classify(confidence=0.80, uses=0, pinned=False, last_signal_at=last_signal)
        assert tier == "warm"

    def test_classify_30_day_inactivity_boundary(self, engine):
        last_signal = (datetime.now() - timedelta(days=30)).isoformat()
        tier = engine.classify(confidence=0.60, uses=5, pinned=False, last_signal_at=last_signal)
        assert tier == "cold"

    def test_backfill_preserves_pinned_state(self, storage, engine):
        pref = make_pref("pref_pinned", "test.pinned", confidence=0.20, tier="cold", pinned=True)
        delattr(pref, 'tier')
        storage.preferences.save_preference(pref)

        engine.backfill()

        updated = storage.preferences.get_preference("pref_pinned")
        assert updated.tier == "hot"
        assert updated.pinned is True

    def test_recalculate_respects_pinned(self, storage, engine):
        pref = make_pref("pref_pin_recalc", "test.pin_recalc", confidence=0.20, tier="hot", pinned=True)
        storage.preferences.save_preference(pref)

        pref.confidence = 0.10
        storage.preferences.save_preference(pref)

        result = engine.recalculate()

        assert "pref_pin_recalc" in result["unchanged"]
        updated = storage.preferences.get_preference("pref_pin_recalc")
        assert updated.tier == "hot"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
