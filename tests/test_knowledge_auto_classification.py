"""Test auto-classification fallback for knowledge add command."""

import io
import os
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.cli import AdaptivePreferenceCLI
from scripts.storage import ConfidentialStorageManager


class KnowledgeAutoClassificationTests(unittest.TestCase):
    """Test that knowledge add auto-classifies confidential content."""

    def test_explicit_confidential_flag_routes_to_confidential_db(self):
        """Test that --confidential flag routes to confidential DB."""
        with TemporaryDirectory() as tmpdir:
            # Create separate dirs for public and confidential
            public_dir = os.path.join(tmpdir, "public")
            confidential_dir = os.path.join(tmpdir, "confidential")
            os.makedirs(public_dir)
            os.makedirs(confidential_dir)

            cli = AdaptivePreferenceCLI(public_dir)

            args = Namespace(
                partition="project_context",
                category="note",
                title="Public Title",
                tags=[],
                content="Public content without sensitive data",
                confidence=1.0,
                decay_exempt=False,
                expires_at=None,
                expires_when=None,
                expires_when_tag=None,
                confidential=True,  # Explicit flag
            )

            # Mock ConfidentialStorageManager to use tmpdir
            original_init = ConfidentialStorageManager.__init__
            def mock_init(self, base_dir=None):
                original_init(self, confidential_dir)

            with patch.object(ConfidentialStorageManager, '__init__', mock_init):
                with redirect_stdout(io.StringIO()):
                    cli.cmd_knowledge_add(args)

                # Should be in confidential DB
                confidential_mgr = ConfidentialStorageManager()
                entries = confidential_mgr.knowledge.get_all_entries()
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0].title, "Public Title")

                # Should NOT be in public DB
                public_entries = cli.storage.knowledge.get_all_entries()
                self.assertEqual(len(public_entries), 0)

    def test_auto_classify_cisco_email_routes_to_confidential(self):
        """Test that content with @cisco.com auto-routes to confidential DB."""
        with TemporaryDirectory() as tmpdir:
            # Create separate dirs for public and confidential
            public_dir = os.path.join(tmpdir, "public")
            confidential_dir = os.path.join(tmpdir, "confidential")
            os.makedirs(public_dir)
            os.makedirs(confidential_dir)

            cli = AdaptivePreferenceCLI(public_dir)

            args = Namespace(
                partition="project_context",
                category="note",
                title="Team Contact",
                tags=[],
                content="Contact John at john.doe@cisco.com for details",
                confidence=1.0,
                decay_exempt=False,
                expires_at=None,
                expires_when=None,
                expires_when_tag=None,
                confidential=False,  # No explicit flag
            )

            # Mock ConfidentialStorageManager to use tmpdir
            original_init = ConfidentialStorageManager.__init__
            def mock_init(self, base_dir=None):
                original_init(self, confidential_dir)

            with patch.object(ConfidentialStorageManager, '__init__', mock_init):
                with redirect_stdout(io.StringIO()):
                    cli.cmd_knowledge_add(args)

                # Should be in confidential DB due to auto-classification
                confidential_mgr = ConfidentialStorageManager()
                entries = confidential_mgr.knowledge.get_all_entries()
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0].title, "Team Contact")
                self.assertIn("@cisco.com", entries[0].content)

                # Should NOT be in public DB
                public_entries = cli.storage.knowledge.get_all_entries()
                self.assertEqual(len(public_entries), 0)

    def test_auto_classify_user_path_routes_to_confidential(self):
        """Test that content with /Users/ path auto-routes to confidential DB."""
        with TemporaryDirectory() as tmpdir:
            # Create separate dirs for public and confidential
            public_dir = os.path.join(tmpdir, "public")
            confidential_dir = os.path.join(tmpdir, "confidential")
            os.makedirs(public_dir)
            os.makedirs(confidential_dir)

            cli = AdaptivePreferenceCLI(public_dir)

            args = Namespace(
                partition="project_context",
                category="note",
                title="File Location",
                tags=[],
                content="Config is at /Users/alice/config.yaml",
                confidence=1.0,
                decay_exempt=False,
                expires_at=None,
                expires_when=None,
                expires_when_tag=None,
                confidential=False,  # No explicit flag
            )

            # Mock ConfidentialStorageManager to use tmpdir
            original_init = ConfidentialStorageManager.__init__
            def mock_init(self, base_dir=None):
                original_init(self, confidential_dir)

            with patch.object(ConfidentialStorageManager, '__init__', mock_init):
                with redirect_stdout(io.StringIO()):
                    cli.cmd_knowledge_add(args)

                # Should be in confidential DB due to auto-classification
                confidential_mgr = ConfidentialStorageManager()
                entries = confidential_mgr.knowledge.get_all_entries()
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0].title, "File Location")
                self.assertIn("/Users/", entries[0].content)

                # Should NOT be in public DB
                public_entries = cli.storage.knowledge.get_all_entries()
                self.assertEqual(len(public_entries), 0)

    def test_auto_classify_confidential_title_routes_to_confidential(self):
        """Test that a confidential pattern in title routes to confidential DB."""
        with TemporaryDirectory() as tmpdir:
            # Create separate dirs for public and confidential
            public_dir = os.path.join(tmpdir, "public")
            confidential_dir = os.path.join(tmpdir, "confidential")
            os.makedirs(public_dir)
            os.makedirs(confidential_dir)

            cli = AdaptivePreferenceCLI(public_dir)

            args = Namespace(
                partition="project_context",
                category="note",
                title="cd.splunkdev.com deployment notes",
                tags=[],
                content="Standard deployment steps",
                confidence=1.0,
                decay_exempt=False,
                expires_at=None,
                expires_when=None,
                expires_when_tag=None,
                confidential=False,  # No explicit flag
            )

            # Mock ConfidentialStorageManager to use tmpdir
            original_init = ConfidentialStorageManager.__init__
            def mock_init(self, base_dir=None):
                original_init(self, confidential_dir)

            with patch.object(ConfidentialStorageManager, '__init__', mock_init):
                with redirect_stdout(io.StringIO()):
                    cli.cmd_knowledge_add(args)

                # Should be in confidential DB due to title classification
                confidential_mgr = ConfidentialStorageManager()
                entries = confidential_mgr.knowledge.get_all_entries()
                self.assertEqual(len(entries), 1)
                self.assertIn("cd.splunkdev.com", entries[0].title)

                # Should NOT be in public DB
                public_entries = cli.storage.knowledge.get_all_entries()
                self.assertEqual(len(public_entries), 0)

    def test_public_content_routes_to_public_db(self):
        """Test that non-confidential content routes to public DB."""
        with TemporaryDirectory() as tmpdir:
            # Create separate dirs for public and confidential
            public_dir = os.path.join(tmpdir, "public")
            confidential_dir = os.path.join(tmpdir, "confidential")
            os.makedirs(public_dir)
            os.makedirs(confidential_dir)

            cli = AdaptivePreferenceCLI(public_dir)

            args = Namespace(
                partition="project_context",
                category="note",
                title="General Knowledge",
                tags=[],
                content="Python uses indentation for code blocks",
                confidence=1.0,
                decay_exempt=False,
                expires_at=None,
                expires_when=None,
                expires_when_tag=None,
                confidential=False,  # No explicit flag
            )

            # Mock ConfidentialStorageManager to use tmpdir
            original_init = ConfidentialStorageManager.__init__
            def mock_init(self, base_dir=None):
                original_init(self, confidential_dir)

            with patch.object(ConfidentialStorageManager, '__init__', mock_init):
                with redirect_stdout(io.StringIO()):
                    cli.cmd_knowledge_add(args)

                # Should be in public DB
                public_entries = cli.storage.knowledge.get_all_entries()
                self.assertEqual(len(public_entries), 1)
                self.assertEqual(public_entries[0].title, "General Knowledge")

                # Should NOT be in confidential DB
                confidential_mgr = ConfidentialStorageManager()
                entries = confidential_mgr.knowledge.get_all_entries()
                self.assertEqual(len(entries), 0)


if __name__ == "__main__":
    unittest.main()
