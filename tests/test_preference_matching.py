"""Tests for preference matching in signal processing.

Validates that corrections matching existing preferences are routed as
confirmations rather than creating new correction signals.
"""
import unittest
from tempfile import TemporaryDirectory

from scripts.models import Preference, generate_id
from scripts.storage import PreferenceStorageManager
from adaptive_preference_engine.services.signals import SignalProcessor, PreferenceMatchResult


class TestPreferenceMatching(unittest.TestCase):
    """Test match_existing_preference logic."""

    def _make_processor(self, tmpdir):
        storage = PreferenceStorageManager(tmpdir)
        return SignalProcessor(storage), storage

    def _save_pref(self, storage, path, value, name=None):
        pref = Preference(
            id=generate_id("pref"),
            path=path,
            parent_id=None,
            name=name or path.split(".")[-1],
            type="property",
            value=value,
            confidence=0.8,
        )
        storage.preferences.save_preference(pref)
        return pref

    def test_no_match_when_no_preferences(self):
        with TemporaryDirectory() as tmpdir:
            proc, _ = self._make_processor(tmpdir)
            result = proc.match_existing_preference("always use worktrees")
            self.assertFalse(result.matched)

    def test_value_keyword_match(self):
        with TemporaryDirectory() as tmpdir:
            proc, storage = self._make_processor(tmpdir)
            self._save_pref(
                storage,
                "git.always_worktree",
                "Always use git worktrees with feature branches, never commit directly to main",
            )
            result = proc.match_existing_preference(
                "always use git worktrees, never push to main"
            )
            self.assertTrue(result.matched)
            self.assertEqual(result.preference.path, "git.always_worktree")

    def test_path_match(self):
        with TemporaryDirectory() as tmpdir:
            proc, storage = self._make_processor(tmpdir)
            self._save_pref(
                storage,
                "workflow.progress_reporting",
                "surface progress after each step",
            )
            result = proc.match_existing_preference(
                "report progress after each workflow step"
            )
            self.assertTrue(result.matched)

    def test_no_match_below_threshold(self):
        with TemporaryDirectory() as tmpdir:
            proc, storage = self._make_processor(tmpdir)
            self._save_pref(
                storage,
                "formatting.git_commits",
                "human-readable with bullet points and outlines",
            )
            result = proc.match_existing_preference(
                "SharePoint file upload must use Playwright browser automation"
            )
            self.assertFalse(result.matched)

    def test_best_match_selected(self):
        with TemporaryDirectory() as tmpdir:
            proc, storage = self._make_processor(tmpdir)
            self._save_pref(
                storage,
                "formatting.comments.brevity",
                "Keep code comments short, 1-2 sentences max",
            )
            self._save_pref(
                storage,
                "workflow.progress_reporting",
                "surface progress after each step, never work silently",
            )
            result = proc.match_existing_preference(
                "keep comments short and brief"
            )
            self.assertTrue(result.matched)
            self.assertEqual(result.preference.path, "formatting.comments.brevity")


class TestConfirmationRouting(unittest.TestCase):
    """Test that matched corrections are routed as confirmations."""

    def _make_processor(self, tmpdir):
        storage = PreferenceStorageManager(tmpdir)
        return SignalProcessor(storage), storage

    def _save_pref(self, storage, path, value):
        pref = Preference(
            id=generate_id("pref"),
            path=path,
            parent_id=None,
            name=path.split(".")[-1],
            type="property",
            value=value,
            confidence=0.7,
        )
        storage.preferences.save_preference(pref)
        return pref

    def test_matched_correction_becomes_feedback(self):
        with TemporaryDirectory() as tmpdir:
            proc, storage = self._make_processor(tmpdir)
            pref = self._save_pref(
                storage,
                "git.always_worktree",
                "Always use git worktrees with feature branches, never commit directly to main",
            )
            signal = proc.process_correction(
                task="git_workflow",
                context_tags=["git"],
                agent_proposed="pushed directly to main",
                user_corrected_to="always use git worktrees, never commit to main",
                user_message="No, use worktrees!",
            )
            # Signal type should be feedback, not correction
            self.assertEqual(signal.type, "feedback")
            # Preference confidence should be boosted
            updated = storage.preferences.get_preference(pref.id)
            self.assertGreater(updated.confidence, 0.7)
            # Match metadata should be in preferences_affected
            self.assertEqual(
                signal.preferences_affected[0]["action"], "confirm_strengthen"
            )

    def test_unmatched_correction_stays_correction(self):
        with TemporaryDirectory() as tmpdir:
            proc, storage = self._make_processor(tmpdir)
            self._save_pref(
                storage,
                "formatting.git_commits",
                "human-readable with bullet points",
            )
            signal = proc.process_correction(
                task="sharepoint_upload",
                context_tags=["sharepoint"],
                agent_proposed="use Graph API to upload",
                user_corrected_to="use Playwright browser automation for SharePoint file uploads",
                user_message="",
            )
            self.assertEqual(signal.type, "correction")

    def test_confidence_capped_at_one(self):
        with TemporaryDirectory() as tmpdir:
            proc, storage = self._make_processor(tmpdir)
            pref = self._save_pref(
                storage,
                "git.always_worktree",
                "Always use git worktrees with feature branches",
            )
            # Set confidence near max
            pref.confidence = 0.98
            storage.preferences.save_preference(pref)

            proc.process_correction(
                task="git_workflow",
                context_tags=["git"],
                agent_proposed="pushed to main",
                user_corrected_to="always use git worktrees, never commit to main",
            )
            updated = storage.preferences.get_preference(pref.id)
            self.assertLessEqual(updated.confidence, 1.0)


class TestTokenizer(unittest.TestCase):
    """Test the tokenizer used for matching."""

    def test_removes_stop_words(self):
        tokens = SignalProcessor._tokenize("the quick brown fox is very fast")
        self.assertNotIn("the", tokens)
        self.assertNotIn("is", tokens)
        self.assertNotIn("very", tokens)
        self.assertIn("quick", tokens)
        self.assertIn("brown", tokens)

    def test_lowercases(self):
        tokens = SignalProcessor._tokenize("Always Use WORKTREES")
        self.assertIn("always", tokens)
        self.assertIn("worktrees", tokens)

    def test_empty_string(self):
        tokens = SignalProcessor._tokenize("")
        self.assertEqual(len(tokens), 0)


if __name__ == "__main__":
    unittest.main()
