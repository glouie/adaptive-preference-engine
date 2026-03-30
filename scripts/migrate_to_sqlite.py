#!/usr/bin/env python3
"""
migrate_to_sqlite.py — One-time migration from JSONL files to SQLite.

Usage:
    python scripts/migrate_to_sqlite.py
    python scripts/migrate_to_sqlite.py --base-dir /custom/path
    python scripts/migrate_to_sqlite.py --dry-run

The script is idempotent: running it twice does not duplicate records
(SQLite UPSERT handles conflicts by ID).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.storage import PreferenceStorageManager
from scripts.models import (
    Association, ContextStack, Preference, Signal,
)


def _read_jsonl(path: Path):
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"  ⚠  Skipping malformed line in {path.name}")
    return records


def migrate(base_dir: str, dry_run: bool = False) -> None:
    base = Path(base_dir)
    prefs_dir = base / "preferences"

    files = {
        "preferences":  prefs_dir / "all_preferences.jsonl",
        "associations": prefs_dir / "associations.jsonl",
        "contexts":     prefs_dir / "contexts.jsonl",
        "signals":      prefs_dir / "signals.jsonl",
    }

    counts = {k: len(_read_jsonl(v)) for k, v in files.items()}
    total = sum(counts.values())

    if total == 0:
        print("No JSONL data found — nothing to migrate.")
        return

    print(f"Found: {counts['preferences']} preferences, "
          f"{counts['associations']} associations, "
          f"{counts['contexts']} contexts, "
          f"{counts['signals']} signals")

    if dry_run:
        print("[dry-run] No changes written.")
        return

    mgr = PreferenceStorageManager(base_dir)

    for d in _read_jsonl(files["preferences"]):
        try:
            mgr.preferences.save_preference(Preference.from_dict(d))
        except Exception as e:
            print(f"  ⚠  preference {d.get('id')}: {e}")

    for d in _read_jsonl(files["associations"]):
        try:
            mgr.associations.save_association(Association.from_dict(d))
        except Exception as e:
            print(f"  ⚠  association {d.get('id')}: {e}")

    for d in _read_jsonl(files["contexts"]):
        try:
            mgr.contexts.save_context(ContextStack.from_dict(d))
        except Exception as e:
            print(f"  ⚠  context {d.get('id')}: {e}")

    for d in _read_jsonl(files["signals"]):
        try:
            mgr.signals.save_signal(Signal.from_dict(d))
        except Exception as e:
            print(f"  ⚠  signal {d.get('id')}: {e}")

    info = mgr.get_storage_info()
    print(f"✅ Migration complete → adaptive.db")
    print(f"   preferences:  {info['preferences_count']}")
    print(f"   associations: {info['associations_count']}")
    print(f"   contexts:     {info['contexts_count']}")
    print(f"   signals:      {info['signals_count']}")


def main():
    parser = argparse.ArgumentParser(description="Migrate JSONL data to SQLite")
    parser.add_argument(
        "--base-dir",
        default="~/.adaptive-cli",
        help="Base data directory (default: ~/.adaptive-cli)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without writing anything",
    )
    args = parser.parse_args()
    migrate(str(Path(args.base_dir).expanduser()), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
