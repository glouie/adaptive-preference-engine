import io
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from tempfile import TemporaryDirectory

from scripts.cli import AdaptivePreferenceCLI
from scripts.models import Preference, generate_id


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


if __name__ == "__main__":
    unittest.main()
