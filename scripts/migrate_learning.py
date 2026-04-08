#!/usr/bin/env python3
"""migrate_learning.py — One-time migration from learning plugin to APE knowledge store.

Usage:
    python3 scripts/migrate_learning.py --source ~/learning/glouie-assistant
    python3 scripts/migrate_learning.py --source ~/learning/glouie-assistant --dry-run
"""

import argparse
import re
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.storage import PreferenceStorageManager
from adaptive_preference_engine.knowledge import KnowledgeEntry


def _load_yaml(path: Path) -> dict:
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        raise RuntimeError("pyyaml required for migration. Install: pip install pyyaml")


def _extract_content(md_path: Path) -> str:
    """Extract markdown content after YAML frontmatter."""
    text = md_path.read_text()
    parts = re.split(r'^---\s*$', text, maxsplit=2, flags=re.MULTILINE)
    if len(parts) >= 3:
        return parts[2].strip()
    return text.strip()


def migrate(source_dir: str, dry_run: bool = False) -> dict:
    source = Path(source_dir).expanduser()
    index_path = source / "index.yaml"

    if not index_path.exists():
        print(f"ERROR: {index_path} not found")
        sys.exit(1)

    index = _load_yaml(index_path)
    entries = index.get("entries", [])
    print(f"Found {len(entries)} entries in index.yaml")

    if not dry_run:
        mgr = PreferenceStorageManager()

    migrated = []
    errors = []
    hostname = socket.gethostname()

    for entry_meta in entries:
        file_path = source / entry_meta.get("file_path", "")
        if not file_path.exists():
            errors.append(f"Missing file: {file_path}")
            continue

        content = _extract_content(file_path)
        if not content:
            errors.append(f"Empty content: {file_path}")
            continue

        knowledge = KnowledgeEntry(
            id=entry_meta["id"],
            partition=entry_meta.get("partition", "user"),
            category=entry_meta.get("category", "convention"),
            title=entry_meta.get("title", file_path.stem),
            tags=entry_meta.get("tags", []),
            content=content,
            confidence=entry_meta.get("confidence", 1.0),
            source="migrated",
            machine_origin=hostname,
            decay_exempt=entry_meta.get("decay_exempt", False),
            access_count=entry_meta.get("access_count", 0),
            token_estimate=entry_meta.get("token_estimate", len(content) // 4),
            created_at=entry_meta.get("created_at", ""),
            last_used=entry_meta.get("last_used", ""),
        )

        if dry_run:
            print(f"  [DRY RUN] Would migrate: [{knowledge.partition}] {knowledge.title} ({knowledge.token_estimate}t)")
        else:
            mgr.knowledge.save_entry(knowledge)
            print(f"  Migrated: [{knowledge.partition}] {knowledge.title} ({knowledge.token_estimate}t)")
        migrated.append(knowledge)

    if not dry_run:
        mgr.close()

    label = "Would migrate" if dry_run else "Migrated"
    print(f"\n{label}: {len(migrated)} entries")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors:
            print(f"  - {e}")

    return {"migrated": len(migrated), "errors": len(errors)}


def verify(expected_count: int) -> bool:
    mgr = PreferenceStorageManager()
    entries = mgr.knowledge.get_all_entries(include_archived=True)
    mgr.close()
    actual = len(entries)
    if actual >= expected_count:
        print(f"Verification PASSED: {actual} entries in knowledge table (expected {expected_count})")
        return True
    else:
        print(f"Verification FAILED: expected {expected_count}, got {actual}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Migrate learning plugin to APE knowledge store")
    parser.add_argument("--source", required=True, help="Path to glouie-assistant repo")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    parser.add_argument("--verify-only", action="store_true", dest="verify_only",
                        help="Only verify existing migration")
    parser.add_argument("--expected", type=int, default=21,
                        help="Expected entry count for verification (default: 21)")
    args = parser.parse_args()

    if args.verify_only:
        ok = verify(args.expected)
        sys.exit(0 if ok else 1)

    result = migrate(args.source, dry_run=args.dry_run)

    if not args.dry_run and result["errors"] == 0:
        print("\nVerifying...")
        verify(result["migrated"])


if __name__ == "__main__":
    main()
