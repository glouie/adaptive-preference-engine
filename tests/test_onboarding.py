import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.models import Preference, generate_id
from scripts.onboarding import OnboardingState, OnboardingSystem


class OnboardingStateTests(unittest.TestCase):
    def test_state_persists_progress_and_demo_ids(self):
        with TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            state = OnboardingState(state_file)

            self.assertEqual(state.get_current_step(), 0)
            self.assertFalse(state.is_complete())

            state.advance_step()
            state.set_demo_preference("pref_demo")
            state.set_demo_signal("sig_demo")

            reloaded = OnboardingState(state_file)
            self.assertEqual(reloaded.get_current_step(), 1)
            self.assertEqual(reloaded.state["demo_preference_id"], "pref_demo")
            self.assertEqual(reloaded.state["demo_signal_id"], "sig_demo")


class OnboardingSystemTests(unittest.TestCase):
    def _quietly(self, func, *args, **kwargs):
        with redirect_stdout(io.StringIO()):
            return func(*args, **kwargs)

    def test_state_completion_prevents_repeat_even_without_marker(self):
        with TemporaryDirectory() as tmpdir:
            onboarding = OnboardingSystem(tmpdir)
            onboarding.state.mark_complete()
            self.assertFalse(onboarding.is_first_run())

    def test_first_run_detection_and_completion(self):
        with TemporaryDirectory() as tmpdir:
            onboarding = OnboardingSystem(tmpdir)
            self.assertTrue(onboarding.is_first_run())
            onboarding.mark_complete()
            self.assertFalse(onboarding.is_first_run())

    def test_quit_returns_without_marking_complete(self):
        with TemporaryDirectory() as tmpdir:
            onboarding = OnboardingSystem(tmpdir)
            with patch("builtins.input", side_effect=["q", "y"]):
                completed = self._quietly(onboarding.run_tutorial, skip_demo=True)

            self.assertFalse(completed)
            self.assertTrue(onboarding.is_first_run())

    def test_demo_preference_and_correction_are_hermetic(self):
        with TemporaryDirectory() as tmpdir:
            onboarding = OnboardingSystem(tmpdir)

            preferred_pref_id = self._quietly(onboarding._create_demo_preference)
            signal_id = self._quietly(onboarding._record_demo_correction)

            preferred_pref = onboarding.storage.preferences.get_preference(preferred_pref_id)
            self.assertIsNotNone(preferred_pref)
            self.assertEqual(preferred_pref.path, "communication.output_format.bullets")
            self.assertEqual(preferred_pref.learning.use_count, 1)
            self.assertGreater(preferred_pref.confidence, 0.5)
            self.assertIsNotNone(onboarding.storage.signals.get_signal(signal_id))

            self.assertTrue((Path(tmpdir) / "metrics.jsonl").exists())
            self.assertTrue((Path(tmpdir) / "habits" / "usage.jsonl").exists())
            self.assertEqual(len(onboarding.state.get_managed_preference_ids()), 3)
            self.assertEqual(len(onboarding.state.get_managed_signal_ids()), 0)

    def test_weekly_digest_uses_semantic_content(self):
        with TemporaryDirectory() as tmpdir:
            onboarding = OnboardingSystem(tmpdir)
            self._quietly(onboarding._create_demo_preference)
            digest = onboarding.generate_weekly_digest()

            self.assertIn("WEEKLY LEARNING DIGEST", digest)
            self.assertIn("THIS WEEK'S ACTIVITY", digest)
            self.assertIn("LOCKED IN", digest)
            self.assertIn("EMERGING", digest)

    def test_all_steps_have_required_fields(self):
        with TemporaryDirectory() as tmpdir:
            onboarding = OnboardingSystem(tmpdir)
            for index, step in enumerate(onboarding.STEPS, start=1):
                self.assertEqual(step["number"], index)
                self.assertIn("title", step)
                self.assertIn("duration", step)
                self.assertGreater(len(step["content"]), 100)

    def test_modify_setup_replaces_only_onboarding_managed_preferences(self):
        with TemporaryDirectory() as tmpdir:
            onboarding = OnboardingSystem(tmpdir)
            self._quietly(onboarding._apply_starter_choice, None)
            self._quietly(onboarding._record_and_track_demo_signal)

            user_pref = Preference(
                id=generate_id("pref"),
                path="user.custom.preference",
                parent_id=None,
                name="custom",
                type="variant",
                value="enabled",
            )
            onboarding.storage.preferences.save_preference(user_pref)

            with patch("builtins.input", side_effect=["1", "1", "n", "5"]):
                completed = self._quietly(onboarding.run_modify_setup)

            self.assertTrue(completed)
            self.assertEqual(onboarding.state.get_starter_profile(), "DEVELOPER")
            self.assertEqual(len(onboarding.state.get_managed_preference_ids()), 5)
            self.assertTrue(onboarding.storage.preferences.get_preference(user_pref.id))
            self.assertFalse(onboarding.has_demo_signal())
            self.assertFalse(onboarding.has_demo_preference())

    def test_modify_setup_can_recreate_demo_signal(self):
        with TemporaryDirectory() as tmpdir:
            onboarding = OnboardingSystem(tmpdir)
            self._quietly(onboarding._apply_starter_choice, None)
            first_signal_id = self._quietly(onboarding._record_and_track_demo_signal)

            with patch("builtins.input", side_effect=["2", "5"]):
                completed = self._quietly(onboarding.run_modify_setup)

            self.assertTrue(completed)
            new_signal_ids = onboarding.state.get_managed_signal_ids()
            self.assertEqual(len(new_signal_ids), 1)
            self.assertNotEqual(new_signal_ids[0], first_signal_id)
            self.assertIsNone(onboarding.storage.signals.get_signal(first_signal_id))

    def test_modify_setup_can_create_demo_bundle_before_recreating_signal(self):
        with TemporaryDirectory() as tmpdir:
            onboarding = OnboardingSystem(tmpdir)
            self._quietly(onboarding._apply_starter_choice, "DEVELOPER")

            with patch("builtins.input", side_effect=["2", "y", "5"]):
                completed = self._quietly(onboarding.run_modify_setup)

            self.assertTrue(completed)
            self.assertTrue(onboarding.has_demo_preference())
            self.assertTrue(onboarding.has_demo_signal())
            self.assertEqual(onboarding.state.get_starter_profile(), "DEVELOPER")
            self.assertEqual(len(onboarding.state.get_starter_preference_ids()), 5)
            self.assertEqual(len(onboarding.state.get_demo_preference_ids()), 3)

    def test_recreating_demo_signal_repairs_partial_demo_bundle(self):
        with TemporaryDirectory() as tmpdir:
            onboarding = OnboardingSystem(tmpdir)
            bullets_pref_id = self._quietly(onboarding._create_demo_preference)
            tables_pref = next(
                pref for pref in onboarding._get_demo_preferences()
                if pref.path == "communication.output_format.tables"
            )

            onboarding.storage.delete_preference(tables_pref.id)
            onboarding._remove_managed_preference_id(tables_pref.id)

            self.assertFalse(onboarding.has_demo_preference())

            signal_id = self._quietly(onboarding._record_and_track_demo_signal)

            self.assertNotEqual(onboarding.state.state["demo_preference_id"], tables_pref.id)
            self.assertNotEqual(onboarding.state.state["demo_preference_id"], bullets_pref_id)
            self.assertTrue(onboarding.has_demo_preference())
            self.assertTrue(onboarding.storage.signals.get_signal(signal_id))
            self.assertEqual(len(onboarding.state.get_demo_preference_ids()), 3)

    def test_reset_all_setup_removes_only_onboarding_managed_artifacts(self):
        with TemporaryDirectory() as tmpdir:
            onboarding = OnboardingSystem(tmpdir)
            self._quietly(onboarding._apply_starter_choice, None)
            self._quietly(onboarding._record_and_track_demo_signal)
            onboarding.mark_complete()

            user_pref = Preference(
                id=generate_id("pref"),
                path="user.custom.preference",
                parent_id=None,
                name="custom",
                type="variant",
                value="enabled",
            )
            onboarding.storage.preferences.save_preference(user_pref)

            managed_pref_ids = onboarding.state.get_managed_preference_ids()
            managed_signal_ids = onboarding.state.get_managed_signal_ids()
            self._quietly(onboarding.reset_all_setup)

            self.assertTrue(onboarding.is_first_run())
            self.assertFalse(onboarding.complete_file.exists())
            self.assertEqual(onboarding.state.get_managed_preference_ids(), [])
            self.assertEqual(onboarding.state.get_managed_signal_ids(), [])
            for pref_id in managed_pref_ids:
                self.assertIsNone(onboarding.storage.preferences.get_preference(pref_id))
            for signal_id in managed_signal_ids:
                self.assertIsNone(onboarding.storage.signals.get_signal(signal_id))
            self.assertIsNotNone(onboarding.storage.preferences.get_preference(user_pref.id))

    def test_setup_summary_shows_split_starter_and_demo_counts(self):
        with TemporaryDirectory() as tmpdir:
            onboarding = OnboardingSystem(tmpdir)
            self._quietly(onboarding._apply_starter_choice, "DEVELOPER")
            self._quietly(onboarding._record_and_track_demo_signal)

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                onboarding.show_setup_summary()

            summary = buffer.getvalue()
            self.assertIn("Starter profile: DEVELOPER", summary)
            self.assertIn("Starter preferences: 5", summary)
            self.assertIn("Demo preferences: 3", summary)
            self.assertIn("Demo correction recorded: yes", summary)


if __name__ == "__main__":
    unittest.main()
