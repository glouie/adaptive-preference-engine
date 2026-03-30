"""
query_index.py - In-memory indexing for fast preference queries at scale
Provides O(1) and O(log n) lookups instead of O(n) full scans
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
from bisect import bisect_left, bisect_right
from scripts.models import Preference, Association, Signal
from scripts.storage import PreferenceStorageManager


class QueryIndex:
    """In-memory index for fast preference queries"""

    def __init__(self):
        """Initialize all indexes"""
        # path_prefix_index: {"communication": ["comm_bullets", "comm_table"], ...}
        self.path_prefix_index: Dict[str, List[str]] = {}

        # id_index: {"comm_bullets": Preference(...), ...}
        self.id_index: Dict[str, Preference] = {}

        # type_index: {"variant": ["id1", "id2"], "selector": [...], ...}
        self.type_index: Dict[str, List[str]] = {}

        # context_index: {"task_analysis": ["signal_id1", ...], ...}
        self.context_index: Dict[str, List[str]] = {}

        # confidence_index: [(0.5, "id1"), (0.7, "id2"), ...] sorted by confidence
        self.confidence_index: List[Tuple[float, str]] = []

        # association_index: {"from_id": [Association(...), ...], ...}
        self.association_index: Dict[str, List[Association]] = {}

        # signal_index: {"signal_type": [Signal(...), ...], ...}
        self.signal_index: Dict[str, List[Signal]] = {}

        # Track stats
        self._built_at: Optional[str] = None
        self._preference_count: int = 0
        self._association_count: int = 0
        self._signal_count: int = 0

    def build(self, storage_manager: PreferenceStorageManager) -> None:
        """Build all indexes from storage manager"""
        self._clear_indexes()

        # Index preferences
        preferences = storage_manager.preferences.get_all_preferences()
        for pref in preferences:
            self._index_preference(pref)

        # Index associations
        associations = storage_manager.associations.get_all_associations()
        for assoc in associations:
            self._index_association(assoc)

        # Index signals
        signals = storage_manager.signals.get_all_signals()
        for signal in signals:
            self._index_signal(signal)

        # Sort confidence index
        self.confidence_index.sort(key=lambda x: x[0])

        self._built_at = datetime.now().isoformat()
        self._preference_count = len(preferences)
        self._association_count = len(associations)
        self._signal_count = len(signals)

    def _clear_indexes(self) -> None:
        """Clear all indexes"""
        self.path_prefix_index.clear()
        self.id_index.clear()
        self.type_index.clear()
        self.context_index.clear()
        self.confidence_index.clear()
        self.association_index.clear()
        self.signal_index.clear()

    def _index_preference(self, pref: Preference) -> None:
        """Index a single preference"""
        # Add to id_index
        self.id_index[pref.id] = pref

        # Add to type_index (check for duplicates)
        if pref.type not in self.type_index:
            self.type_index[pref.type] = []
        if pref.id not in self.type_index[pref.type]:
            self.type_index[pref.type].append(pref.id)

        # Add to path_prefix_index (split path by dots)
        path_parts = pref.path.split(".")
        for i in range(len(path_parts)):
            prefix = ".".join(path_parts[:i+1])
            if prefix not in self.path_prefix_index:
                self.path_prefix_index[prefix] = []
            if pref.id not in self.path_prefix_index[prefix]:
                self.path_prefix_index[prefix].append(pref.id)

        # Add to confidence_index (as tuple, will be sorted later)
        # Check if already exists to avoid duplicates
        if not any(pid == pref.id for _, pid in self.confidence_index):
            self.confidence_index.append((pref.confidence, pref.id))

    def _index_association(self, assoc: Association) -> None:
        """Index a single association"""
        # Create index entries for both directions
        for direction_id in [assoc.from_id, assoc.to_id]:
            if direction_id not in self.association_index:
                self.association_index[direction_id] = []
            self.association_index[direction_id].append(assoc)

    def _index_signal(self, signal: Signal) -> None:
        """Index a single signal"""
        # Index by signal type
        if signal.type not in self.signal_index:
            self.signal_index[signal.type] = []
        self.signal_index[signal.type].append(signal)

        # Index by context tags
        for tag in signal.context_tags:
            if tag not in self.context_index:
                self.context_index[tag] = []
            self.context_index[tag].append(signal.id)

    # ========== Query Methods ==========

    def find_by_path_prefix(self, prefix: str) -> List[str]:
        """
        Find preference IDs by path prefix
        Fast O(1) lookup after index build

        Args:
            prefix: Path prefix (e.g., "communication" or "communication.output_format")

        Returns:
            List of preference IDs matching prefix
        """
        return self.path_prefix_index.get(prefix, [])

    def find_by_id(self, pref_id: str) -> Optional[Preference]:
        """
        Find preference by ID
        O(1) lookup

        Args:
            pref_id: Preference ID

        Returns:
            Preference object or None
        """
        return self.id_index.get(pref_id)

    def find_by_type(self, pref_type: str) -> List[str]:
        """
        Find preference IDs by type
        O(1) lookup after index build

        Args:
            pref_type: Type ("variant", "selector", "property")

        Returns:
            List of preference IDs with this type
        """
        return self.type_index.get(pref_type, [])

    def find_by_confidence_range(self, min_conf: float, max_conf: float) -> List[str]:
        """
        Find preference IDs within confidence range
        O(log n + k) where k = results
        Uses binary search on sorted confidence index

        Args:
            min_conf: Minimum confidence (0.0-1.0)
            max_conf: Maximum confidence (0.0-1.0)

        Returns:
            List of preference IDs in confidence range
        """
        if not self.confidence_index:
            return []

        # Find start index where confidence >= min_conf
        start_idx = bisect_left(self.confidence_index, (min_conf, ""))

        # Find end index where confidence <= max_conf
        end_idx = bisect_right(self.confidence_index, (max_conf, "\uffff"))

        return [pref_id for _, pref_id in self.confidence_index[start_idx:end_idx]]

    def find_by_context(self, context_tag: str) -> List[str]:
        """
        Find signal IDs by context tag
        O(1) lookup after index build

        Args:
            context_tag: Context tag (e.g., "code_review")

        Returns:
            List of signal IDs with this context tag
        """
        return self.context_index.get(context_tag, [])

    def find_associations_for(self, pref_id: str) -> List[Association]:
        """
        Find all associations involving a preference (either direction)
        O(1) lookup after index build

        Args:
            pref_id: Preference ID

        Returns:
            List of Association objects
        """
        return self.association_index.get(pref_id, [])

    def find_signals_by_type(self, signal_type: str) -> List[Signal]:
        """
        Find signals by type
        O(1) lookup after index build

        Args:
            signal_type: Signal type ("correction", "feedback", "usage", "override")

        Returns:
            List of Signal objects
        """
        return self.signal_index.get(signal_type, [])

    # ========== Update Methods ==========

    def update(self, preference: Preference) -> None:
        """
        Incrementally update a preference without rebuilding entire index
        More efficient than calling build() again

        Args:
            preference: Updated Preference object
        """
        # Check if this is a new preference
        is_new = preference.id not in self.id_index

        # Remove old preference from indexes if it exists
        if not is_new:
            old_pref = self.id_index[preference.id]
            self._remove_from_type_index(old_pref)
            self._remove_from_path_prefix_index(old_pref)
            self._remove_from_confidence_index(old_pref)

        # Add new preference to indexes
        self._index_preference(preference)

        # Resort confidence index (only affected entries)
        self.confidence_index.sort(key=lambda x: x[0])

        # Update count if new
        if is_new:
            self._preference_count += 1

    def _remove_from_type_index(self, pref: Preference) -> None:
        """Remove preference from type index"""
        if pref.type in self.type_index:
            try:
                self.type_index[pref.type].remove(pref.id)
                if not self.type_index[pref.type]:
                    del self.type_index[pref.type]
            except ValueError:
                pass

    def _remove_from_path_prefix_index(self, pref: Preference) -> None:
        """Remove preference from path prefix index"""
        path_parts = pref.path.split(".")
        for i in range(len(path_parts)):
            prefix = ".".join(path_parts[:i+1])
            if prefix in self.path_prefix_index:
                try:
                    self.path_prefix_index[prefix].remove(pref.id)
                    if not self.path_prefix_index[prefix]:
                        del self.path_prefix_index[prefix]
                except ValueError:
                    pass

    def _remove_from_confidence_index(self, pref: Preference) -> None:
        """Remove preference from confidence index"""
        self.confidence_index = [
            (conf, pid) for conf, pid in self.confidence_index
            if pid != pref.id
        ]

    def remove(self, preference_id: str) -> bool:
        """
        Remove a preference from all indexes

        Args:
            preference_id: ID of preference to remove

        Returns:
            True if removed, False if not found
        """
        pref = self.id_index.get(preference_id)
        if not pref:
            return False

        # Remove from all indexes
        del self.id_index[preference_id]
        self._remove_from_type_index(pref)
        self._remove_from_path_prefix_index(pref)
        self._remove_from_confidence_index(pref)

        # Update count
        self._preference_count -= 1

        return True

    # ========== Statistics ==========

    def get_stats(self) -> Dict[str, Any]:
        """
        Get index statistics and metadata

        Returns:
            Dict with index statistics
        """
        return {
            "built_at": self._built_at,
            "preference_count": self._preference_count,
            "association_count": self._association_count,
            "signal_count": self._signal_count,
            "id_index_size": len(self.id_index),
            "type_index_size": len(self.type_index),
            "path_prefix_index_size": len(self.path_prefix_index),
            "context_index_size": len(self.context_index),
            "confidence_index_size": len(self.confidence_index),
            "association_index_size": len(self.association_index),
            "signal_index_size": len(self.signal_index),
            "types": list(self.type_index.keys()),
            "context_tags": list(self.context_index.keys()),
            "signal_types": list(self.signal_index.keys())
        }

    # ========== Persistence ==========

    def save(self, index_dir: Optional[str] = None) -> str:
        """
        Serialize indexes to JSON for fast startup

        Args:
            index_dir: Directory to save indexes (default: ~/.adaptive-cli/indexes/)

        Returns:
            Path to saved index directory
        """
        if index_dir is None:
            index_dir = os.path.expanduser("~/.adaptive-cli/indexes")

        index_path = Path(index_dir)
        index_path.mkdir(parents=True, exist_ok=True)

        # Serialize indexes that can be JSON serialized
        indexes = {
            "built_at": self._built_at,
            "preference_count": self._preference_count,
            "association_count": self._association_count,
            "signal_count": self._signal_count,
            "path_prefix_index": self.path_prefix_index,
            "type_index": self.type_index,
            "context_index": self.context_index,
            "confidence_index": self.confidence_index,
        }

        index_file = index_path / "index.json"
        with open(index_file, 'w') as f:
            json.dump(indexes, f, indent=2)

        return str(index_path)

    def load(self, index_dir: Optional[str] = None) -> bool:
        """
        Load indexes from saved JSON
        Note: id_index, association_index, signal_index must be rebuilt
        from storage since they contain object references

        Args:
            index_dir: Directory to load indexes from

        Returns:
            True if loaded successfully, False if file not found
        """
        if index_dir is None:
            index_dir = os.path.expanduser("~/.adaptive-cli/indexes")

        index_file = Path(index_dir) / "index.json"

        if not index_file.exists():
            return False

        try:
            with open(index_file, 'r') as f:
                data = json.load(f)

            self._built_at = data.get("built_at")
            self._preference_count = data.get("preference_count", 0)
            self._association_count = data.get("association_count", 0)
            self._signal_count = data.get("signal_count", 0)

            self.path_prefix_index = data.get("path_prefix_index", {})
            self.type_index = data.get("type_index", {})
            self.context_index = data.get("context_index", {})

            # Convert confidence_index lists back to tuples for binary search
            conf_list = data.get("confidence_index", [])
            self.confidence_index = [tuple(item) if isinstance(item, list) else item for item in conf_list]

            return True
        except (json.JSONDecodeError, KeyError):
            return False


class IndexedStorageManager(PreferenceStorageManager):
    """
    Drop-in replacement for PreferenceStorageManager with query indexing
    Maintains QueryIndex alongside storage and returns indexed results
    """

    def __init__(self, base_dir: str = None, use_persisted_index: bool = True):
        """
        Initialize indexed storage manager

        Args:
            base_dir: Base directory for preferences
            use_persisted_index: Try to load persisted index on startup (faster)
        """
        super().__init__(base_dir)
        self.index = QueryIndex()

        # Try to load persisted index first
        index_loaded = False
        if use_persisted_index:
            index_dir = os.path.expanduser("~/.adaptive-cli/indexes")
            index_loaded = self.index.load(index_dir)

        # Always rebuild id_index, association_index, signal_index from storage
        # since they contain object references (not JSON serializable)
        if index_loaded:
            # Persisted structural indexes loaded, now rebuild object indexes
            self._rebuild_object_indexes()
        else:
            # Full build from storage
            self.index.build(self)

    def _rebuild_object_indexes(self) -> None:
        """Rebuild id_index, association_index, signal_index from storage"""
        # Index preferences
        preferences = self.preferences.get_all_preferences()
        for pref in preferences:
            self.index.id_index[pref.id] = pref

        # Index associations
        associations = self.associations.get_all_associations()
        for assoc in associations:
            self.index._index_association(assoc)

        # Index signals
        signals = self.signals.get_all_signals()
        for signal in signals:
            self.index._index_signal(signal)

        # Update stats
        self.index._preference_count = len(preferences)
        self.index._association_count = len(associations)
        self.index._signal_count = len(signals)

    def get_preference(self, pref_id: str) -> Optional[Preference]:
        """Get preference by ID using index (O(1))"""
        return self.index.find_by_id(pref_id)

    def find_preferences_by_path(self, path_prefix: str) -> List[Preference]:
        """Find preferences by path prefix using index"""
        pref_ids = self.index.find_by_path_prefix(path_prefix)
        return [self.index.find_by_id(pid) for pid in pref_ids if self.index.find_by_id(pid)]

    def find_preferences_by_type(self, pref_type: str) -> List[Preference]:
        """Find preferences by type using index"""
        pref_ids = self.index.find_by_type(pref_type)
        return [self.index.find_by_id(pid) for pid in pref_ids if self.index.find_by_id(pid)]

    def find_preferences_by_confidence_range(
        self, min_conf: float, max_conf: float
    ) -> List[Preference]:
        """Find preferences in confidence range using index"""
        pref_ids = self.index.find_by_confidence_range(min_conf, max_conf)
        return [self.index.find_by_id(pid) for pid in pref_ids if self.index.find_by_id(pid)]

    def find_associations_for(self, pref_id: str) -> List[Association]:
        """Find associations for preference using index"""
        return self.index.find_associations_for(pref_id)

    def find_signals_by_type(self, signal_type: str) -> List[Signal]:
        """Find signals by type using index"""
        return self.index.find_signals_by_type(signal_type)

    def save_preference(self, preference: Preference) -> None:
        """Save preference to storage and update index"""
        self.preferences.save_preference(preference)
        self.index.update(preference)

    def rebuild_index(self) -> None:
        """Rebuild the entire index from storage"""
        self.index.build(self)

    def persist_index(self) -> str:
        """Persist index to disk for faster startup"""
        return self.index.save()

    def get_index_stats(self) -> Dict[str, Any]:
        """Get comprehensive index statistics"""
        stats = self.index.get_stats()
        stats["storage_info"] = self.get_storage_info()
        return stats


if __name__ == "__main__":
    # Quick test
    from scripts.models import Preference, LearningData

    # Create test storage
    mgr = IndexedStorageManager("/tmp/test_indexed_cli")

    # Create test preferences
    prefs = [
        Preference(
            id="comm_bullets",
            path="communication.output_format.bullets",
            parent_id="comm_format",
            name="bullets",
            type="variant",
            value="active",
            confidence=0.85
        ),
        Preference(
            id="comm_table",
            path="communication.output_format.table",
            parent_id="comm_format",
            name="table",
            type="variant",
            value="active",
            confidence=0.65
        ),
        Preference(
            id="code_clarity",
            path="coding.data_structure_clarity",
            parent_id="coding",
            name="clarity",
            type="selector",
            value="high",
            confidence=0.92
        ),
    ]

    for pref in prefs:
        mgr.save_preference(pref)

    # Test queries
    print("=== Query Index Tests ===\n")

    # Test path prefix search
    comm_prefs = mgr.find_preferences_by_path("communication")
    print(f"By path 'communication': {[p.id for p in comm_prefs]}")

    # Test type search
    variants = mgr.find_preferences_by_type("variant")
    print(f"By type 'variant': {[p.id for p in variants]}")

    # Test confidence range
    high_conf = mgr.find_preferences_by_confidence_range(0.8, 1.0)
    print(f"Confidence 0.8-1.0: {[p.id for p in high_conf]}")

    # Test direct lookup
    pref = mgr.get_preference("code_clarity")
    print(f"\nDirect lookup 'code_clarity': {pref.name if pref else 'Not found'}")

    # Print stats
    stats = mgr.get_index_stats()
    print(f"\nIndex Statistics:")
    print(f"  Total preferences: {stats['preference_count']}")
    print(f"  Built at: {stats['built_at']}")
    print(f"  Preference types: {stats['types']}")

    # Test persistence
    index_dir = mgr.persist_index()
    print(f"\nIndex persisted to: {index_dir}")
