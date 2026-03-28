"""
concurrency_control.py - Version-based locking (MVCC) for safe concurrent writes
Addresses James Rodriguez (Systems) critical gap: "No concurrency control"
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from models import generate_id


class ConcurrencyError(Exception):
    """Raised when concurrent modification is detected"""
    pass


class VersionedObject:
    """Any object that needs version control"""
    
    def __init__(self, obj_dict: Dict[str, Any]):
        self.data = obj_dict
        self._version = obj_dict.get("_version", 1)
        self._last_modified = obj_dict.get("_last_modified", datetime.now().isoformat())
        self._modified_by = obj_dict.get("_modified_by", "system")
    
    def to_dict(self) -> Dict:
        """Convert to dictionary with version info"""
        result = dict(self.data)
        result["_version"] = self._version
        result["_last_modified"] = self._last_modified
        result["_modified_by"] = self._modified_by
        return result
    
    @staticmethod
    def from_dict(data: Dict) -> "VersionedObject":
        return VersionedObject(data)


class ConcurrentStorageManager:
    """Storage manager with optimistic concurrency control"""
    
    def __init__(self, storage_manager):
        self.storage = storage_manager
        self.transaction_log = []
    
    def get_with_version(self, obj_id: str, collection_name: str) -> Optional[VersionedObject]:
        """Get object with version info"""
        
        collection = getattr(self.storage, collection_name)
        obj_dict = collection.get(obj_id)
        
        if not obj_dict:
            return None
        
        # Add version if not present
        if "_version" not in obj_dict:
            obj_dict["_version"] = 1
            obj_dict["_last_modified"] = datetime.now().isoformat()
            obj_dict["_modified_by"] = "system"
        
        return VersionedObject(obj_dict)
    
    def update_with_version_check(self,
                                 obj_id: str,
                                 updated_obj: Dict,
                                 expected_version: int,
                                 collection_name: str,
                                 modified_by: str = "system") -> Dict:
        """
        Update only if version matches (Optimistic Concurrency Control)
        
        Raises ConcurrencyError if object was modified by another process
        """
        
        # 1. Get current version
        current = self.get_with_version(obj_id, collection_name)
        
        if not current:
            raise ValueError(f"Object not found: {obj_id}")
        
        # 2. Check if version matches
        if current._version != expected_version:
            raise ConcurrencyError(
                f"Object {obj_id} was modified by another process. "
                f"Expected version {expected_version}, got {current._version}"
            )
        
        # 3. Update version and metadata
        updated_obj["_version"] = expected_version + 1
        updated_obj["_last_modified"] = datetime.now().isoformat()
        updated_obj["_modified_by"] = modified_by
        
        # 4. Log transaction
        self._log_transaction(
            "update",
            obj_id,
            collection_name,
            expected_version,
            expected_version + 1,
            modified_by
        )
        
        # 5. Write to storage
        collection = getattr(self.storage, collection_name)
        collection.save(obj_id, updated_obj)
        
        return updated_obj
    
    def _log_transaction(self,
                        operation: str,
                        obj_id: str,
                        collection: str,
                        old_version: int,
                        new_version: int,
                        modified_by: str):
        """Log transaction for audit trail"""
        
        log_entry = {
            "id": generate_id("txn"),
            "operation": operation,
            "object_id": obj_id,
            "collection": collection,
            "old_version": old_version,
            "new_version": new_version,
            "modified_by": modified_by,
            "timestamp": datetime.now().isoformat()
        }
        
        self.transaction_log.append(log_entry)
    
    def get_transaction_history(self, obj_id: str) -> list:
        """Get all transactions for an object"""
        return [t for t in self.transaction_log if t["object_id"] == obj_id]


class TransactionLog:
    """Write-ahead log for durability"""
    
    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.log_file.parent.mkdir(exist_ok=True)
        self.pending_transactions = {}
    
    def begin_transaction(self, txn_id: str) -> None:
        """Start a new transaction"""
        
        log_entry = {
            "txn_id": txn_id,
            "status": "started",
            "timestamp": datetime.now().isoformat(),
            "operations": []
        }
        
        self.pending_transactions[txn_id] = log_entry
        self._write_log(log_entry)
    
    def add_operation(self, txn_id: str, operation: Dict) -> None:
        """Add operation to transaction"""
        
        if txn_id not in self.pending_transactions:
            raise ValueError(f"Transaction not found: {txn_id}")
        
        self.pending_transactions[txn_id]["operations"].append(operation)
        
        # Write to log
        self._write_log({
            "txn_id": txn_id,
            "status": "operation_added",
            "operation": operation
        })
    
    def commit_transaction(self, txn_id: str) -> None:
        """Commit transaction"""
        
        if txn_id not in self.pending_transactions:
            raise ValueError(f"Transaction not found: {txn_id}")
        
        self._write_log({
            "txn_id": txn_id,
            "status": "committed",
            "timestamp": datetime.now().isoformat()
        })
        
        del self.pending_transactions[txn_id]
    
    def abort_transaction(self, txn_id: str) -> None:
        """Abort transaction"""
        
        if txn_id in self.pending_transactions:
            self._write_log({
                "txn_id": txn_id,
                "status": "aborted",
                "timestamp": datetime.now().isoformat()
            })
            del self.pending_transactions[txn_id]
    
    def _write_log(self, entry: Dict) -> None:
        """Write entry to transaction log"""
        
        import json
        
        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    
    def get_pending_transactions(self) -> list:
        """Get all uncommitted transactions"""
        return list(self.pending_transactions.values())
    
    def recover_from_crash(self) -> list:
        """Recover uncommitted transactions from log"""
        
        import json
        
        if not self.log_file.exists():
            return []
        
        uncommitted = []
        current_txn = None
        
        with open(self.log_file, "r") as f:
            for line in f:
                entry = json.loads(line)
                
                if entry["status"] == "started":
                    current_txn = entry
                
                elif entry["status"] == "operation_added":
                    if current_txn:
                        current_txn["operations"].append(entry["operation"])
                
                elif entry["status"] == "committed":
                    if current_txn:
                        current_txn["is_committed"] = True
                        current_txn = None
                
                elif entry["status"] == "aborted":
                    current_txn = None
        
        # Return any uncommitted transactions
        return self.get_pending_transactions()


class SafePreferenceUpdater:
    """Safe preference updates with concurrency control"""
    
    def __init__(self, concurrent_storage: ConcurrentStorageManager):
        self.storage = concurrent_storage
    
    def update_preference_with_correction(self,
                                        pref_id: str,
                                        new_confidence: float,
                                        modified_by: str = "system") -> Dict:
        """
        Safely update preference with version checking
        
        Usage:
            pref = storage.get_with_version(pref_id, "preferences")
            updated = updater.update_preference_with_correction(
                pref_id,
                0.85,
                expected_version=pref._version
            )
        """
        
        # Get current version
        pref = self.storage.get_with_version(pref_id, "preferences")
        
        if not pref:
            raise ValueError(f"Preference not found: {pref_id}")
        
        # Update data
        pref_data = pref.to_dict()
        pref_data["confidence"] = new_confidence
        
        # Update with version check
        return self.storage.update_with_version_check(
            pref_id,
            pref_data,
            pref._version,
            "preferences",
            modified_by
        )


if __name__ == "__main__":
    # Test concurrency control
    from pathlib import Path
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir)
        
        # Create mock storage
        class MockCollection:
            def __init__(self):
                self.data = {}
            
            def get(self, obj_id):
                return self.data.get(obj_id)
            
            def save(self, obj_id, obj):
                self.data[obj_id] = obj
        
        class MockStorage:
            def __init__(self):
                self.preferences = MockCollection()
        
        mock_storage = MockStorage()
        
        # Add test data
        test_pref = {
            "id": "test_pref",
            "name": "tables",
            "confidence": 0.7,
            "_version": 1,
            "_last_modified": datetime.now().isoformat(),
            "_modified_by": "system"
        }
        mock_storage.preferences.save("test_pref", test_pref)
        
        # Test concurrent access
        concurrent = ConcurrentStorageManager(mock_storage)
        
        print("\n✓ Getting preference with version:")
        pref = concurrent.get_with_version("test_pref", "preferences")
        print(f"  Version: {pref._version}")
        
        print("\n✓ Updating with correct version:")
        pref_data = pref.to_dict()
        pref_data["confidence"] = 0.85
        
        updated = concurrent.update_with_version_check(
            "test_pref",
            pref_data,
            expected_version=pref._version,
            collection_name="preferences",
            modified_by="test_agent"
        )
        print(f"  New version: {updated['_version']}")
        print(f"  New confidence: {updated['confidence']}")
        
        print("\n✓ Attempting update with stale version (should fail):")
        try:
            pref_data["confidence"] = 0.9
            concurrent.update_with_version_check(
                "test_pref",
                pref_data,
                expected_version=1,  # Wrong version
                collection_name="preferences"
            )
            print("  ERROR: Should have raised ConcurrencyError!")
        except ConcurrencyError as e:
            print(f"  ✓ Correctly caught: {str(e)[:50]}...")
        
        print("\n✓ Transaction log:")
        for txn in concurrent.transaction_log:
            print(f"  {txn['operation']} (v{txn['old_version']} → v{txn['new_version']})")
        
        print("\n✓ Concurrency control working correctly!")
