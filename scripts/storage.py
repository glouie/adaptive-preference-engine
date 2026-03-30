"""
storage.py - JSONL file storage and retrieval for preferences, associations, signals
"""

import json
import os
import logging
import threading
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime
from scripts.models import Preference, Association, ContextStack, Signal
from scripts.distributed_lock import DistributedLock

logger = logging.getLogger(__name__)


class JSONLStorage:
    """Base class for JSONL file operations"""
    
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
    
    def append(self, obj: Dict[str, Any]) -> None:
        """Append JSON object as new line"""
        with open(self.filepath, 'a') as f:
            f.write(json.dumps(obj) + '\n')
    
    def read_all(self) -> List[Dict[str, Any]]:
        """Read all lines from JSONL file"""
        if not self.filepath.exists():
            return []
        
        data = []
        with open(self.filepath, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        data.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return data
    
    def read_filtered(self, filter_fn) -> List[Dict[str, Any]]:
        """Read lines matching filter function"""
        return [obj for obj in self.read_all() if filter_fn(obj)]
    
    def find_by_id(self, obj_id: str) -> Optional[Dict[str, Any]]:
        """Find object by ID"""
        data = self.read_all()
        return next((obj for obj in data if obj.get("id") == obj_id), None)
    
    def update_by_id(self, obj_id: str, updated_obj: Dict[str, Any]) -> bool:
        """Update object by ID (rewrites entire file)"""
        data = self.read_all()
        
        found = False
        for i, obj in enumerate(data):
            if obj.get("id") == obj_id:
                data[i] = updated_obj
                found = True
                break
        
        if found:
            self._rewrite_all(data)
        
        return found
    
    def _rewrite_all(self, data: List[Dict[str, Any]]) -> None:
        """Rewrite entire file (used for updates)"""
        self.filepath.unlink(missing_ok=True)
        for obj in data:
            self.append(obj)
    
    def clear(self) -> None:
        """Clear the file"""
        self.filepath.unlink(missing_ok=True)


class PreferenceStorage(JSONLStorage):
    """Manage preference JSONL files"""
    
    def save_preference(self, preference: Preference) -> None:
        """Save or update preference"""
        existing = self.find_by_id(preference.id)
        if existing:
            self.update_by_id(preference.id, preference.to_dict())
        else:
            self.append(preference.to_dict())
    
    def get_preference(self, pref_id: str) -> Optional[Preference]:
        """Get preference by ID"""
        data = self.find_by_id(pref_id)
        return Preference.from_dict(data) if data else None
    
    def get_preferences_for_parent(self, parent_id: str) -> List[Preference]:
        """Get all preferences under a parent"""
        data = self.read_filtered(lambda obj: obj.get("parent_id") == parent_id)
        return [Preference.from_dict(obj) for obj in data]
    
    def get_preferences_by_path(self, path_prefix: str) -> List[Preference]:
        """Get preferences by path prefix (e.g., 'communication.output_format')"""
        data = self.read_filtered(lambda obj: obj.get("path", "").startswith(path_prefix))
        return [Preference.from_dict(obj) for obj in data]
    
    def get_all_preferences(self) -> List[Preference]:
        """Get all preferences"""
        data = self.read_all()
        return [Preference.from_dict(obj) for obj in data]


class AssociationStorage(JSONLStorage):
    """Manage association JSONL file"""
    
    def save_association(self, association: Association) -> None:
        """Save or update association"""
        existing = self.find_by_id(association.id)
        if existing:
            self.update_by_id(association.id, association.to_dict())
        else:
            self.append(association.to_dict())
    
    def get_association(self, assoc_id: str) -> Optional[Association]:
        """Get association by ID"""
        data = self.find_by_id(assoc_id)
        return Association.from_dict(data) if data else None
    
    def get_associations_for_preference(self, pref_id: str) -> List[Association]:
        """Get all associations involving this preference (either direction)"""
        data = self.read_filtered(
            lambda obj: obj.get("from_id") == pref_id or obj.get("to_id") == pref_id
        )
        return [Association.from_dict(obj) for obj in data]
    
    def get_associations_from(self, from_id: str) -> List[Association]:
        """Get associations where this is the source"""
        data = self.read_filtered(lambda obj: obj.get("from_id") == from_id)
        return [Association.from_dict(obj) for obj in data]
    
    def get_associations_to(self, to_id: str) -> List[Association]:
        """Get associations where this is the target"""
        data = self.read_filtered(lambda obj: obj.get("to_id") == to_id)
        return [Association.from_dict(obj) for obj in data]
    
    def get_all_associations(self) -> List[Association]:
        """Get all associations"""
        data = self.read_all()
        return [Association.from_dict(obj) for obj in data]


class ContextStorage(JSONLStorage):
    """Manage context stack JSONL file"""
    
    def save_context(self, context: ContextStack) -> None:
        """Save or update context"""
        existing = self.find_by_id(context.id)
        if existing:
            self.update_by_id(context.id, context.to_dict())
        else:
            self.append(context.to_dict())
    
    def get_context(self, context_id: str) -> Optional[ContextStack]:
        """Get context by ID"""
        data = self.find_by_id(context_id)
        return ContextStack.from_dict(data) if data else None
    
    def get_contexts_by_scope(self, scope: str) -> List[ContextStack]:
        """Get all contexts for a scope (base, project, conversation)"""
        data = self.read_filtered(lambda obj: obj.get("scope") == scope)
        return [ContextStack.from_dict(obj) for obj in data]
    
    def get_active_contexts(self) -> List[ContextStack]:
        """Get all active contexts"""
        data = self.read_filtered(lambda obj: obj.get("active") is True)
        contexts = [ContextStack.from_dict(obj) for obj in data]
        # Sort by stack level (0, 1, 2)
        return sorted(contexts, key=lambda c: c.stack_level)
    
    def get_all_contexts(self) -> List[ContextStack]:
        """Get all contexts"""
        data = self.read_all()
        return [ContextStack.from_dict(obj) for obj in data]


class SignalStorage(JSONLStorage):
    """Manage behavioral signal JSONL file"""
    
    def save_signal(self, signal: Signal) -> None:
        """Save new signal (append only)"""
        self.append(signal.to_dict())
    
    def get_signal(self, signal_id: str) -> Optional[Signal]:
        """Get signal by ID"""
        data = self.find_by_id(signal_id)
        return Signal.from_dict(data) if data else None
    
    def get_signals_by_type(self, signal_type: str) -> List[Signal]:
        """Get signals by type (correction, feedback, usage, etc.)"""
        data = self.read_filtered(lambda obj: obj.get("type") == signal_type)
        return [Signal.from_dict(obj) for obj in data]
    
    def get_signals_for_preference(self, pref_id: str) -> List[Signal]:
        """Get signals affecting a specific preference"""
        data = self.read_filtered(
            lambda obj: pref_id in obj.get("preferences_used", [])
        )
        return [Signal.from_dict(obj) for obj in data]
    
    def get_recent_signals(self, hours: int = 24) -> List[Signal]:
        """Get signals from last N hours"""
        from datetime import datetime, timedelta
        
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        data = self.read_filtered(lambda obj: obj.get("timestamp", "") >= cutoff)
        return [Signal.from_dict(obj) for obj in data]
    
    def get_all_signals(self) -> List[Signal]:
        """Get all signals"""
        data = self.read_all()
        return [Signal.from_dict(obj) for obj in data]


class PreferenceStorageManager:
    """High-level manager for all preference storage"""

    def __init__(
        self,
        base_dir: str = None,
        use_locking: bool = True,
        auto_compact_threshold: int = 10000,
        write_timeout: Optional[float] = 30.0,
        read_timeout: Optional[float] = 10.0
    ):
        """
        Initialize storage manager.

        Args:
            base_dir: Base directory for preference storage (~/.adaptive-cli if None)
            use_locking: Whether to use distributed locking for write operations (default: True)
            auto_compact_threshold: Number of lines in a JSONL file that triggers auto-compaction (default: 10000)
            write_timeout: Timeout in seconds for write operations (default: 30.0, None to disable)
            read_timeout: Timeout in seconds for read operations (default: 10.0, None to disable)
        """
        if base_dir is None:
            base_dir = os.path.expanduser("~/.adaptive-cli")

        self.base_dir = Path(base_dir)
        self.preferences_dir = self.base_dir / "preferences"
        self.preferences_dir.mkdir(parents=True, exist_ok=True)

        # Initialize storage for different file types
        self.preferences = PreferenceStorage(str(self.preferences_dir / "all_preferences.jsonl"))
        self.associations = AssociationStorage(str(self.preferences_dir / "associations.jsonl"))
        self.contexts = ContextStorage(str(self.preferences_dir / "contexts.jsonl"))
        self.signals = SignalStorage(str(self.preferences_dir / "signals.jsonl"))

        # Initialize distributed lock system
        self.use_locking = use_locking
        self.distributed_lock = DistributedLock(str(self.base_dir)) if use_locking else None

        # Timeout settings for operations
        self.write_timeout = write_timeout
        self.read_timeout = read_timeout

        # Auto-compaction: check if compaction is needed and run if threshold exceeded
        if self.should_compact(auto_compact_threshold):
            logger.info(f"Auto-compaction triggered (threshold: {auto_compact_threshold})")
            self.compact_all()

    # ---- Auto-compaction helper methods ----

    def _record_count(self, jsonl_file: Path) -> int:
        """
        Efficiently count the number of records in a JSONL file.

        Counts non-empty lines without parsing JSON.

        Args:
            jsonl_file: Path to the JSONL file

        Returns:
            Number of non-empty lines in the file (0 if file doesn't exist)
        """
        if not jsonl_file.exists():
            return 0

        try:
            count = 0
            with open(jsonl_file, 'r') as f:
                for line in f:
                    if line.strip():
                        count += 1
            return count
        except Exception as e:
            logger.warning(f"Error counting records in {jsonl_file}: {e}")
            return 0

    def should_compact(self, threshold: int = 10000) -> bool:
        """
        Check if any JSONL file exceeds the compaction threshold.

        Args:
            threshold: Line count threshold for triggering compaction (default: 10000)

        Returns:
            True if any JSONL file has more than threshold lines, False otherwise
        """
        storage_files = [
            self.preferences.filepath,
            self.associations.filepath,
            self.contexts.filepath,
            self.signals.filepath
        ]

        for jsonl_file in storage_files:
            if self._record_count(jsonl_file) > threshold:
                logger.debug(f"Compaction needed: {jsonl_file.name} exceeds {threshold} lines")
                return True

        return False

    # ---- Wrapped write methods with optional locking ----

    def save_preference(self, preference: Preference) -> bool:
        """
        Save preference with optional distributed locking and timeout.

        Args:
            preference: Preference object to save

        Returns:
            True if save was successful, False if timeout occurred
        """
        def do_write():
            if self.use_locking:
                lock_name = "preferences_write"
                if not self.distributed_lock.acquire(lock_name, timeout_seconds=5.0):
                    raise RuntimeError(f"Could not acquire lock for {lock_name}")
                try:
                    self.preferences.save_preference(preference)
                finally:
                    self.distributed_lock.release(lock_name)
            else:
                self.preferences.save_preference(preference)

        if self.write_timeout is None:
            do_write()
            return True

        result = [False]
        exception = [None]

        def write_with_result():
            try:
                do_write()
                result[0] = True
            except Exception as e:
                exception[0] = e

        t = threading.Thread(target=write_with_result, daemon=False)
        t.start()
        t.join(timeout=self.write_timeout)

        if t.is_alive():
            logger.warning(
                f"Write timeout after {self.write_timeout}s for save_preference"
            )
            return False

        if exception[0]:
            raise exception[0]

        return result[0]

    def delete_preference(self, pref_id: str) -> None:
        """
        Delete preference with optional distributed locking.

        Args:
            pref_id: ID of preference to delete
        """
        if self.use_locking:
            lock_name = "preferences_write"
            if not self.distributed_lock.acquire(lock_name, timeout_seconds=5.0):
                raise RuntimeError(f"Could not acquire lock for {lock_name}")
            try:
                data = self.preferences.read_all()
                filtered = [obj for obj in data if obj.get("id") != pref_id]
                self.preferences._rewrite_all(filtered)
            finally:
                self.distributed_lock.release(lock_name)
        else:
            data = self.preferences.read_all()
            filtered = [obj for obj in data if obj.get("id") != pref_id]
            self.preferences._rewrite_all(filtered)

    def save_association(self, association: Association) -> bool:
        """
        Save association with optional distributed locking and timeout.

        Args:
            association: Association object to save

        Returns:
            True if save was successful, False if timeout occurred
        """
        def do_write():
            if self.use_locking:
                lock_name = "associations_write"
                if not self.distributed_lock.acquire(lock_name, timeout_seconds=5.0):
                    raise RuntimeError(f"Could not acquire lock for {lock_name}")
                try:
                    self.associations.save_association(association)
                finally:
                    self.distributed_lock.release(lock_name)
            else:
                self.associations.save_association(association)

        if self.write_timeout is None:
            do_write()
            return True

        result = [False]
        exception = [None]

        def write_with_result():
            try:
                do_write()
                result[0] = True
            except Exception as e:
                exception[0] = e

        t = threading.Thread(target=write_with_result, daemon=False)
        t.start()
        t.join(timeout=self.write_timeout)

        if t.is_alive():
            logger.warning(
                f"Write timeout after {self.write_timeout}s for save_association"
            )
            return False

        if exception[0]:
            raise exception[0]

        return result[0]

    def save_context(self, context: ContextStack) -> bool:
        """
        Save context with optional distributed locking and timeout.

        Args:
            context: ContextStack object to save

        Returns:
            True if save was successful, False if timeout occurred
        """
        def do_write():
            if self.use_locking:
                lock_name = "contexts_write"
                if not self.distributed_lock.acquire(lock_name, timeout_seconds=5.0):
                    raise RuntimeError(f"Could not acquire lock for {lock_name}")
                try:
                    self.contexts.save_context(context)
                finally:
                    self.distributed_lock.release(lock_name)
            else:
                self.contexts.save_context(context)

        if self.write_timeout is None:
            do_write()
            return True

        result = [False]
        exception = [None]

        def write_with_result():
            try:
                do_write()
                result[0] = True
            except Exception as e:
                exception[0] = e

        t = threading.Thread(target=write_with_result, daemon=False)
        t.start()
        t.join(timeout=self.write_timeout)

        if t.is_alive():
            logger.warning(
                f"Write timeout after {self.write_timeout}s for save_context"
            )
            return False

        if exception[0]:
            raise exception[0]

        return result[0]

    def save_signal(self, signal: Signal) -> bool:
        """
        Save signal with optional distributed locking and timeout.

        Args:
            signal: Signal object to save

        Returns:
            True if save was successful, False if timeout occurred
        """
        def do_write():
            if self.use_locking:
                lock_name = "signals_write"
                if not self.distributed_lock.acquire(lock_name, timeout_seconds=5.0):
                    raise RuntimeError(f"Could not acquire lock for {lock_name}")
                try:
                    self.signals.save_signal(signal)
                finally:
                    self.distributed_lock.release(lock_name)
            else:
                self.signals.save_signal(signal)

        if self.write_timeout is None:
            do_write()
            return True

        result = [False]
        exception = [None]

        def write_with_result():
            try:
                do_write()
                result[0] = True
            except Exception as e:
                exception[0] = e

        t = threading.Thread(target=write_with_result, daemon=False)
        t.start()
        t.join(timeout=self.write_timeout)

        if t.is_alive():
            logger.warning(
                f"Write timeout after {self.write_timeout}s for save_signal"
            )
            return False

        if exception[0]:
            raise exception[0]

        return result[0]

    def get_storage_info(self) -> Dict[str, Any]:
        """Get storage statistics"""
        return {
            "base_dir": str(self.base_dir),
            "preferences_count": len(self.preferences.get_all_preferences()),
            "associations_count": len(self.associations.get_all_associations()),
            "contexts_count": len(self.contexts.get_all_contexts()),
            "signals_count": len(self.signals.get_all_signals())
        }
    
    def backup(self, backup_name: str = None) -> str:
        """
        Create timestamped backup of all preference files (with optional locking).

        Args:
            backup_name: Name for the backup (defaults to timestamp)

        Returns:
            Path to the backup directory
        """
        backup_fn = self._do_backup

        if self.use_locking:
            lock_name = "storage_backup"
            if not self.distributed_lock.acquire(lock_name, timeout_seconds=5.0):
                raise RuntimeError(f"Could not acquire lock for {lock_name}")
            try:
                return backup_fn(backup_name)
            finally:
                self.distributed_lock.release(lock_name)
        else:
            return backup_fn(backup_name)

    def _do_backup(self, backup_name: str = None) -> str:
        """Internal backup implementation."""
        if backup_name is None:
            backup_name = datetime.now().strftime("%Y%m%d_%H%M%S")

        backup_dir = self.base_dir / "backups" / backup_name
        backup_dir.mkdir(parents=True, exist_ok=True)

        import shutil
        for file in self.preferences_dir.glob("*.jsonl"):
            shutil.copy(file, backup_dir / file.name)

        return str(backup_dir)
    
    def reset(self, confirm: bool = True) -> None:
        """
        Reset all preferences with optional locking (with backup).

        Args:
            confirm: Whether to prompt user for confirmation (default: True)
        """
        reset_fn = self._do_reset

        if self.use_locking:
            lock_name = "storage_reset"
            if not self.distributed_lock.acquire(lock_name, timeout_seconds=5.0):
                raise RuntimeError(f"Could not acquire lock for {lock_name}")
            try:
                return reset_fn(confirm)
            finally:
                self.distributed_lock.release(lock_name)
        else:
            return reset_fn(confirm)

    def _do_reset(self, confirm: bool = True) -> None:
        """Internal reset implementation."""
        if confirm:
            response = input("⚠️  Clear all preferences? This will back up old data. (y/n): ")
            if response.lower() != 'y':
                return

        self.backup(f"reset_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

        self.preferences.clear()
        self.associations.clear()
        self.contexts.clear()
        self.signals.clear()

        print("✅ Preferences reset. Backup created.")

    def compact(self) -> Dict[str, Dict[str, int]]:
        """
        Compact JSONL files by removing duplicate records, keeping only the latest
        version per unique ID.

        For each JSONL file (preferences, associations, contexts, signals):
        - Read all records
        - Keep only the latest version per unique ID
        - Rewrite the file

        Returns:
            Dictionary mapping filename to compaction stats:
            {
                "filename": {
                    "before": int (original record count),
                    "after": int (records after compaction),
                    "removed": int (records removed)
                }
            }
        """
        compact_fn = self._do_compact

        if self.use_locking:
            lock_name = "storage_compact"
            if not self.distributed_lock.acquire(lock_name, timeout_seconds=5.0):
                raise RuntimeError(f"Could not acquire lock for {lock_name}")
            try:
                return compact_fn()
            finally:
                self.distributed_lock.release(lock_name)
        else:
            return compact_fn()

    def _do_compact(self) -> Dict[str, Dict[str, int]]:
        """Internal compaction implementation."""
        results = {}

        # List of storage objects to compact
        storage_files = [
            ("preferences", self.preferences),
            ("associations", self.associations),
            ("contexts", self.contexts),
            ("signals", self.signals)
        ]

        for file_key, storage in storage_files:
            all_records = storage.read_all()
            before_count = len(all_records)

            # Keep only the latest version per ID
            seen_ids = {}
            for record in all_records:
                record_id = record.get("id")
                if record_id:
                    # Store the record (later ones overwrite earlier ones)
                    seen_ids[record_id] = record

            # Rewrite file with deduplicated records
            compacted_records = list(seen_ids.values())
            after_count = len(compacted_records)
            storage._rewrite_all(compacted_records)

            results[file_key] = {
                "before": before_count,
                "after": after_count,
                "removed": before_count - after_count
            }

        # Also compact metrics.jsonl if it exists
        metrics_file = Path(os.path.expanduser("~/.adaptive-cli/metrics.jsonl"))
        if metrics_file.exists():
            try:
                metrics_storage = JSONLStorage(str(metrics_file))
                all_records = metrics_storage.read_all()
                before_count = len(all_records)

                # Keep only the latest version per ID (if metrics have IDs)
                seen_ids = {}
                for record in all_records:
                    record_id = record.get("id")
                    if record_id:
                        seen_ids[record_id] = record
                    else:
                        # If no ID, keep the record (append-only metrics)
                        pass

                # Rewrite file with deduplicated records
                if seen_ids:
                    compacted_records = list(seen_ids.values())
                else:
                    # If no records have IDs, keep all as-is (metrics are append-only)
                    compacted_records = all_records

                after_count = len(compacted_records)
                if before_count != after_count:
                    metrics_storage._rewrite_all(compacted_records)

                results["metrics"] = {
                    "before": before_count,
                    "after": after_count,
                    "removed": before_count - after_count
                }
            except Exception as e:
                logger.warning(f"Error compacting metrics.jsonl: {e}")

        return results

    def compact_all(self) -> None:
        """
        Convenience method to run compact() and log the results.

        Calls compact() and prints a human-readable summary of compaction results.
        """
        import logging
        logger = logging.getLogger(__name__)

        results = self.compact()

        # Log summary
        logger.info("JSONL Compaction Results:")
        total_before = 0
        total_after = 0
        total_removed = 0

        for filename, stats in results.items():
            before = stats["before"]
            after = stats["after"]
            removed = stats["removed"]
            total_before += before
            total_after += after
            total_removed += removed

            logger.info(
                f"  {filename:15s}: {before:6d} -> {after:6d} records "
                f"({removed:6d} removed)"
            )

        logger.info(f"Total: {total_before} -> {total_after} records ({total_removed} removed)")


if __name__ == "__main__":
    # Quick test
    mgr = PreferenceStorageManager("/tmp/test_adaptive_cli")
    
    # Create test preference
    pref = Preference(
        id="comm_bullets",
        path="communication.output_format.bullets",
        parent_id="comm_format",
        name="bullets",
        type="variant",
        value="active",
        confidence=0.85
    )
    
    mgr.preferences.save_preference(pref)
    
    # Retrieve it
    retrieved = mgr.preferences.get_preference("comm_bullets")
    print(f"Saved and retrieved: {retrieved.name}")
    
    print("\nStorage info:", mgr.get_storage_info())
