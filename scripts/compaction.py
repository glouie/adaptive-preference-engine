"""
compaction.py - Knowledge compaction engine for APE

Implements budget-triggered compaction of knowledge partitions to manage token
usage within configured limits. When knowledge entries in a partition exceed
the partition budget, the engine consolidates them into a single reference entry
with content stored in an external markdown file.

Compaction strategy:
1. Check if global knowledge tokens exceed token_budgets.knowledge (3000)
2. If over, find partitions exceeding token_budgets.partition (1000) and compact those first
3. If no partition is individually over but global still breaches, compact the largest partition
4. Max 5 rounds per trigger (safety cap)

Ref files are stored in: <sync_repo>/partitions/<partition>/consolidated.md
"""

import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from adaptive_preference_engine.knowledge import KnowledgeEntry
from scripts.config import AdaptiveConfig, APEConfig
from scripts.models import generate_id
from scripts.storage import PreferenceStorageManager

logger = logging.getLogger(__name__)

# Safety cap: max rounds per compaction trigger
MAX_ROUNDS = 5


class CompactionEngine:
    """
    Knowledge compaction engine for budget management.

    Consolidates knowledge entries within a partition when token budgets are
    exceeded, storing full content in external ref files and creating a
    consolidated database entry with ref_path.
    """

    def __init__(self, storage: PreferenceStorageManager = None, knowledge_storage=None, base_dir: str = None):
        """
        Initialize compaction engine.

        Args:
            storage: PreferenceStorageManager instance (optional if knowledge_storage provided)
            knowledge_storage: KnowledgeStorage instance (optional, defaults to storage.knowledge)
            base_dir: Base directory path (required if knowledge_storage provided without storage)
        """
        self.storage = storage

        # Determine knowledge storage
        if knowledge_storage:
            self.knowledge = knowledge_storage
        elif storage:
            self.knowledge = storage.knowledge
        else:
            raise ValueError("Either storage or knowledge_storage must be provided")

        # Get base_dir for config
        if storage:
            base_dir = storage.base_dir
        elif base_dir is None:
            raise ValueError("base_dir must be provided when using knowledge_storage without storage")

        self.adaptive_config = AdaptiveConfig(base_dir)

        # Load APE config with budgets
        self.ape_config = APEConfig.load(
            str(base_dir),
            sync_repo_path=self.adaptive_config.sync_repo_path
        )

        # Get token budgets
        self.knowledge_budget = self.ape_config.get("token_budgets.knowledge", 3000)
        self.partition_budget = self.ape_config.get("token_budgets.partition", 1000)

        # Get sync repo path for ref files
        self.sync_repo_path = self.adaptive_config.sync_repo_path

    def check_and_compact(self) -> List[str]:
        """
        Main entry point: check budgets and compact if needed.

        Returns:
            List of partition names that were compacted
        """
        if not self.sync_repo_path:
            logger.warning(
                "No sync_repo_path configured - skipping compaction. "
                "Run 'ape-buddy config set sync_repo_path <path>' to enable."
            )
            return []

        sync_repo = Path(self.sync_repo_path)
        if not sync_repo.exists():
            logger.warning(
                f"Sync repo does not exist: {self.sync_repo_path} - skipping compaction"
            )
            return []

        compacted_partitions = []
        rounds = 0

        while rounds < MAX_ROUNDS:
            rounds += 1

            # Calculate current token usage
            partition_tokens = self._calculate_partition_tokens()
            total_tokens = sum(partition_tokens.values())

            logger.debug(
                f"Compaction round {rounds}: total={total_tokens}, "
                f"budget={self.knowledge_budget}, partitions={len(partition_tokens)}"
            )

            # Check if we're over budget
            if total_tokens <= self.knowledge_budget:
                logger.debug("Within budget - no compaction needed")
                break

            # Find partition to compact
            partition_to_compact = self._select_partition_to_compact(partition_tokens)

            if not partition_to_compact:
                logger.warning(
                    f"Global budget exceeded ({total_tokens} > {self.knowledge_budget}) "
                    f"but no partition can be compacted (round {rounds})"
                )
                break

            # Compact the selected partition
            logger.info(
                f"Compacting partition '{partition_to_compact}' "
                f"({partition_tokens[partition_to_compact]} tokens)"
            )

            success = self._compact_partition(partition_to_compact)

            if success:
                compacted_partitions.append(partition_to_compact)
            else:
                logger.error(f"Failed to compact partition '{partition_to_compact}'")
                break

        if rounds >= MAX_ROUNDS:
            logger.warning(
                f"Compaction stopped after {MAX_ROUNDS} rounds (safety cap)"
            )

        return compacted_partitions

    def _calculate_partition_tokens(self) -> Dict[str, int]:
        """
        Calculate token usage per partition (excluding archived entries).

        Returns:
            Dict mapping partition name to total token count
        """
        partition_tokens: Dict[str, int] = {}

        all_entries = self.knowledge.get_all_entries(include_archived=False)

        for entry in all_entries:
            if entry.partition not in partition_tokens:
                partition_tokens[entry.partition] = 0
            partition_tokens[entry.partition] += entry.token_estimate

        return partition_tokens

    def _select_partition_to_compact(self, partition_tokens: Dict[str, int]) -> Optional[str]:
        """
        Select which partition to compact.

        Strategy:
        1. If any partition exceeds partition_budget, compact the largest one
        2. Otherwise, compact the largest partition overall
        3. Only compact partitions with 2+ entries (can't compact single entry)

        Args:
            partition_tokens: Dict mapping partition name to token count

        Returns:
            Partition name to compact, or None if no suitable partition found
        """
        if not partition_tokens:
            return None

        # Find partitions exceeding partition budget
        over_budget = [
            (partition, tokens)
            for partition, tokens in partition_tokens.items()
            if tokens > self.partition_budget
        ]

        # Get entry counts per partition
        partition_entry_counts = self._get_partition_entry_counts()

        if over_budget:
            # Sort by tokens (descending) and filter out single-entry partitions
            over_budget.sort(key=lambda x: x[1], reverse=True)
            for partition, _ in over_budget:
                if partition_entry_counts.get(partition, 0) >= 2:
                    return partition

        # No partition over budget individually - compact largest partition
        sorted_partitions = sorted(
            partition_tokens.items(),
            key=lambda x: x[1],
            reverse=True
        )

        for partition, _ in sorted_partitions:
            if partition_entry_counts.get(partition, 0) >= 2:
                return partition

        # No partition has 2+ entries - can't compact
        return None

    def _get_partition_entry_counts(self) -> Dict[str, int]:
        """
        Get count of non-archived entries per partition.

        Returns:
            Dict mapping partition name to entry count
        """
        counts: Dict[str, int] = {}

        all_entries = self.knowledge.get_all_entries(include_archived=False)

        for entry in all_entries:
            counts[entry.partition] = counts.get(entry.partition, 0) + 1

        return counts

    def _compact_partition(self, partition: str) -> bool:
        """
        Compact all entries in a partition into a single consolidated entry.

        Process:
        1. Fetch all non-archived entries for the partition
        2. Write full content to ref file: <sync_repo>/partitions/<partition>/consolidated.md
        3. Create or update consolidated DB entry with ref_path
        4. Archive original entries
        5. Git commit the ref file

        Args:
            partition: Partition name to compact

        Returns:
            True if compaction succeeded, False otherwise
        """
        # Fetch entries to compact
        entries = self.knowledge.get_entries_by_partition(
            partition,
            include_archived=False
        )

        if len(entries) < 2:
            logger.warning(
                f"Partition '{partition}' has {len(entries)} entries - "
                f"need at least 2 to compact"
            )
            return False

        # Check if there's already a consolidated entry (re-compaction)
        existing_consolidated = None
        regular_entries = []

        for entry in entries:
            if entry.ref_path and entry.title.startswith("Consolidated:"):
                existing_consolidated = entry
            else:
                regular_entries.append(entry)

        if not regular_entries:
            logger.warning(
                f"Partition '{partition}' has only consolidated entries - skipping"
            )
            return False

        # Prepare ref file path
        sync_repo = Path(self.sync_repo_path)
        # Encode partition name to avoid collisions (e.g., "projects/foo/bar" vs "projects_foo_bar")
        # Use URL-safe encoding: replace "/" with "__" and "_" with "_u"
        safe_partition = partition.replace("_", "_u").replace("/", "__")
        partition_dir = sync_repo / "partitions" / safe_partition
        partition_dir.mkdir(parents=True, exist_ok=True)

        ref_file = partition_dir / "consolidated.md"
        ref_rel = ref_file.relative_to(sync_repo)

        # Build consolidated content
        consolidated_content = self._build_consolidated_content(
            regular_entries,
            existing_consolidated
        )

        # Write ref file
        try:
            ref_file.write_text(consolidated_content, encoding="utf-8")
        except OSError as e:
            logger.error(f"Failed to write ref file {ref_file}: {e}")
            return False

        # Collect all titles and tags for the consolidated entry
        all_titles = [entry.title for entry in regular_entries]
        all_tags: Set[str] = set()
        for entry in regular_entries:
            all_tags.update(entry.tags)

        if existing_consolidated:
            # Add existing consolidated tags
            all_tags.update(existing_consolidated.tags)

        # Calculate token estimate for summary (rough estimate: 1 token per 4 chars)
        summary_text = f"Consolidated {len(regular_entries)} entries: " + ", ".join(all_titles[:5])
        if len(all_titles) > 5:
            summary_text += f", ... and {len(all_titles) - 5} more"

        token_estimate = len(summary_text) // 4

        # Create or update consolidated entry
        if existing_consolidated:
            # Update existing consolidated entry
            consolidated_entry = existing_consolidated
            consolidated_entry.content = summary_text
            consolidated_entry.tags = sorted(all_tags)
            consolidated_entry.token_estimate = token_estimate
            consolidated_entry.last_used = datetime.now().isoformat()
        else:
            # Create new consolidated entry
            consolidated_entry = KnowledgeEntry(
                id=generate_id("consolidated"),
                partition=partition,
                category="consolidated",
                title=f"Consolidated: {partition}",
                tags=sorted(all_tags),
                content=summary_text,
                confidence=1.0,
                source="compaction",
                token_estimate=token_estimate,
                ref_path=str(ref_rel),
            )

        # Save consolidated entry
        self.knowledge.save_entry(consolidated_entry)

        # Archive original entries
        for entry in regular_entries:
            self.knowledge.archive_entry(entry.id)

        # Calculate tokens saved
        original_tokens = sum(entry.token_estimate for entry in regular_entries)
        tokens_saved = original_tokens - token_estimate

        # Git commit
        self._git_commit(
            ref_rel=str(ref_rel),
            partition=partition,
            count=len(regular_entries),
            saved=tokens_saved
        )

        logger.info(
            f"Compacted {len(regular_entries)} entries in '{partition}' -> "
            f"1 consolidated entry (saved {tokens_saved} tokens)"
        )

        return True

    def _build_consolidated_content(
        self,
        entries: List[KnowledgeEntry],
        existing_consolidated: Optional[KnowledgeEntry]
    ) -> str:
        """
        Build markdown content for consolidated ref file.

        Args:
            entries: List of entries to consolidate
            existing_consolidated: Existing consolidated entry if re-compacting

        Returns:
            Markdown content string
        """
        lines = [
            f"# Consolidated Knowledge: {entries[0].partition}",
            "",
            f"Consolidated at: {datetime.now().isoformat()}",
            f"Entry count: {len(entries)}",
            "",
        ]

        if existing_consolidated:
            lines.extend([
                "**Note:** This is a re-compaction. Previous consolidation has been merged.",
                "",
            ])

        lines.extend([
            "---",
            "",
        ])

        for entry in entries:
            lines.extend([
                f"## {entry.title}",
                "",
                f"**Category:** {entry.category}",
                f"**Tags:** {', '.join(entry.tags)}",
                f"**Confidence:** {entry.confidence}",
                f"**Created:** {entry.created_at}",
                "",
                entry.content,
                "",
                "---",
                "",
            ])

        return "\n".join(lines)

    def _git_commit(self, ref_rel: str, partition: str, count: int, saved: int) -> None:
        """
        Git commit the ref file to sync repo.

        Args:
            ref_rel: Relative path to ref file from sync repo root
            partition: Partition name
            count: Number of entries compacted
            saved: Tokens saved
        """
        sync_repo = Path(self.sync_repo_path)

        try:
            # Add the ref file
            subprocess.run(
                ["git", "add", str(ref_rel)],
                cwd=str(sync_repo),
                check=True,
                capture_output=True,
                text=True
            )

            # Commit with descriptive message
            commit_msg = f"ape: compact {partition} ({count} entries -> 1, saved {saved}t)"
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=str(sync_repo),
                check=True,
                capture_output=True,
                text=True
            )

            logger.debug(f"Git committed: {commit_msg}")

        except subprocess.CalledProcessError as e:
            logger.warning(f"Git commit failed: {e.stderr}")

    def read_ref_content(self, entry: KnowledgeEntry) -> Optional[str]:
        """
        Read full content from a ref file for a consolidated entry.

        Args:
            entry: KnowledgeEntry with ref_path set

        Returns:
            Full content string from ref file, or None if not found or error
        """
        if not entry.ref_path:
            logger.warning(f"Entry {entry.id} has no ref_path")
            return None

        if not self.sync_repo_path:
            logger.warning("No sync_repo_path configured")
            return None

        sync_repo = Path(self.sync_repo_path)
        ref_file = sync_repo / entry.ref_path

        if not ref_file.exists():
            logger.warning(f"Ref file not found: {ref_file}")
            return None

        try:
            return ref_file.read_text(encoding="utf-8")
        except OSError as e:
            logger.error(f"Failed to read ref file {ref_file}: {e}")
            return None
