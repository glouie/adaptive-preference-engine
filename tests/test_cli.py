import io
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from tempfile import TemporaryDirectory

from scripts.cli import AdaptivePreferenceCLI
from scripts.models import Preference, generate_id
from adaptive_preference_engine.knowledge import KnowledgeEntry


class CLITests(unittest.TestCase):
    def test_create_update_and_delete_preference(self):
        with TemporaryDirectory() as tmpdir:
            cli = AdaptivePreferenceCLI(tmpdir)

            create_args = Namespace(
                path="communication.output_format.bullets",
                parent=None,
                name="bullets",
                type="variant",
                value="bullets",
                description="Bullet output",
            )
            with redirect_stdout(io.StringIO()):
                cli.cmd_create_preference(create_args)
            preferences = cli.storage.preferences.get_all_preferences()
            self.assertEqual(len(preferences), 1)

            pref = preferences[0]
            update_args = Namespace(
                pref_id=pref.id,
                value="tables",
                description="Table output",
                confidence=0.9,
            )
            with redirect_stdout(io.StringIO()):
                cli.cmd_update_preference(update_args)
            updated = cli.storage.preferences.get_preference(pref.id)
            self.assertEqual(updated.value, "tables")
            self.assertEqual(updated.description, "Table output")
            self.assertEqual(updated.confidence, 0.9)

            self.assertTrue(cli.storage.delete_preference(pref.id))
            self.assertIsNone(cli.storage.preferences.get_preference(pref.id))

    def test_signal_correction_prints_learned_preference(self):
        with TemporaryDirectory() as tmpdir:
            cli = AdaptivePreferenceCLI(tmpdir)

            preferred = Preference(
                id=generate_id("pref"),
                path="communication.output_format.bullets",
                parent_id=None,
                name="bullets",
                type="variant",
                value="bullets",
            )
            rejected = Preference(
                id=generate_id("pref"),
                path="communication.output_format.tables",
                parent_id=None,
                name="tables",
                type="variant",
                value="tables",
            )
            cli.storage.preferences.save_preference(preferred)
            cli.storage.preferences.save_preference(rejected)

            args = Namespace(
                task="api_design",
                context=["communication"],
                proposed=rejected.id,
                corrected=preferred.id,
                message="I prefer bullets for this",
            )

            out = io.StringIO()
            with redirect_stdout(out):
                cli.cmd_signal_correction(args)

            rendered = out.getvalue()
            self.assertIn("What I learned", rendered)
            self.assertIn("communication.output_format.bullets", rendered)

    def test_knowledge_expire_with_signal_flag(self):
        with TemporaryDirectory() as tmpdir:
            cli = AdaptivePreferenceCLI(tmpdir)

            # Create entries with signal-based expiry
            entry1 = KnowledgeEntry(
                id=generate_id("know"),
                partition="projects/test",
                category="convention",
                title="Expires on signal",
                tags=["test"],
                content="Should be archived when signal fires",
                confidence=1.0,
                token_estimate=25,
                expires_when_tag="project-complete",
                created_at="2026-01-01T00:00:00",
            )
            entry2 = KnowledgeEntry(
                id=generate_id("know"),
                partition="projects/test",
                category="convention",
                title="No signal yet",
                tags=["test"],
                content="Should not be archived",
                confidence=1.0,
                token_estimate=25,
                expires_when_tag="future-event",
                created_at="2026-01-01T00:00:00",
            )
            cli.storage.knowledge.save_entry(entry1)
            cli.storage.knowledge.save_entry(entry2)

            # Create a signal that matches entry1's expires_when_tag
            cli.storage.signals._conn.execute(
                """INSERT INTO signals (id, type, task, context_tags,
                   emotional_indicators, preferences_used, associations_affected,
                   preferences_affected, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    generate_id("sig"),
                    "feedback",
                    "project",
                    "deploy,project-complete,ops",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "2026-04-01T00:00:00",
                ),
            )
            cli.storage.signals._conn.commit()

            # Run expire with --signal flag
            args = Namespace(quiet=False, signal=True)
            out = io.StringIO()
            with redirect_stdout(out):
                cli.cmd_knowledge_expire(args)

            # Check that entry1 was archived
            result1 = cli.storage.knowledge.get_entry(entry1.id)
            self.assertTrue(result1.archived)

            # Check that entry2 was not archived
            result2 = cli.storage.knowledge.get_entry(entry2.id)
            self.assertFalse(result2.archived)

            # Check output
            rendered = out.getvalue()
            self.assertIn("signal-triggered", rendered)
            self.assertIn("Archived 1 entries", rendered)


if __name__ == "__main__":
    unittest.main()
