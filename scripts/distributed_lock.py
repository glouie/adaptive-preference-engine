"""
distributed_lock.py - File-based distributed lock system for multi-agent concurrent writes
Addresses James Rodriguez's gap: "No distributed locking for multi-agent concurrent writes"
"""

import os
import json
import time
import psutil
import logging
import random
from pathlib import Path
from typing import Optional
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

# One-time setup for lock contention logging
_lock_contention_handler_configured = False

def _setup_lock_contention_logging():
    """Setup file handler for lock contention events (one-time)."""
    global _lock_contention_handler_configured
    if _lock_contention_handler_configured:
        return

    try:
        lock_contention_log = os.path.expanduser("~/.adaptive-cli/lock_contention.log")
        lock_contention_dir = os.path.dirname(lock_contention_log)
        os.makedirs(lock_contention_dir, exist_ok=True)

        file_handler = logging.FileHandler(lock_contention_log)
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        _lock_contention_handler_configured = True
    except Exception:
        # Silent failure if logging setup fails
        pass


class DistributedLock:
    """File-based distributed locking using .lock files with PID and timestamp"""

    def __init__(self, base_dir: str = None, lock_ttl_seconds: int = 300):
        """
        Initialize distributed lock system.

        Args:
            base_dir: Base directory for lock files (defaults to ~/.adaptive-cli)
            lock_ttl_seconds: Lock time-to-live in seconds (default: 300 = 5 minutes).
                             Locks older than this are treated as stale.
        """
        if base_dir is None:
            base_dir = os.path.expanduser("~/.adaptive-cli")

        self.base_dir = Path(base_dir)
        self.locks_dir = self.base_dir / "locks"
        self.locks_dir.mkdir(parents=True, exist_ok=True)

        self.current_pid = os.getpid()
        self.lock_ttl_seconds = lock_ttl_seconds

    def acquire(self, lock_name: str, timeout_seconds: float = 5.0) -> bool:
        """
        Acquire a lock for the given resource with exponential backoff and jitter.
        Returns False if already locked by a live process.

        Uses exponential backoff strategy:
        - Base delay: 0.05s
        - Each retry: delay = min(base * (2 ** attempt), 2.0) + random jitter [0, 0.1)
        - Capped at 2.0 seconds max delay

        Args:
            lock_name: Name of resource to lock
            timeout_seconds: Timeout for acquiring lock

        Returns:
            True if lock acquired, False if already locked
        """
        _setup_lock_contention_logging()

        lock_file = self.locks_dir / f"{lock_name}.lock"
        start_time = time.time()
        attempt = 0

        while time.time() - start_time < timeout_seconds:
            # Check if lock exists and process is alive
            if lock_file.exists():
                if self._is_lock_valid(lock_file):
                    # Lock is held by another live process
                    # Calculate exponential backoff with jitter
                    base_delay = 0.05
                    exponential_delay = base_delay * (2 ** attempt)
                    delay = min(exponential_delay, 2.0)
                    jitter = random.uniform(0, 0.1)
                    sleep_time = delay + jitter
                    time.sleep(sleep_time)
                    attempt += 1
                    continue
                else:
                    # Lock exists but process is dead, remove it
                    lock_file.unlink(missing_ok=True)

            # Try to create the lock file
            try:
                lock_data = {
                    "pid": self.current_pid,
                    "timestamp": datetime.now().isoformat(),
                    "hostname": os.uname().nodename
                }

                # Write atomically by writing to temp file then renaming
                temp_lock = self.locks_dir / f"{lock_name}.lock.tmp"
                with open(temp_lock, 'w') as f:
                    json.dump(lock_data, f)

                temp_lock.rename(lock_file)

                # Log successful acquisition after waiting
                total_wait_time = time.time() - start_time
                if total_wait_time > 0.001:  # Only log if there was actual wait
                    logger.debug(
                        f"Lock acquired: {lock_name}, wait_time={total_wait_time:.3f}s, attempts={attempt}"
                    )

                return True
            except (FileExistsError, OSError):
                # Another process created the lock, try again
                base_delay = 0.05
                exponential_delay = base_delay * (2 ** attempt)
                delay = min(exponential_delay, 2.0)
                jitter = random.uniform(0, 0.1)
                sleep_time = delay + jitter
                time.sleep(sleep_time)
                attempt += 1

        # Lock acquisition failed
        total_wait_time = time.time() - start_time
        logger.warning(
            f"Failed to acquire lock: {lock_name}, timeout={timeout_seconds}s, "
            f"total_wait_time={total_wait_time:.3f}s, attempts={attempt}"
        )

        return False

    def release(self, lock_name: str) -> bool:
        """
        Release a lock if owned by current process.

        Args:
            lock_name: Name of resource to unlock

        Returns:
            True if lock released, False if not owned by this process
        """
        lock_file = self.locks_dir / f"{lock_name}.lock"

        if not lock_file.exists():
            return False

        try:
            lock_data = self._read_lock_file(lock_file)

            # Only release if owned by this process
            if lock_data.get("pid") == self.current_pid:
                lock_file.unlink(missing_ok=True)
                return True
            else:
                return False
        except Exception:
            return False

    def is_locked(self, lock_name: str) -> bool:
        """
        Check if a lock exists and the owning process is still alive.

        Also checks TTL: if the lock file exists but is older than lock_ttl_seconds,
        treats it as stale and returns False (doesn't hold up on zombie locks).

        Args:
            lock_name: Name of resource

        Returns:
            True if lock exists, process is alive, and lock is not stale
        """
        lock_file = self.locks_dir / f"{lock_name}.lock"

        if not lock_file.exists():
            return False

        # Check TTL: if lock is too old, treat as stale
        if self._is_lock_stale(lock_file):
            return False

        return self._is_lock_valid(lock_file)

    def cleanup_stale_locks(self) -> int:
        """
        Remove locks where the owning PID is no longer alive or lock is older than TTL.

        Checks both process validity and TTL age. Removes locks that are either:
        - Owned by a dead process
        - Older than lock_ttl_seconds

        Returns:
            Number of stale locks cleaned up
        """
        cleaned = 0

        for lock_file in self.locks_dir.glob("*.lock"):
            # Remove if process is dead or lock is too old
            if not self._is_lock_valid(lock_file) or self._is_lock_stale(lock_file):
                try:
                    lock_file.unlink(missing_ok=True)
                    cleaned += 1
                except Exception:
                    pass

        return cleaned

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit (no-op, release must be called explicitly)"""
        return False

    def _is_lock_stale(self, lock_file: Path) -> bool:
        """
        Check if lock file is older than TTL.

        Args:
            lock_file: Path to lock file

        Returns:
            True if lock is older than lock_ttl_seconds, False otherwise
        """
        try:
            lock_data = self._read_lock_file(lock_file)
            timestamp_str = lock_data.get("timestamp")

            if not timestamp_str:
                return True  # No timestamp = stale

            lock_time = datetime.fromisoformat(timestamp_str)
            age_seconds = (datetime.now() - lock_time).total_seconds()
            return age_seconds > self.lock_ttl_seconds
        except Exception:
            return True  # If we can't determine age, treat as stale

    def _is_lock_valid(self, lock_file: Path) -> bool:
        """
        Check if lock file exists and the process is still alive.

        Args:
            lock_file: Path to lock file

        Returns:
            True if lock is valid (process alive), False otherwise
        """
        try:
            lock_data = self._read_lock_file(lock_file)
            pid = lock_data.get("pid")

            if pid is None:
                return False

            # Check if process with this PID is still alive
            try:
                process = psutil.Process(pid)
                # Process exists and is running
                return process.is_running()
            except (psutil.NoSuchProcess, ProcessLookupError):
                return False
        except Exception:
            return False

    def _read_lock_file(self, lock_file: Path) -> dict:
        """
        Read lock file data.

        Args:
            lock_file: Path to lock file

        Returns:
            Lock data dictionary
        """
        try:
            with open(lock_file, 'r') as f:
                return json.load(f)
        except Exception:
            return {}


class LockedStorageManager:
    """Wrapper around PreferenceStorageManager that acquires write locks"""

    def __init__(self, storage_manager, lock_timeout: float = 5.0):
        """
        Initialize locked storage manager.

        Args:
            storage_manager: PreferenceStorageManager instance
            lock_timeout: Timeout for acquiring locks
        """
        self.storage = storage_manager
        self.lock_timeout = lock_timeout
        self.distributed_lock = DistributedLock(
            base_dir=str(storage_manager.base_dir)
        )

    def save_preference(self, preference):
        """Save preference with write lock"""
        lock_name = "preferences_write"

        if not self.distributed_lock.acquire(lock_name, self.lock_timeout):
            raise RuntimeError(f"Could not acquire lock for {lock_name}")

        try:
            self.storage.preferences.save_preference(preference)
        finally:
            self.distributed_lock.release(lock_name)

    def save_association(self, association):
        """Save association with write lock"""
        lock_name = "associations_write"

        if not self.distributed_lock.acquire(lock_name, self.lock_timeout):
            raise RuntimeError(f"Could not acquire lock for {lock_name}")

        try:
            self.storage.associations.save_association(association)
        finally:
            self.distributed_lock.release(lock_name)

    def save_context(self, context):
        """Save context with write lock"""
        lock_name = "contexts_write"

        if not self.distributed_lock.acquire(lock_name, self.lock_timeout):
            raise RuntimeError(f"Could not acquire lock for {lock_name}")

        try:
            self.storage.contexts.save_context(context)
        finally:
            self.distributed_lock.release(lock_name)

    def save_signal(self, signal):
        """Save signal with write lock"""
        lock_name = "signals_write"

        if not self.distributed_lock.acquire(lock_name, self.lock_timeout):
            raise RuntimeError(f"Could not acquire lock for {lock_name}")

        try:
            self.storage.signals.save_signal(signal)
        finally:
            self.distributed_lock.release(lock_name)

    def reset(self, confirm: bool = True):
        """Reset storage with write lock"""
        lock_name = "storage_reset"

        if not self.distributed_lock.acquire(lock_name, self.lock_timeout):
            raise RuntimeError(f"Could not acquire lock for {lock_name}")

        try:
            self.storage.reset(confirm=confirm)
        finally:
            self.distributed_lock.release(lock_name)

    # Passthrough read methods (no locking needed)
    def get_preference(self, pref_id: str):
        """Get preference (read-only, no lock needed)"""
        return self.storage.preferences.get_preference(pref_id)

    def get_all_preferences(self):
        """Get all preferences (read-only, no lock needed)"""
        return self.storage.preferences.get_all_preferences()

    def get_association(self, assoc_id: str):
        """Get association (read-only, no lock needed)"""
        return self.storage.associations.get_association(assoc_id)

    def get_all_associations(self):
        """Get all associations (read-only, no lock needed)"""
        return self.storage.associations.get_all_associations()

    def get_context(self, context_id: str):
        """Get context (read-only, no lock needed)"""
        return self.storage.contexts.get_context(context_id)

    def get_all_contexts(self):
        """Get all contexts (read-only, no lock needed)"""
        return self.storage.contexts.get_all_contexts()

    def get_signal(self, signal_id: str):
        """Get signal (read-only, no lock needed)"""
        return self.storage.signals.get_signal(signal_id)

    def get_all_signals(self):
        """Get all signals (read-only, no lock needed)"""
        return self.storage.signals.get_all_signals()

    def get_storage_info(self):
        """Get storage statistics (read-only, no lock needed)"""
        return self.storage.get_storage_info()

    def backup(self, backup_name: str = None):
        """Create backup with lock"""
        lock_name = "storage_backup"

        if not self.distributed_lock.acquire(lock_name, self.lock_timeout):
            raise RuntimeError(f"Could not acquire lock for {lock_name}")

        try:
            return self.storage.backup(backup_name=backup_name)
        finally:
            self.distributed_lock.release(lock_name)

    def cleanup_stale_locks(self) -> int:
        """Clean up stale locks (convenience method)"""
        return self.distributed_lock.cleanup_stale_locks()


if __name__ == "__main__":
    # Quick test
    lock = DistributedLock("/tmp/test_locks")

    # Test basic lock acquire/release
    print("Testing lock acquire...")
    if lock.acquire("test_resource", timeout_seconds=2.0):
        print("✓ Lock acquired")

        print("Checking lock status...")
        print(f"✓ Is locked: {lock.is_locked('test_resource')}")

        print("Releasing lock...")
        if lock.release("test_resource"):
            print("✓ Lock released")
        else:
            print("✗ Failed to release lock")
    else:
        print("✗ Failed to acquire lock")

    # Test cleanup
    print("\nTesting cleanup...")
    cleaned = lock.cleanup_stale_locks()
    print(f"✓ Cleaned up {cleaned} stale locks")
