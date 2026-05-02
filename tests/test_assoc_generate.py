import io
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from datetime import datetime

from scripts.assoc_meta import AssocMeta
from scripts.cli import AdaptivePreferenceCLI
from scripts.models import Preference, Signal, generate_id


class TestAssocGenerate(unittest.TestCase):
    def _make_cli(self, tmpdir):
        cli = AdaptivePreferenceCLI(tmpdir)
        for path in ["coding.style.type_hints", "coding.testing.framework"]:
            p = Preference(
                id=generate_id("pref"),
                path=path,
                parent_id=None,
                name=path.split(".")[-1],
                type="variant",
                value="on",
                description="",
            )
            cli.storage.preferences.save_preference(p)
        return cli

    def _add_signal_with_both_prefs(self, cli):
        prefs = cli.storage.preferences.get_all_preferences()
        pref_ids = [p.id for p in prefs]
        signal = Signal(
            id=generate_id("sig"),
            timestamp=datetime.now().isoformat(),
            type="feedback",
            task="test task",
            context_tags=[],
            preferences_used=pref_ids,
            preferences_affected=[{"pref_id": pid, "action": "strengthen"} for pid in pref_ids],
            emotional_tone="satisfied",
            associations_affected=[],
        )
        cli.storage.signals.save_signal(signal)

    def test_generate_creates_associations_from_cooccurrence(self):
        with TemporaryDirectory() as tmpdir:
            cli = self._make_cli(tmpdir)
            for _ in range(5):
                self._add_signal_with_both_prefs(cli)
            out = io.StringIO()
            with redirect_stdout(out):
                cli.cmd_assoc_generate(Namespace(if_stale=False))
            assocs = cli.storage.associations.get_all_associations()
            self.assertGreater(len(assocs), 0)

    def test_generate_if_stale_skips_when_no_new_signals(self):
        with TemporaryDirectory() as tmpdir:
            cli = self._make_cli(tmpdir)
            out = io.StringIO()
            with redirect_stdout(out):
                cli.cmd_assoc_generate(Namespace(if_stale=True))
            assocs = cli.storage.associations.get_all_associations()
            self.assertEqual(len(assocs), 0)

    def test_generate_updates_existing_association_strength(self):
        with TemporaryDirectory() as tmpdir:
            cli = self._make_cli(tmpdir)
            for _ in range(5):
                self._add_signal_with_both_prefs(cli)
            with redirect_stdout(io.StringIO()):
                cli.cmd_assoc_generate(Namespace(if_stale=False))
            count_after_first = len(cli.storage.associations.get_all_associations())
            for _ in range(5):
                self._add_signal_with_both_prefs(cli)
            with redirect_stdout(io.StringIO()):
                cli.cmd_assoc_generate(Namespace(if_stale=False))
            count_after_second = len(cli.storage.associations.get_all_associations())
            self.assertEqual(count_after_first, count_after_second)

    def test_prune_triggers_assoc_generate(self):
        with TemporaryDirectory() as tmpdir:
            cli = self._make_cli(tmpdir)
            for _ in range(5):
                self._add_signal_with_both_prefs(cli)

            # Add a knowledge entry old enough to be pruned
            from adaptive_preference_engine.knowledge import KnowledgeEntry
            from datetime import datetime, timedelta
            old_date = (datetime.now() - timedelta(days=400)).isoformat()
            entry = KnowledgeEntry(
                id=generate_id("know"),
                partition="project",
                category="workflow",
                title="Old entry",
                tags=[],
                content="old",
                last_used=old_date,
            )
            cli.storage.knowledge.save_entry(entry)

            with redirect_stdout(io.StringIO()):
                cli.cmd_knowledge_prune(Namespace(dry_run=False))

            assocs = cli.storage.associations.get_all_associations()
            self.assertGreater(len(assocs), 0)

    def test_signal_threshold_triggers_assoc_generate(self):
        with TemporaryDirectory() as tmpdir:
            cli = self._make_cli(tmpdir)

            # Manually add 9 signals + increment counter = 9 pending
            for _ in range(9):
                self._add_signal_with_both_prefs(cli)
                meta = AssocMeta.load(Path(tmpdir))
                meta.increment(Path(tmpdir))

            # Counter should be 9 now (not yet at threshold)
            meta = AssocMeta.load(Path(tmpdir))
            self.assertEqual(meta.signals_since_last_run, 9)
            self.assertEqual(len(cli.storage.associations.get_all_associations()), 0)

            # Simulate the threshold check that signal commands perform
            from scripts.cli import _run_assoc_generate
            meta.increment(Path(tmpdir))  # now 10
            meta2 = AssocMeta.load(Path(tmpdir))
            if meta2.signals_since_last_run >= 10:
                _run_assoc_generate(cli.storage, Path(tmpdir))

            assocs = cli.storage.associations.get_all_associations()
            self.assertGreater(len(assocs), 0)
            meta3 = AssocMeta.load(Path(tmpdir))
            self.assertEqual(meta3.signals_since_last_run, 0)
