"""Ingest memory inbox files into APE knowledge databases."""

import hashlib
from pathlib import Path
from typing import Optional

from scripts.memory_generator import parse_memory_file
from scripts.confidential_classifier import is_confidential
from scripts.models import generate_id
from adaptive_preference_engine.knowledge import KnowledgeEntry


def _content_hash(title: str, content: str, category: str, partition: str) -> str:
    """SHA-256 hash of title+content+category+partition for dedup."""
    data = f"{title}\n{content}\n{category}\n{partition}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _entry_exists(public_mgr, confidential_mgr, content_hash: str) -> bool:
    """Check if an entry with this content hash exists in either DB using O(1) index lookup."""
    for mgr in (public_mgr, confidential_mgr):
        if mgr is None:
            continue
        row = mgr.knowledge._conn.execute(
            "SELECT 1 FROM knowledge WHERE content_hash = ? LIMIT 1", (content_hash,)
        ).fetchone()
        if row:
            return True
    return False


def ingest_inbox(
    inbox_dir: Path,
    public_mgr,
    confidential_mgr,
) -> int:
    """Ingest all .md files from inbox into appropriate database.

    Returns count of entries ingested (skips duplicates and tmp files).
    """
    inbox = Path(inbox_dir)
    if not inbox.exists():
        return 0

    ingested = 0
    for md_file in sorted(inbox.glob("*.md")):
        # Skip tmp/hidden files
        if md_file.name.startswith("."):
            continue

        parsed = parse_memory_file(md_file)
        title = parsed["name"]
        content = parsed["content"]
        category = parsed["category"]
        partition = parsed["partition"]

        # Dedup check
        ch = _content_hash(title, content, category, partition)
        if _entry_exists(public_mgr, confidential_mgr, ch):
            md_file.unlink()
            continue

        # Route to correct DB
        if confidential_mgr and is_confidential(content):
            target_mgr = confidential_mgr
        else:
            target_mgr = public_mgr

        entry = KnowledgeEntry(
            id=generate_id("know"),
            partition=partition,
            category=category,
            title=title,
            tags=[],
            content=content,
            token_estimate=len(content.split()),
        )
        target_mgr.knowledge.save_entry(entry)
        md_file.unlink()
        ingested += 1

    return ingested
