import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.assoc_meta import AssocMeta


class TestAssocMeta(unittest.TestCase):
    def test_load_missing_file_returns_defaults(self):
        with TemporaryDirectory() as tmpdir:
            meta = AssocMeta.load(Path(tmpdir))
            self.assertIsNone(meta.last_run_at)
            self.assertEqual(meta.signals_since_last_run, 0)

    def test_load_corrupt_file_returns_defaults(self):
        with TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "assoc_meta.json"
            p.write_text("not json")
            meta = AssocMeta.load(Path(tmpdir))
            self.assertIsNone(meta.last_run_at)
            self.assertEqual(meta.signals_since_last_run, 0)

    def test_increment_persists(self):
        with TemporaryDirectory() as tmpdir:
            meta = AssocMeta.load(Path(tmpdir))
            meta.increment(Path(tmpdir))
            meta2 = AssocMeta.load(Path(tmpdir))
            self.assertEqual(meta2.signals_since_last_run, 1)

    def test_reset_writes_timestamp_and_zeroes_count(self):
        with TemporaryDirectory() as tmpdir:
            meta = AssocMeta.load(Path(tmpdir))
            meta.increment(Path(tmpdir))
            meta.reset(Path(tmpdir))
            meta2 = AssocMeta.load(Path(tmpdir))
            self.assertEqual(meta2.signals_since_last_run, 0)
            self.assertIsNotNone(meta2.last_run_at)

    def test_is_stale_false_when_no_new_signals(self):
        with TemporaryDirectory() as tmpdir:
            meta = AssocMeta.load(Path(tmpdir))
            self.assertFalse(meta.is_stale)

    def test_is_stale_true_when_signals_pending(self):
        with TemporaryDirectory() as tmpdir:
            meta = AssocMeta.load(Path(tmpdir))
            meta.increment(Path(tmpdir))
            meta2 = AssocMeta.load(Path(tmpdir))
            self.assertTrue(meta2.is_stale)
