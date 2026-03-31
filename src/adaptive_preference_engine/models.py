"""
models.py - Core data models for adaptive preference engine
Defines Preference, Association, Context, Signal classes
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Literal
from datetime import datetime
import json
import uuid


@dataclass
class LearningData:
    """Learning metrics for preferences/associations"""
    use_count: int = 0
    last_used: str = field(default_factory=lambda: datetime.now().isoformat())
    first_detected: str = field(default_factory=lambda: datetime.now().isoformat())
    satisfaction_rate: float = 0.5  # 0.0 to 1.0
    trend: Literal["strongly_increasing", "increasing", "stable", "decreasing", "strongly_decreasing"] = "stable"
    velocity: float = 0.0  # Rate of change per week
    weekly_usage: List[int] = field(default_factory=list)  # Last 7 weeks
    significance_score: Optional[float] = None
    p_value: Optional[float] = None
    effect_size: Optional[float] = None
    autocorrelation: Optional[float] = None
    n_signals: Optional[int] = None
    fdr_significant: Optional[bool] = None
    
    def to_dict(self):
        return asdict(self)


@dataclass
class Preference:
    """Individual preference (variant or property)"""
    id: str
    path: str                    # e.g., "communication.output_format.bullets"
    parent_id: Optional[str]     # e.g., "comm_output_format"
    name: str                    # e.g., "bullets"
    type: Literal["selector", "variant", "property"]
    
    value: Optional[str] = None  # Current value (for selector/variant)
    confidence: float = 0.5      # 0.0 to 1.0
    
    description: str = ""
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    auto_detected: bool = False
    
    learning: LearningData = field(default_factory=LearningData)
    
    def to_dict(self):
        return {
            "id": self.id,
            "path": self.path,
            "parent_id": self.parent_id,
            "name": self.name,
            "type": self.type,
            "value": self.value,
            "confidence": self.confidence,
            "description": self.description,
            "created": self.created,
            "last_updated": self.last_updated,
            "auto_detected": self.auto_detected,
            "learning": self.learning.to_dict()
        }
    
    @staticmethod
    def from_dict(data):
        data = dict(data)
        learning_data = LearningData(**data.pop("learning", {}))
        return Preference(**data, learning=learning_data)


@dataclass
class AssociationLearning:
    """Learning data for one direction of association"""
    use_count: int = 0
    last_used: str = field(default_factory=lambda: datetime.now().isoformat())
    first_detected: str = field(default_factory=lambda: datetime.now().isoformat())
    trend: Literal["strongly_increasing", "increasing", "stable", "decreasing", "strongly_decreasing"] = "stable"
    velocity: float = 0.0
    weekly_usage: List[int] = field(default_factory=list)
    satisfaction_rate: float = 0.5
    
    def to_dict(self):
        return asdict(self)


@dataclass
class Association:
    """Bidirectional association between two preferences"""
    id: str
    from_id: str              # e.g., "communication.output_format.table"
    to_id: str                # e.g., "coding.data_structure_clarity"
    bidirectional: bool = True
    
    strength_forward: float = 0.5   # A → B strength
    strength_backward: float = 0.5  # B → A strength
    
    learning_forward: AssociationLearning = field(default_factory=AssociationLearning)
    learning_backward: AssociationLearning = field(default_factory=AssociationLearning)
    
    description: str = ""
    context_tags: List[str] = field(default_factory=list)
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    
    time_decay_factor: float = 0.98  # 2% per day
    last_decay_applied: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self):
        return {
            "id": self.id,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "bidirectional": self.bidirectional,
            "strength_forward": self.strength_forward,
            "strength_backward": self.strength_backward,
            "learning_forward": self.learning_forward.to_dict(),
            "learning_backward": self.learning_backward.to_dict(),
            "description": self.description,
            "context_tags": self.context_tags,
            "created": self.created,
            "time_decay_factor": self.time_decay_factor,
            "last_decay_applied": self.last_decay_applied
        }
    
    @staticmethod
    def from_dict(data):
        data = dict(data)
        learning_forward = AssociationLearning(**data.pop("learning_forward", {}))
        learning_backward = AssociationLearning(**data.pop("learning_backward", {}))
        return Association(**data, learning_forward=learning_forward, learning_backward=learning_backward)
    
    def get_strength_for_direction(self, from_id: str) -> float:
        """Get strength based on traversal direction"""
        if from_id == self.from_id:
            return self.strength_forward
        else:
            return self.strength_backward


@dataclass
class ContextStack:
    """Preference context (base, project, or conversation level)"""
    id: str
    name: str
    scope: Literal["base", "project", "conversation"]
    active: bool = True
    
    preferences: Dict[str, Dict] = field(default_factory=dict)  # {pref_id: {value, confidence, source}}
    stack_level: int = 0  # 0=base, 1=project, 2=conversation
    
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    last_used: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "scope": self.scope,
            "active": self.active,
            "preferences": self.preferences,
            "stack_level": self.stack_level,
            "created": self.created,
            "last_used": self.last_used
        }
    
    @staticmethod
    def from_dict(data):
        return ContextStack(**data)


@dataclass
class Signal:
    """Behavioral signal from user interaction (correction, feedback, usage)"""
    id: str
    timestamp: str
    type: Literal["correction", "feedback", "usage", "override"]
    
    task: Optional[str] = None           # Task context
    context_tags: List[str] = field(default_factory=list)
    
    # For correction type
    agent_proposed: Optional[str] = None
    user_corrected_to: Optional[str] = None
    
    # For feedback type
    user_response: Optional[str] = None
    emotional_tone: Optional[Literal["satisfied", "frustrated", "neutral", "unclear"]] = None
    emotional_indicators: List[str] = field(default_factory=list)
    
    # Affected items
    preferences_used: List[str] = field(default_factory=list)
    associations_affected: List[Dict] = field(default_factory=list)
    preferences_affected: List[Dict] = field(default_factory=list)
    
    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "type": self.type,
            "task": self.task,
            "context_tags": self.context_tags,
            "agent_proposed": self.agent_proposed,
            "user_corrected_to": self.user_corrected_to,
            "user_response": self.user_response,
            "emotional_tone": self.emotional_tone,
            "emotional_indicators": self.emotional_indicators,
            "preferences_used": self.preferences_used,
            "associations_affected": self.associations_affected,
            "preferences_affected": self.preferences_affected
        }
    
    @staticmethod
    def from_dict(data):
        return Signal(**data)


# Utility functions
def generate_id(prefix: str = "") -> str:
    """Generate unique ID"""
    unique = str(uuid.uuid4())[:8]
    return f"{prefix}_{unique}" if prefix else unique


def merge_contexts(contexts: List[ContextStack]) -> Dict[str, Dict]:
    """
    Merge context stack preferences.
    Later contexts override earlier ones.
    """
    merged = {}
    for context in contexts:
        merged.update(context.preferences)
    return merged


if __name__ == "__main__":
    # Quick test
    pref = Preference(
        id="test_bullets",
        path="communication.output_format.bullets",
        parent_id="comm_format",
        name="bullets",
        type="variant",
        value="active",
        confidence=0.85
    )
    
    print(json.dumps(pref.to_dict(), indent=2))
    
    assoc = Association(
        id="assoc_table_datastructure",
        from_id="communication.output_format.table",
        to_id="coding.data_structure_clarity",
        strength_forward=0.95,
        strength_backward=0.70
    )
    
    print(json.dumps(assoc.to_dict(), indent=2))
