"""
user_feedback_system.py - User-visible feedback on preference learning
Addresses Lisa Thompson (Product/UX) critical gap: "System is invisible to users"
Addresses Priya Sharma (Behavioral) critical gap: "No feedback loop"
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent))

from models import Preference, Association, Signal, generate_id
from storage import PreferenceStorageManager


@dataclass
class UserFeedback:
    """Feedback shown to user about system learning"""
    
    id: str
    type: str  # "preference_learned", "milestone_reached", "progress_update"
    timestamp: str
    message: str
    confidence: float
    metadata: Dict  # Additional data (old value, new value, etc.)
    
    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "timestamp": self.timestamp,
            "message": self.message,
            "confidence": self.confidence,
            "metadata": self.metadata
        }


class UserFeedbackSystem:
    """Generate user-visible feedback when system learns"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
        self.feedback_log = []
    
    def feedback_preference_learned(self,
                                   pref: Preference,
                                   confidence: float,
                                   learning_count: int) -> UserFeedback:
        """Generate feedback when a preference is learned"""
        
        pref_name = pref.name.replace('_', ' ').title()
        confidence_pct = int(confidence * 100)
        
        # Calculate progress to solidification
        progress = min(learning_count, 25)
        bar_filled = int((progress / 25) * 10)
        progress_bar = "█" * bar_filled + "░" * (10 - bar_filled)
        
        message = f"""
✓ LEARNED! I've got this one.

Preference: {pref_name}
Confidence: {confidence_pct}% {progress_bar}
Progress: {progress}/25 corrections to solidify this preference

Next time you're in this context, I'll suggest {pref_name}.
        """.strip()
        
        feedback = UserFeedback(
            id=generate_id("feedback"),
            type="preference_learned",
            timestamp=datetime.now().isoformat(),
            message=message,
            confidence=confidence,
            metadata={
                "preference_id": pref.id,
                "preference_name": pref.name,
                "confidence": confidence,
                "solidification_progress": progress
            }
        )
        
        self.feedback_log.append(feedback)
        return feedback
    
    def feedback_correction_accepted(self,
                                    from_pref: str,
                                    to_pref: str,
                                    context: str = "") -> UserFeedback:
        """Feedback when user corrects system"""
        
        message = f"""
✓ Got it! I'll remember this.

You corrected me: {from_pref.replace('_', ' ')} → {to_pref.replace('_', ' ')}

I'm building a memory of this preference.
Each correction strengthens it.
        """.strip()
        
        feedback = UserFeedback(
            id=generate_id("feedback"),
            type="correction_accepted",
            timestamp=datetime.now().isoformat(),
            message=message,
            confidence=0.5,
            metadata={
                "from": from_pref,
                "to": to_pref,
                "context": context
            }
        )
        
        self.feedback_log.append(feedback)
        return feedback
    
    def feedback_milestone_reached(self,
                                  milestone: str,
                                  pref_name: str) -> UserFeedback:
        """Feedback when preference reaches a milestone"""
        
        milestones = {
            "emerging": "🎯 Emerging Preference",
            "consolidating": "📈 Consolidating Preference",
            "stable": "🔒 STABLE PREFERENCE",
            "strong": "⭐ Strong Preference"
        }
        
        messages = {
            "emerging": f"I'm starting to understand your preference for {pref_name}. (3 corrections detected)",
            "consolidating": f"Pattern confirmed! Your {pref_name} preference is taking shape. (7 corrections)",
            "stable": f"✨ LOCKED IN: {pref_name} is now a core preference I'll use automatically.",
            "strong": f"🎯 EXPERT LEVEL: I know {pref_name} better than you do now. (25+ corrections)"
        }
        
        message = f"""
{milestones.get(milestone, '📊')} {pref_name}

{messages.get(milestone, 'New preference milestone reached!')}
        """.strip()
        
        feedback = UserFeedback(
            id=generate_id("feedback"),
            type="milestone_reached",
            timestamp=datetime.now().isoformat(),
            message=message,
            confidence=0.8,
            metadata={
                "milestone": milestone,
                "preference": pref_name
            }
        )
        
        self.feedback_log.append(feedback)
        return feedback
    
    def feedback_cluster_discovered(self,
                                   members: List[str],
                                   co_occurrence_rate: float) -> UserFeedback:
        """Feedback when cluster is discovered"""
        
        member_names = [m.replace('_', ' ') for m in members[:3]]
        more = f"... + {len(members) - 3} more" if len(members) > 3 else ""
        
        message = f"""
🔗 PATTERN DISCOVERED!

You use these together {int(co_occurrence_rate * 100)}% of the time:
• {member_names[0]}
• {member_names[1] if len(member_names) > 1 else ''}
{more}

I'll suggest the whole group when I detect one of them.
        """.strip()
        
        feedback = UserFeedback(
            id=generate_id("feedback"),
            type="cluster_discovered",
            timestamp=datetime.now().isoformat(),
            message=message,
            confidence=co_occurrence_rate,
            metadata={
                "cluster_members": members,
                "co_occurrence_rate": co_occurrence_rate
            }
        )
        
        self.feedback_log.append(feedback)
        return feedback
    
    def feedback_summary_weekly(self) -> UserFeedback:
        """Weekly summary of learning"""
        
        preferences = self.storage.preferences.get_all_preferences()
        signals = self.storage.signals.get_recent_signals(hours=168)  # 1 week
        
        corrections_this_week = sum(1 for s in signals if s.get("type") == "correction")
        positive_feedback = sum(1 for s in signals if s.get("emotional_tone") in ["satisfied", "happy"])
        
        message = f"""
📊 THIS WEEK'S LEARNING

Corrections made: {corrections_this_week}
Positive feedback: {positive_feedback}
Preferences refined: {min(preferences.__len__(), 5)}

Most confident preference: [TBD based on data]
Fastest growing: [TBD based on trends]

Keep correcting me and I'll get better! 🚀
        """.strip()
        
        feedback = UserFeedback(
            id=generate_id("feedback"),
            type="weekly_summary",
            timestamp=datetime.now().isoformat(),
            message=message,
            confidence=0.8,
            metadata={
                "corrections": corrections_this_week,
                "positive_feedback": positive_feedback,
                "total_preferences": len(preferences)
            }
        )
        
        self.feedback_log.append(feedback)
        return feedback
    
    def get_recent_feedback(self, count: int = 5) -> List[UserFeedback]:
        """Get recent feedback messages"""
        return self.feedback_log[-count:]
    
    def display_feedback(self, feedback: UserFeedback) -> str:
        """Format feedback for display to user"""
        return f"\n{feedback.message}\n"


class MilestoneTracker:
    """Track when preferences reach milestones"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
    
    def check_milestones(self, pref_id: str) -> Optional[str]:
        """Check if preference just hit a milestone"""
        
        pref = self.storage.preferences.get_preference(pref_id)
        if not pref:
            return None
        
        use_count = pref.learning.use_count if pref.learning else 0
        
        # Milestone thresholds
        if use_count == 3:
            return "emerging"
        elif use_count == 7:
            return "consolidating"
        elif use_count == 15:
            return "stable"
        elif use_count == 25:
            return "strong"
        
        return None
    
    def check_all_milestones(self) -> List[Dict]:
        """Check all preferences for new milestones"""
        
        milestones = []
        preferences = self.storage.preferences.get_all_preferences()
        
        for pref in preferences:
            milestone = self.check_milestones(pref.id)
            if milestone:
                milestones.append({
                    "preference_id": pref.id,
                    "preference_name": pref.name,
                    "milestone": milestone
                })
        
        return milestones


if __name__ == "__main__":
    # Test
    storage = PreferenceStorageManager("/tmp/test_feedback")
    
    # Create test preference
    from models import Preference
    pref = Preference(
        id="pref_tables",
        path="communication.output_format.tables",
        parent_id=None,
        name="tables",
        type="variant",
        confidence=0.75
    )
    storage.preferences.save_preference(pref)
    
    # Test feedback system
    feedback_system = UserFeedbackSystem(storage)
    
    # Test different feedback types
    f1 = feedback_system.feedback_preference_learned(pref, 0.75, 5)
    print("\n📝 Preference Learned Feedback:")
    print(feedback_system.display_feedback(f1))
    
    f2 = feedback_system.feedback_correction_accepted("bullets", "tables", "API documentation")
    print("\n📝 Correction Accepted Feedback:")
    print(feedback_system.display_feedback(f2))
    
    f3 = feedback_system.feedback_milestone_reached("emerging", "Table Format")
    print("\n📝 Milestone Reached Feedback:")
    print(feedback_system.display_feedback(f3))
    
    f4 = feedback_system.feedback_cluster_discovered(
        ["tables", "data_structures", "documentation"],
        0.95
    )
    print("\n📝 Cluster Discovered Feedback:")
    print(feedback_system.display_feedback(f4))
    
    print(f"\n✓ Total feedback items logged: {len(feedback_system.feedback_log)}")
