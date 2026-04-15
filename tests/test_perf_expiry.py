"""Performance acceptance test for temporal expiry. Run: pytest tests/test_perf_expiry.py -v"""

import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.storage import PreferenceStorageManager, ConfidentialStorageManager
from adaptive_preference_engine.knowledge import KnowledgeEntry
from scripts.models import generate_id


def make_entry(**kwargs) -> KnowledgeEntry:
    defaults = dict(
        id=generate_id("know"), partition="projects/test",
        category="convention", title="Test", tags=["test"],
        content="Content " * 20, confidence=1.0, token_estimate=40,
    )
    defaults.update(kwargs)
    return KnowledgeEntry(**defaults)


class TestExpiryPerformance:
    def test_archive_expired_under_200ms(self, tmp_path):
        """Spec requirement: <200ms for 500 entries per DB, 100 with expires_at."""
        pub_mgr = PreferenceStorageManager(str(tmp_path / "pub"))
        conf_mgr = ConfidentialStorageManager(str(tmp_path / "conf"))

        # Seed public DB: 500 entries, 100 with expires_at (50 past, 50 future)
        for i in range(400):
            pub_mgr.knowledge.save_entry(make_entry(
                id=f"pub_{i}", title=f"Entry {i}",
            ))
        for i in range(50):
            pub_mgr.knowledge.save_entry(make_entry(
                id=f"pub_exp_past_{i}", title=f"Expired {i}",
                expires_at="2020-01-01",
            ))
        for i in range(50):
            pub_mgr.knowledge.save_entry(make_entry(
                id=f"pub_exp_future_{i}", title=f"Future {i}",
                expires_at="2099-12-31",
            ))

        # Seed confidential DB: same distribution
        for i in range(400):
            conf_mgr.knowledge.save_entry(make_entry(
                id=f"conf_{i}", title=f"Conf {i}",
            ))
        for i in range(50):
            conf_mgr.knowledge.save_entry(make_entry(
                id=f"conf_exp_past_{i}", title=f"Conf Expired {i}",
                expires_at="2020-01-01",
            ))
        for i in range(50):
            conf_mgr.knowledge.save_entry(make_entry(
                id=f"conf_exp_future_{i}", title=f"Conf Future {i}",
                expires_at="2099-12-31",
            ))

        # Measure archive pass on both DBs
        start = time.monotonic()
        pub_count = pub_mgr.knowledge.archive_expired()
        conf_count = conf_mgr.knowledge.archive_expired()
        elapsed_ms = (time.monotonic() - start) * 1000

        assert pub_count == 50
        assert conf_count == 50
        assert elapsed_ms < 200, f"Expiry check took {elapsed_ms:.1f}ms (budget: 200ms)"

        pub_mgr.close()
        conf_mgr.close()
