# tests/test_storage.py
"""Tests for SQLite storage layer. Run from project root: pytest tests/test_storage.py -v"""

import sys
import json
import tempfile
import os
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.storage import PreferenceStorageManager
from scripts.models import (
    Preference, Association, ContextStack, Signal,
    LearningData, AssociationLearning, generate_id
)


@pytest.fixture
def mgr(tmp_path):
    """Fresh storage manager backed by a temp directory."""
    return PreferenceStorageManager(str(tmp_path))


def make_pref(**kwargs) -> Preference:
    defaults = dict(
        id=generate_id("pref"),
        path="communication.output_format.bullets",
        parent_id=None,
        name="bullets",
        type="variant",
        value="active",
        confidence=0.75,
    )
    defaults.update(kwargs)
    return Preference(**defaults)


def make_assoc(**kwargs) -> Association:
    defaults = dict(
        id=generate_id("assoc"),
        from_id="pref_aaa",
        to_id="pref_bbb",
        strength_forward=0.8,
        strength_backward=0.4,
    )
    defaults.update(kwargs)
    return Association(**defaults)


def make_context(**kwargs) -> ContextStack:
    defaults = dict(
        id=generate_id("ctx"),
        name="Test Context",
        scope="base",
        stack_level=0,
    )
    defaults.update(kwargs)
    return ContextStack(**defaults)


def make_signal(**kwargs) -> Signal:
    from datetime import datetime
    defaults = dict(
        id=generate_id("sig"),
        timestamp=datetime.now().isoformat(),
        type="correction",
        task="api_design",
        context_tags=["python"],
        agent_proposed="bullets",
        user_corrected_to="table",
    )
    defaults.update(kwargs)
    return Signal(**defaults)


# ── Preference tests ──────────────────────────────────────────────────────────

class TestPreferenceStorage:
    def test_save_and_retrieve(self, mgr):
        pref = make_pref(id="pref_001", name="bullets")
        mgr.preferences.save_preference(pref)
        result = mgr.preferences.get_preference("pref_001")
        assert result is not None
        assert result.name == "bullets"
        assert result.confidence == 0.75

    def test_learning_data_round_trips(self, mgr):
        pref = make_pref(id="pref_002")
        pref.learning.use_count = 7
        pref.learning.satisfaction_rate = 0.9
        pref.learning.trend = "increasing"
        mgr.preferences.save_preference(pref)
        result = mgr.preferences.get_preference("pref_002")
        assert result.learning.use_count == 7
        assert result.learning.satisfaction_rate == 0.9
        assert result.learning.trend == "increasing"

    def test_update_existing(self, mgr):
        pref = make_pref(id="pref_003", confidence=0.5)
        mgr.preferences.save_preference(pref)
        pref.confidence = 0.9
        mgr.preferences.save_preference(pref)
        result = mgr.preferences.get_preference("pref_003")
        assert result.confidence == 0.9

    def test_get_missing_returns_none(self, mgr):
        assert mgr.preferences.get_preference("does_not_exist") is None

    def test_get_all(self, mgr):
        for i in range(3):
            mgr.preferences.save_preference(make_pref(id=f"pref_bulk_{i}"))
        assert len(mgr.preferences.get_all_preferences()) == 3

    def test_get_by_path_prefix(self, mgr):
        mgr.preferences.save_preference(make_pref(id="p1", path="communication.output_format.bullets"))
        mgr.preferences.save_preference(make_pref(id="p2", path="communication.output_format.table"))
        mgr.preferences.save_preference(make_pref(id="p3", path="coding.language.python"))
        results = mgr.preferences.get_preferences_by_path("communication.output_format")
        assert len(results) == 2
        assert all(p.path.startswith("communication.output_format") for p in results)

    def test_get_by_parent_id(self, mgr):
        mgr.preferences.save_preference(make_pref(id="child_a", parent_id="parent_x"))
        mgr.preferences.save_preference(make_pref(id="child_b", parent_id="parent_x"))
        mgr.preferences.save_preference(make_pref(id="child_c", parent_id="parent_y"))
        results = mgr.preferences.get_preferences_for_parent("parent_x")
        assert len(results) == 2


# ── Association tests ─────────────────────────────────────────────────────────

class TestAssociationStorage:
    def test_save_and_retrieve(self, mgr):
        assoc = make_assoc(id="assoc_001")
        mgr.associations.save_association(assoc)
        result = mgr.associations.get_association("assoc_001")
        assert result is not None
        assert result.strength_forward == 0.8
        assert result.strength_backward == 0.4

    def test_learning_round_trips(self, mgr):
        assoc = make_assoc(id="assoc_002")
        assoc.learning_forward.use_count = 5
        assoc.learning_forward.trend = "strongly_increasing"
        assoc.context_tags = ["python", "api"]
        mgr.associations.save_association(assoc)
        result = mgr.associations.get_association("assoc_002")
        assert result.learning_forward.use_count == 5
        assert result.learning_forward.trend == "strongly_increasing"
        assert result.context_tags == ["python", "api"]

    def test_update_existing(self, mgr):
        assoc = make_assoc(id="assoc_003", strength_forward=0.5)
        mgr.associations.save_association(assoc)
        assoc.strength_forward = 0.95
        mgr.associations.save_association(assoc)
        result = mgr.associations.get_association("assoc_003")
        assert result.strength_forward == 0.95

    def test_get_for_preference_both_directions(self, mgr):
        mgr.associations.save_association(make_assoc(id="a1", from_id="pref_x", to_id="pref_y"))
        mgr.associations.save_association(make_assoc(id="a2", from_id="pref_z", to_id="pref_x"))
        mgr.associations.save_association(make_assoc(id="a3", from_id="pref_y", to_id="pref_z"))
        results = mgr.associations.get_associations_for_preference("pref_x")
        ids = {a.id for a in results}
        assert ids == {"a1", "a2"}

    def test_get_associations_from(self, mgr):
        mgr.associations.save_association(make_assoc(id="a1", from_id="src", to_id="dst1"))
        mgr.associations.save_association(make_assoc(id="a2", from_id="src", to_id="dst2"))
        mgr.associations.save_association(make_assoc(id="a3", from_id="other", to_id="dst1"))
        results = mgr.associations.get_associations_from("src")
        assert len(results) == 2

    def test_get_all(self, mgr):
        for i in range(4):
            mgr.associations.save_association(make_assoc(id=f"bulk_{i}"))
        assert len(mgr.associations.get_all_associations()) == 4


# ── Context tests ─────────────────────────────────────────────────────────────

class TestContextStorage:
    def test_save_and_retrieve(self, mgr):
        ctx = make_context(id="ctx_001", name="Base", scope="base")
        mgr.contexts.save_context(ctx)
        result = mgr.contexts.get_context("ctx_001")
        assert result is not None
        assert result.name == "Base"
        assert result.scope == "base"

    def test_preferences_dict_round_trips(self, mgr):
        ctx = make_context(id="ctx_002")
        ctx.preferences = {"pref_x": {"value": "table", "confidence": 0.9}}
        mgr.contexts.save_context(ctx)
        result = mgr.contexts.get_context("ctx_002")
        assert result.preferences == {"pref_x": {"value": "table", "confidence": 0.9}}

    def test_get_active_contexts_sorted(self, mgr):
        mgr.contexts.save_context(make_context(id="c1", scope="conversation", stack_level=2, active=True))
        mgr.contexts.save_context(make_context(id="c2", scope="base", stack_level=0, active=True))
        mgr.contexts.save_context(make_context(id="c3", scope="project", stack_level=1, active=False))
        results = mgr.contexts.get_active_contexts()
        assert len(results) == 2
        assert results[0].stack_level == 0
        assert results[1].stack_level == 2

    def test_get_by_scope(self, mgr):
        mgr.contexts.save_context(make_context(id="c1", scope="project"))
        mgr.contexts.save_context(make_context(id="c2", scope="project"))
        mgr.contexts.save_context(make_context(id="c3", scope="base"))
        results = mgr.contexts.get_contexts_by_scope("project")
        assert len(results) == 2


# ── Signal tests ──────────────────────────────────────────────────────────────

class TestSignalStorage:
    def test_save_and_retrieve(self, mgr):
        sig = make_signal(id="sig_001")
        mgr.signals.save_signal(sig)
        result = mgr.signals.get_signal("sig_001")
        assert result is not None
        assert result.type == "correction"
        assert result.context_tags == ["python"]

    def test_lists_round_trip(self, mgr):
        sig = make_signal(id="sig_002")
        sig.preferences_used = ["pref_a", "pref_b"]
        sig.emotional_indicators = ["excited", "clear"]
        mgr.signals.save_signal(sig)
        result = mgr.signals.get_signal("sig_002")
        assert result.preferences_used == ["pref_a", "pref_b"]
        assert result.emotional_indicators == ["excited", "clear"]

    def test_get_by_type(self, mgr):
        mgr.signals.save_signal(make_signal(id="s1", type="correction"))
        mgr.signals.save_signal(make_signal(id="s2", type="correction"))
        mgr.signals.save_signal(make_signal(id="s3", type="feedback"))
        results = mgr.signals.get_signals_by_type("correction")
        assert len(results) == 2

    def test_get_recent_signals(self, mgr):
        from datetime import datetime, timedelta
        old_ts = (datetime.now() - timedelta(hours=48)).isoformat()
        recent_ts = datetime.now().isoformat()
        mgr.signals.save_signal(make_signal(id="old", timestamp=old_ts))
        mgr.signals.save_signal(make_signal(id="new", timestamp=recent_ts))
        results = mgr.signals.get_recent_signals(hours=24)
        ids = {s.id for s in results}
        assert "new" in ids
        assert "old" not in ids

    def test_get_signals_for_preference(self, mgr):
        sig = make_signal(id="s1")
        sig.preferences_used = ["pref_target", "pref_other"]
        mgr.signals.save_signal(sig)
        mgr.signals.save_signal(make_signal(id="s2"))  # preferences_used is empty
        results = mgr.signals.get_signals_for_preference("pref_target")
        assert len(results) == 1
        assert results[0].id == "s1"


# ── Manager-level tests ───────────────────────────────────────────────────────

class TestPreferenceStorageManager:
    def test_get_storage_info(self, mgr):
        mgr.preferences.save_preference(make_pref())
        mgr.associations.save_association(make_assoc())
        info = mgr.get_storage_info()
        assert info["preferences_count"] == 1
        assert info["associations_count"] == 1
        assert info["signals_count"] == 0

    def test_backup_creates_copy(self, mgr, tmp_path):
        mgr.preferences.save_preference(make_pref(id="backup_test"))
        backup_path = mgr.backup("test_backup")
        assert Path(backup_path).exists()

    def test_prune_old_signals(self, mgr):
        from datetime import datetime, timedelta
        old_ts = (datetime.now() - timedelta(days=100)).isoformat()
        recent_ts = datetime.now().isoformat()
        mgr.signals.save_signal(make_signal(id="old", timestamp=old_ts))
        mgr.signals.save_signal(make_signal(id="recent", timestamp=recent_ts))
        removed = mgr.prune_old_signals(max_age_days=90)
        assert removed == 1
        assert mgr.signals.get_signal("old") is None
        assert mgr.signals.get_signal("recent") is not None

    def test_reset_clears_all_tables(self, mgr):
        mgr.preferences.save_preference(make_pref())
        mgr.associations.save_association(make_assoc())
        mgr.signals.save_signal(make_signal())
        mgr.reset()
        assert mgr.preferences.get_all_preferences() == []
        assert mgr.associations.get_all_associations() == []
        assert mgr.signals.get_all_signals() == []
