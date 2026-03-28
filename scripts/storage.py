"""
storage.py - JSONL file storage and retrieval for preferences, associations, signals
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime
from scripts.models import Preference, Association, ContextStack, Signal


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
    
    def __init__(self, base_dir: str = None):
        """Initialize storage manager"""
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
        """Create timestamped backup of all preference files"""
        if backup_name is None:
            backup_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        backup_dir = self.base_dir / "backups" / backup_name
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        import shutil
        for file in self.preferences_dir.glob("*.jsonl"):
            shutil.copy(file, backup_dir / file.name)
        
        return str(backup_dir)
    
    def reset(self, confirm: bool = True) -> None:
        """Reset all preferences (with backup)"""
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
