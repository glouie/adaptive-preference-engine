import unittest

from scripts.models import LearningData, Preference


class ModelSchemaTests(unittest.TestCase):
    def test_learning_data_persists_significance_metadata(self):
        pref = Preference(
            id="pref_test",
            path="communication.output_format.bullets",
            parent_id=None,
            name="bullets",
            type="variant",
            value="bullets",
            learning=LearningData(
                use_count=3,
                significance_score=0.97,
                p_value=0.03,
                effect_size=0.61,
                autocorrelation=0.12,
                n_signals=9,
                fdr_significant=True,
            ),
        )

        restored = Preference.from_dict(pref.to_dict())

        self.assertEqual(restored.learning.significance_score, 0.97)
        self.assertEqual(restored.learning.p_value, 0.03)
        self.assertEqual(restored.learning.effect_size, 0.61)
        self.assertEqual(restored.learning.autocorrelation, 0.12)
        self.assertEqual(restored.learning.n_signals, 9)
        self.assertTrue(restored.learning.fdr_significant)


if __name__ == "__main__":
    unittest.main()
