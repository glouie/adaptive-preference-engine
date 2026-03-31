import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.models import Association, ContextStack, Preference, generate_id
from scripts.storage import JSONLStorageReadError, PreferenceStorageManager


class StorageReliabilityTests(unittest.TestCase):
    def test_malformed_jsonl_records_raise_explicit_error(self):
        with TemporaryDirectory() as tmpdir:
            manager = PreferenceStorageManager(tmpdir)
            malformed_file = manager.preferences.filepath
            malformed_file.write_text(
                json.dumps(
                    Preference(
                        id="pref_ok",
                        path="communication.output_format.bullets",
                        parent_id=None,
                        name="bullets",
                        type="variant",
                        value="bullets",
                    ).to_dict()
                )
                + "\n"
                + "{not-json}\n"
            )

            with self.assertRaises(JSONLStorageReadError) as ctx:
                manager.preferences.get_all_preferences()

            self.assertEqual(ctx.exception.filepath, malformed_file)
            self.assertEqual(ctx.exception.errors[0]["line_number"], 2)
            self.assertIn("Expecting property name", ctx.exception.errors[0]["message"])

    def test_skip_invalid_mode_still_records_read_errors(self):
        with TemporaryDirectory() as tmpdir:
            manager = PreferenceStorageManager(tmpdir)
            manager.preferences.filepath.write_text('{"id": "ok"}\n{bad}\n')

            rows = manager.preferences.read_all(skip_invalid=True)

            self.assertEqual(len(rows), 1)
            self.assertEqual(len(manager.preferences.last_read_errors), 1)
            self.assertEqual(manager.preferences.last_read_errors[0]["line_number"], 2)

    def test_delete_preference_removes_associations_and_context_refs(self):
        with TemporaryDirectory() as tmpdir:
            manager = PreferenceStorageManager(tmpdir)
            pref_a = Preference(
                id=generate_id("pref"),
                path="communication.output_format.bullets",
                parent_id=None,
                name="bullets",
                type="variant",
                value="bullets",
            )
            pref_b = Preference(
                id=generate_id("pref"),
                path="communication.output_format.tables",
                parent_id=None,
                name="tables",
                type="variant",
                value="tables",
            )
            assoc = Association(
                id=generate_id("assoc"),
                from_id=pref_a.id,
                to_id=pref_b.id,
                strength_forward=0.8,
                strength_backward=0.4,
                description="format tradeoff",
                context_tags=["communication"],
            )
            context = ContextStack(
                id=generate_id("ctx"),
                name="base",
                scope="base",
                stack_level=0,
                preferences={pref_a.id: {"value": "bullets", "confidence": 0.9, "source": "manual"}},
            )

            manager.preferences.save_preference(pref_a)
            manager.preferences.save_preference(pref_b)
            manager.associations.save_association(assoc)
            manager.contexts.save_context(context)

            self.assertTrue(manager.delete_preference(pref_a.id))

            self.assertIsNone(manager.preferences.get_preference(pref_a.id))
            self.assertEqual(manager.associations.get_associations_for_preference(pref_a.id), [])
            reloaded_context = manager.contexts.get_context(context.id)
            self.assertNotIn(pref_a.id, reloaded_context.preferences)


if __name__ == "__main__":
    unittest.main()
