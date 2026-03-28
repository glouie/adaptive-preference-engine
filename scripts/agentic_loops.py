"""
agentic_loops.py - Executable preference rules and automation
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum

sys.path.insert(0, str(Path(__file__).parent))

from models import generate_id
from storage import PreferenceStorageManager
from preference_loader import PreferenceLoader


class TriggerType(Enum):
    """Types of triggers for agentic loops"""
    
    CONTEXT_MATCH = "context_match"           # Context tags match
    PREFERENCE_VALUE = "preference_value"     # Preference has specific value
    STRENGTH_THRESHOLD = "strength_threshold" # Association strength exceeds threshold
    SIGNAL_TYPE = "signal_type"               # Signal type (correction, feedback)
    TIME_BASED = "time_based"                 # Periodic trigger


class ActionType(Enum):
    """Types of actions agentic loops can execute"""
    
    SUGGEST_PREFERENCE = "suggest_preference"       # Add to suggestion queue
    REINFORCE_ASSOCIATION = "reinforce_association" # Boost association strength
    APPLY_PREFERENCE = "apply_preference"           # Set preference value
    CHAIN_PREFERENCE = "chain_preference"           # Enable cluster members
    LOG_EVENT = "log_event"                         # Record execution


class AgenticLoop:
    """Represents a single executable loop"""
    
    def __init__(self,
                 id: str = None,
                 name: str = "",
                 trigger: Dict = None,
                 actions: List[Dict] = None,
                 enabled: bool = True):
        
        self.id = id or generate_id("loop")
        self.name = name
        self.trigger = trigger or {}
        self.actions = actions or []
        self.enabled = enabled
        self.execution_count = 0
        self.success_count = 0
        self.created = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "trigger": self.trigger,
            "actions": self.actions,
            "enabled": self.enabled,
            "execution_count": self.execution_count,
            "success_count": self.success_count,
            "success_rate": self.success_count / max(self.execution_count, 1),
            "created": self.created
        }
    
    @staticmethod
    def from_dict(data: Dict) -> "AgenticLoop":
        loop = AgenticLoop(
            id=data.get("id"),
            name=data.get("name"),
            trigger=data.get("trigger"),
            actions=data.get("actions"),
            enabled=data.get("enabled", True)
        )
        loop.execution_count = data.get("execution_count", 0)
        loop.success_count = data.get("success_count", 0)
        loop.created = data.get("created", datetime.now().isoformat())
        return loop


class TriggerEvaluator:
    """Evaluates if loop trigger is met"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
    
    def evaluate_context_match(self, condition: Dict, context_tags: List[str]) -> bool:
        """Check if context tags match condition"""
        
        required_tags = condition.get("tags", [])
        task_contains = condition.get("task_contains", [])
        
        # All required tags must match
        context_lower = [tag.lower() for tag in context_tags]
        required_lower = [tag.lower() for tag in required_tags]
        
        if required_lower:
            if not all(req in context_lower for req in required_lower):
                return False
        
        # Task text matching
        if task_contains:
            # Would need task context - placeholder
            pass
        
        return True
    
    def evaluate_preference_value(self, condition: Dict, current_prefs: Dict) -> bool:
        """Check if preference has expected value"""
        
        pref_id = condition.get("preference_id")
        expected_value = condition.get("value")
        
        actual_value = current_prefs.get(pref_id, {}).get("value")
        
        return actual_value == expected_value
    
    def evaluate_strength_threshold(self, condition: Dict) -> bool:
        """Check if association strength exceeds threshold"""
        
        assoc_id = condition.get("association_id")
        threshold = condition.get("threshold", 0.70)
        
        assoc = self.storage.associations.get_association(assoc_id)
        
        if not assoc:
            return False
        
        # Check either direction
        direction = condition.get("direction", "forward")
        
        if direction == "forward":
            return assoc.strength_forward >= threshold
        elif direction == "backward":
            return assoc.strength_backward >= threshold
        else:
            return (assoc.strength_forward >= threshold or 
                   assoc.strength_backward >= threshold)
    
    def evaluate(self, trigger: Dict, context: Dict) -> bool:
        """Evaluate if trigger is met given context"""
        
        trigger_type = trigger.get("type")
        condition = trigger.get("condition", {})
        
        if trigger_type == TriggerType.CONTEXT_MATCH.value:
            return self.evaluate_context_match(condition, context.get("tags", []))
        
        elif trigger_type == TriggerType.PREFERENCE_VALUE.value:
            return self.evaluate_preference_value(condition, context.get("preferences", {}))
        
        elif trigger_type == TriggerType.STRENGTH_THRESHOLD.value:
            return self.evaluate_strength_threshold(condition)
        
        else:
            return False


class ActionExecutor:
    """Executes loop actions"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
    
    def execute_suggest_preference(self, action: Dict) -> Dict:
        """Add preference to suggestion queue"""
        
        pref_id = action.get("preference_id")
        confidence_threshold = action.get("confidence_threshold", 0.60)
        
        pref = self.storage.preferences.get_preference(pref_id)
        
        if not pref:
            return {"status": "error", "reason": f"Preference not found: {pref_id}"}
        
        return {
            "status": "success",
            "action": "suggest_preference",
            "preference_id": pref_id,
            "preference_name": pref.name,
            "suggested": True
        }
    
    def execute_reinforce_association(self, action: Dict) -> Dict:
        """Boost association strength"""
        
        from_id = action.get("from_id")
        to_ids = action.get("to_ids", [])
        strength_boost = action.get("strength_boost", 0.05)
        
        results = []
        
        for to_id in to_ids:
            assoc = self.storage.associations.get_association(f"{from_id}_{to_id}")
            
            if not assoc:
                # Try reverse
                assoc = self.storage.associations.get_association(f"{to_id}_{from_id}")
            
            if assoc:
                # Boost strength
                old_strength = assoc.strength_forward
                assoc.strength_forward = min(assoc.strength_forward + strength_boost, 1.0)
                self.storage.associations.save_association(assoc)
                
                results.append({
                    "association": f"{from_id} → {to_id}",
                    "old_strength": old_strength,
                    "new_strength": assoc.strength_forward,
                    "boosted": True
                })
        
        return {
            "status": "success",
            "action": "reinforce_association",
            "results": results
        }
    
    def execute_apply_preference(self, action: Dict) -> Dict:
        """Set preference value"""
        
        pref_id = action.get("preference_id")
        value = action.get("value")
        
        pref = self.storage.preferences.get_preference(pref_id)
        
        if not pref:
            return {"status": "error", "reason": f"Preference not found: {pref_id}"}
        
        old_value = pref.value
        pref.value = value
        self.storage.preferences.save_preference(pref)
        
        return {
            "status": "success",
            "action": "apply_preference",
            "preference_id": pref_id,
            "old_value": old_value,
            "new_value": value
        }
    
    def execute_chain_preference(self, action: Dict) -> Dict:
        """Enable related cluster preferences"""
        
        pref_id = action.get("preference_id")
        cluster_id = action.get("cluster_id")
        
        # Placeholder - would need cluster info
        return {
            "status": "success",
            "action": "chain_preference",
            "preference_id": pref_id,
            "chained": True
        }
    
    def execute_action(self, action: Dict) -> Dict:
        """Execute a single action"""
        
        action_type = action.get("type")
        
        if action_type == ActionType.SUGGEST_PREFERENCE.value:
            return self.execute_suggest_preference(action)
        
        elif action_type == ActionType.REINFORCE_ASSOCIATION.value:
            return self.execute_reinforce_association(action)
        
        elif action_type == ActionType.APPLY_PREFERENCE.value:
            return self.execute_apply_preference(action)
        
        elif action_type == ActionType.CHAIN_PREFERENCE.value:
            return self.execute_chain_preference(action)
        
        else:
            return {"status": "error", "reason": f"Unknown action type: {action_type}"}


class LoopExecutor:
    """Manages loop execution"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
        self.trigger_evaluator = TriggerEvaluator(storage_manager)
        self.action_executor = ActionExecutor(storage_manager)
    
    def execute_loop(self, loop: AgenticLoop, context: Dict) -> Dict:
        """Execute a single loop if trigger is met"""
        
        if not loop.enabled:
            return {"status": "disabled"}
        
        # Evaluate trigger
        trigger_met = self.trigger_evaluator.evaluate(loop.trigger, context)
        
        execution_record = {
            "loop_id": loop.id,
            "timestamp": datetime.now().isoformat(),
            "trigger_met": trigger_met,
            "actions_executed": [],
            "success": False
        }
        
        if not trigger_met:
            return execution_record
        
        # Execute actions
        all_success = True
        for action in loop.actions:
            result = self.action_executor.execute_action(action)
            execution_record["actions_executed"].append(result)
            
            if result.get("status") != "success":
                all_success = False
        
        execution_record["success"] = all_success
        
        # Update loop statistics
        loop.execution_count += 1
        if all_success:
            loop.success_count += 1
        
        self.storage.associations.save_association(loop)  # Placeholder - should save to separate store
        
        return execution_record
    
    def execute_all_loops(self, context: Dict) -> List[Dict]:
        """Execute all applicable loops"""
        
        # Placeholder - would retrieve loops from storage
        loops = []
        
        results = []
        for loop in loops:
            result = self.execute_loop(loop, context)
            results.append(result)
        
        return results


class LoopBuilder:
    """Helper to create agentic loops"""
    
    @staticmethod
    def create_context_trigger(name: str,
                              required_tags: List[str],
                              task_contains: List[str] = None) -> Dict:
        """Create a context-based trigger"""
        
        return {
            "type": TriggerType.CONTEXT_MATCH.value,
            "condition": {
                "tags": required_tags,
                "task_contains": task_contains or []
            }
        }
    
    @staticmethod
    def create_suggest_action(pref_id: str,
                             confidence_threshold: float = 0.70) -> Dict:
        """Create a suggestion action"""
        
        return {
            "type": ActionType.SUGGEST_PREFERENCE.value,
            "preference_id": pref_id,
            "confidence_threshold": confidence_threshold
        }
    
    @staticmethod
    def create_reinforce_action(from_id: str,
                               to_ids: List[str],
                               strength_boost: float = 0.05) -> Dict:
        """Create a reinforcement action"""
        
        return {
            "type": ActionType.REINFORCE_ASSOCIATION.value,
            "from_id": from_id,
            "to_ids": to_ids,
            "strength_boost": strength_boost
        }
    
    @staticmethod
    def build_loop(name: str,
                  trigger: Dict,
                  actions: List[Dict]) -> AgenticLoop:
        """Build an agentic loop"""
        
        return AgenticLoop(
            name=name,
            trigger=trigger,
            actions=actions,
            enabled=True
        )


if __name__ == "__main__":
    # Quick test
    storage = PreferenceStorageManager("/tmp/test_loops")
    
    # Create test preferences
    from models import Preference
    
    python_pref = Preference(
        id="pref_python",
        path="coding.language.python",
        parent_id=None,
        name="python",
        type="variant",
        confidence=0.9
    )
    
    tdd_pref = Preference(
        id="pref_tdd",
        path="workflow.testing.tdd",
        parent_id=None,
        name="tdd",
        type="variant",
        confidence=0.85
    )
    
    storage.preferences.save_preference(python_pref)
    storage.preferences.save_preference(tdd_pref)
    
    # Create loop
    builder = LoopBuilder()
    
    trigger = builder.create_context_trigger(
        name="Python context",
        required_tags=["python"],
        task_contains=["api"]
    )
    
    actions = [
        builder.create_suggest_action("pref_tdd"),
        builder.create_reinforce_action("pref_python", ["pref_tdd"])
    ]
    
    loop = builder.build_loop(
        name="Python API Development",
        trigger=trigger,
        actions=actions
    )
    
    print("\n⚙️ Agentic Loop:\n")
    print(f"Loop: {loop.name}")
    print(f"Trigger: {loop.trigger['condition']['tags']}")
    print(f"Actions: {len(loop.actions)}")
    for i, action in enumerate(loop.actions, 1):
        print(f"  {i}. {action['type']}")
    
    # Test execution
    executor = LoopExecutor(storage)
    context = {
        "tags": ["python", "api_design"],
        "preferences": {}
    }
    
    result = executor.execute_loop(loop, context)
    print(f"\nExecution result:")
    print(f"  Trigger met: {result['trigger_met']}")
    print(f"  Actions executed: {len(result['actions_executed'])}")
