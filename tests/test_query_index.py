import random
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.models import Preference
from scripts.query_index import IndexedStorageManager, QueryIndex


def generate_test_preferences(count: int) -> list[Preference]:
    categories = ["communication", "coding", "analysis"]
    subcategories = {
        "communication": ["output_format", "tone"],
        "coding": ["style", "comments"],
        "analysis": ["depth", "citations"],
    }
    variants = {
        "output_format": ["bullets", "table", "prose"],
        "tone": ["professional", "casual", "technical"],
        "style": ["concise", "verbose", "balanced"],
        "comments": ["minimal", "moderate", "extensive"],
        "depth": ["summary", "detailed"],
        "citations": ["inline", "footnotes"],
    }

    prefs = []
    for i in range(count):
        category = random.choice(categories)
        subcategory = random.choice(subcategories[category])
        variant = random.choice(variants[subcategory])
        prefs.append(
            Preference(
                id=f"pref_{i}",
                path=f"{category}.{subcategory}.{variant}",
                parent_id=f"{category}_{subcategory}",
                name=variant,
                type=random.choice(["variant", "selector", "property"]),
                value="active",
                confidence=round(random.uniform(0.3, 0.99), 3),
                description=f"Preference {i}",
            )
        )
    return prefs


class QueryIndexTests(unittest.TestCase):
    def test_index_queries_match_scan_results(self):
        with TemporaryDirectory() as tmpdir:
            manager = IndexedStorageManager(tmpdir, use_persisted_index=False)
            prefs = generate_test_preferences(50)
            for pref in prefs:
                manager.save_preference(pref)

            comm_by_index = set(manager.index.find_by_path_prefix("communication"))
            comm_by_scan = {p.id for p in prefs if p.path.startswith("communication")}
            self.assertSetEqual(comm_by_index, comm_by_scan)

            variant_ids = set(manager.index.find_by_type("variant"))
            variant_scan = {p.id for p in prefs if p.type == "variant"}
            self.assertSetEqual(variant_ids, variant_scan)

    def test_incremental_updates_and_removal(self):
        with TemporaryDirectory() as tmpdir:
            manager = IndexedStorageManager(tmpdir, use_persisted_index=False)
            preference = Preference(
                id="test_new",
                path="testing.new.feature",
                parent_id="testing_new",
                name="feature",
                type="variant",
                value="active",
                confidence=0.88,
            )

            manager.save_preference(preference)
            self.assertIsNotNone(manager.index.find_by_id("test_new"))

            self.assertTrue(manager.delete_preference("test_new"))
            self.assertIsNone(manager.index.find_by_id("test_new"))

    def test_persisted_index_uses_same_base_dir(self):
        with TemporaryDirectory() as tmpdir:
            manager = IndexedStorageManager(tmpdir, use_persisted_index=False)
            for pref in generate_test_preferences(25):
                manager.save_preference(pref)

            index_dir = manager.persist_index()
            reloaded = IndexedStorageManager(tmpdir, use_persisted_index=True)

            self.assertTrue(index_dir.startswith(tmpdir))
            self.assertEqual(len(manager.index.id_index), len(reloaded.index.id_index))
            self.assertEqual(
                set(manager.index.path_prefix_index.keys()),
                set(reloaded.index.path_prefix_index.keys()),
            )
            self.assertEqual(reloaded.index.index_dir, Path(tmpdir) / "indexes")

    def test_query_index_requires_explicit_persistence_dir(self):
        index = QueryIndex()
        with self.assertRaises(ValueError):
            index.save()
        self.assertFalse(index.load())

    def test_query_index_can_round_trip_with_explicit_dir(self):
        with TemporaryDirectory() as tmpdir:
            index_dir = Path(tmpdir) / "indexes"
            index = QueryIndex(str(index_dir))
            manager = IndexedStorageManager(tmpdir, use_persisted_index=False)
            for pref in generate_test_preferences(10):
                manager.save_preference(pref)

            index.build(manager)
            saved_dir = index.save()

            reloaded = QueryIndex(str(index_dir))
            self.assertTrue(reloaded.load())
            self.assertEqual(Path(saved_dir), index_dir)
            self.assertEqual(
                set(index.path_prefix_index.keys()),
                set(reloaded.path_prefix_index.keys()),
            )

    def test_query_index_configured_dir_is_reused_after_explicit_save(self):
        with TemporaryDirectory() as tmpdir:
            index_dir = Path(tmpdir) / "custom-indexes"
            manager = IndexedStorageManager(tmpdir, use_persisted_index=False)
            for pref in generate_test_preferences(8):
                manager.save_preference(pref)

            index = QueryIndex()
            index.build(manager)
            first_save_dir = index.save(index_dir)

            reloaded = QueryIndex()
            self.assertTrue(reloaded.load(index_dir))
            second_save_dir = reloaded.save()

            self.assertEqual(Path(first_save_dir), index_dir)
            self.assertEqual(Path(second_save_dir), index_dir)
            self.assertEqual(reloaded.index_dir, index_dir)
            self.assertEqual(
                set(index.type_index.keys()),
                set(reloaded.type_index.keys()),
            )

    def test_indexed_storage_manager_uses_non_default_nested_base_dir_for_indexes(self):
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "state" / "profiles" / "test-user"
            manager = IndexedStorageManager(str(base_dir), use_persisted_index=False)
            for pref in generate_test_preferences(12):
                manager.save_preference(pref)

            persisted_dir = Path(manager.persist_index())
            expected_dir = base_dir / "indexes"
            self.assertEqual(persisted_dir, expected_dir)
            self.assertTrue((expected_dir / "index.json").exists())

            reloaded = IndexedStorageManager(str(base_dir), use_persisted_index=True)
            self.assertEqual(reloaded.index.index_dir, expected_dir)
            self.assertEqual(
                set(manager.index.path_prefix_index.keys()),
                set(reloaded.index.path_prefix_index.keys()),
            )


if __name__ == "__main__":
    unittest.main()
