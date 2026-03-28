"""
auto_detector.py - Discovers new preference categories from observed behavior
"""

import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import re

sys.path.insert(0, str(Path(__file__).parent))

from models import Preference, Signal, generate_id
from storage import PreferenceStorageManager


class PatternWatcher:
    """Watches signals for recurring patterns"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
    
    def extract_recent_patterns(self, hours: int = 168) -> Dict[str, int]:
        """
        Extract patterns from recent signals (default: last week).
        Returns dict of pattern → frequency.
        """
        
        # Get recent signals
        cutoff = (datetime.fromisoformat(datetime.now().isoformat()) - 
                 timedelta(hours=hours)).isoformat()
        
        signals = self.storage.signals.read_filtered(
            lambda obj: obj.get("timestamp", "") >= cutoff
        )
        
        patterns = defaultdict(int)
        
        # Extract patterns from signals
        for signal in signals:
            # Pattern 1: Tool mentions
            task = signal.get("task", "")
            context_tags = signal.get("context_tags", [])
            
            for tag in context_tags:
                patterns[f"tool:{tag}"] += 1
            
            # Pattern 2: Correction patterns
            if signal.get("type") == "correction":
                proposed = signal.get("agent_proposed", "")
                corrected = signal.get("user_corrected_to", "")
                
                if proposed and corrected:
                    # They always correct X to Y
                    patterns[f"correction:{proposed}_to_{corrected}"] += 1
            
            # Pattern 3: Emotional patterns
            if signal.get("type") == "feedback":
                emotion = signal.get("emotional_tone", "")
                if emotion:
                    prefs_used = signal.get("preferences_used", [])
                    for pref in prefs_used:
                        patterns[f"emotion:{emotion}:{pref}"] += 1
        
        return dict(patterns)
    
    def find_co_occurrences(self, min_frequency: int = 3) -> Dict[str, int]:
        """
        Find items that appear together frequently.
        Returns dict of co_occurrence → count.
        """
        
        signals = self.storage.signals.get_all_signals()
        co_occurrences = defaultdict(int)
        
        for signal in signals:
            # Get all items in this signal
            items = set()
            
            # Add context tags
            for tag in signal.get("context_tags", []):
                items.add(f"context:{tag}")
            
            # Add preferences used
            for pref in signal.get("preferences_used", []):
                items.add(f"pref:{pref}")
            
            # Add emotional tone
            if signal.get("emotional_tone"):
                items.add(f"emotion:{signal['emotional_tone']}")
            
            # Record all pairs
            items_list = sorted(list(items))
            for i in range(len(items_list)):
                for j in range(i+1, len(items_list)):
                    pair = f"{items_list[i]}___{items_list[j]}"
                    co_occurrences[pair] += 1
        
        # Filter by minimum frequency
        return {k: v for k, v in co_occurrences.items() if v >= min_frequency}


class CategorySuggester:
    """Suggests new preference categories"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
        self.watcher = PatternWatcher(storage_manager)
    
    def suggest_from_tools(self) -> List[Dict]:
        """
        Suggest categories based on tool/framework detection.
        Example: "pytest appears with Python, suggest testing.framework"
        """
        
        patterns = self.watcher.extract_recent_patterns()
        co_occurrences = self.watcher.find_co_occurrences()
        
        suggestions = []
        
        # Known tool/framework patterns
        tool_categories = {
            "pytest": ("testing", "framework", "pytest"),
            "unittest": ("testing", "framework", "unittest"),
            "jest": ("testing", "framework", "jest"),
            "mocha": ("testing", "framework", "mocha"),
            "black": ("formatting", "tool", "black"),
            "prettier": ("formatting", "tool", "prettier"),
            "docker": ("deployment", "tool", "docker"),
            "kubernetes": ("deployment", "platform", "kubernetes"),
            "github": ("vcs", "platform", "github"),
            "gitlab": ("vcs", "platform", "gitlab"),
            "fastapi": ("framework", "web", "fastapi"),
            "django": ("framework", "web", "django"),
            "react": ("framework", "frontend", "react"),
            "vue": ("framework", "frontend", "vue"),
        }
        
        for tool, (cat1, cat2, cat3) in tool_categories.items():
            pattern_key = f"tool:{tool}"
            if pattern_key in patterns and patterns[pattern_key] >= 3:
                frequency = patterns[pattern_key]
                confidence = min(frequency / 10, 0.95)  # Normalize to 0-0.95
                
                # Find what it co-occurs with
                related = []
                for pair, count in co_occurrences.items():
                    if f"tool:{tool}" in pair:
                        parts = pair.split("___")
                        other = [p for p in parts if f"tool:{tool}" not in p]
                        if other:
                            related.append((other[0], count))
                
                suggestion = {
                    "id": generate_id("auto"),
                    "suggested_path": f"{cat1}.{cat2}.{cat3}",
                    "suggested_name": cat3,
                    "pattern": f"{tool} detected {frequency} times",
                    "confidence": confidence,
                    "related_items": sorted(related, key=lambda x: x[1], reverse=True)[:3],
                    "evidence_count": frequency,
                    "created": datetime.now().isoformat(),
                    "status": "suggested"
                }
                
                suggestions.append(suggestion)
        
        return sorted(suggestions, key=lambda x: x["confidence"], reverse=True)
    
    def suggest_from_clusters(self) -> List[Dict]:
        """
        Suggest categories based on preference clusters.
        Example: "These 4 preferences always used together, group them?"
        """
        
        # This will be populated after pattern_analyzer.py creates clusters
        # For now, return empty - will be implemented in pattern_analyzer integration
        return []
    
    def suggest_from_corrections(self) -> List[Dict]:
        """
        Suggest categories based on repeated corrections.
        Example: "You always correct X to Y, should create X category?"
        """
        
        patterns = self.watcher.extract_recent_patterns()
        suggestions = []
        
        # Find repeated corrections
        for pattern, frequency in patterns.items():
            if pattern.startswith("correction:") and frequency >= 2:
                parts = pattern.replace("correction:", "").split("_to_")
                if len(parts) == 2:
                    from_pref, to_pref = parts
                    confidence = min(frequency / 5, 0.90)
                    
                    suggestion = {
                        "id": generate_id("auto"),
                        "suggested_path": f"workflow.correction_pattern.{to_pref}",
                        "suggested_name": f"prefer_{to_pref}",
                        "pattern": f"Always correct {from_pref} to {to_pref}",
                        "confidence": confidence,
                        "evidence_count": frequency,
                        "created": datetime.now().isoformat(),
                        "status": "suggested"
                    }
                    suggestions.append(suggestion)
        
        return sorted(suggestions, key=lambda x: x["confidence"], reverse=True)
    
    def get_all_suggestions(self) -> List[Dict]:
        """Get all suggestions ranked by confidence"""
        
        all_suggestions = (
            self.suggest_from_tools() +
            self.suggest_from_clusters() +
            self.suggest_from_corrections()
        )
        
        # Deduplicate by path
        seen = {}
        unique = []
        for sugg in all_suggestions:
            path = sugg["suggested_path"]
            if path not in seen or seen[path]["confidence"] < sugg["confidence"]:
                if path in seen:
                    unique.remove(seen[path])
                seen[path] = sugg
                unique.append(sugg)
        
        return sorted(unique, key=lambda x: x["confidence"], reverse=True)


class AutoDetectionManager:
    """Manage auto-detected categories"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
        self.suggester = CategorySuggester(storage_manager)
    
    def get_suggestions(self) -> List[Dict]:
        """Get all current suggestions"""
        return self.suggester.get_all_suggestions()
    
    def accept_suggestion(self, suggestion_id: str) -> Preference:
        """
        Accept a suggestion and create the preference.
        Returns the created Preference.
        """
        
        # Get suggestion
        suggestions = self.get_suggestions()
        suggestion = next((s for s in suggestions if s["id"] == suggestion_id), None)
        
        if not suggestion:
            raise ValueError(f"Suggestion not found: {suggestion_id}")
        
        # Create preference
        pref = Preference(
            id=generate_id("pref"),
            path=suggestion["suggested_path"],
            parent_id=None,  # Will be hierarchical in future
            name=suggestion["suggested_name"],
            type="selector",
            confidence=suggestion["confidence"],
            description=f"Auto-detected: {suggestion['pattern']}",
            auto_detected=True
        )
        
        self.storage.preferences.save_preference(pref)
        
        return pref
    
    def reject_suggestion(self, suggestion_id: str) -> None:
        """Mark suggestion as rejected (not persisted, just memory)"""
        # In future versions, could track rejections to avoid re-suggesting
        pass
    
    def batch_accept(self, confidence_threshold: float = 0.80) -> List[Preference]:
        """
        Auto-accept suggestions above confidence threshold.
        Returns list of created preferences.
        """
        
        suggestions = self.get_suggestions()
        high_confidence = [s for s in suggestions if s["confidence"] >= confidence_threshold]
        
        created = []
        for sugg in high_confidence:
            try:
                pref = self.accept_suggestion(sugg["id"])
                created.append(pref)
            except Exception as e:
                print(f"❌ Failed to create from {sugg['suggested_path']}: {e}")
        
        return created


if __name__ == "__main__":
    # Quick test
    storage = PreferenceStorageManager("/tmp/test_auto_detect")
    manager = AutoDetectionManager(storage)
    
    # Add some test signals
    from models import Signal
    
    signal1 = Signal(
        id=generate_id("sig"),
        timestamp=datetime.now().isoformat(),
        type="correction",
        task="testing",
        context_tags=["python", "pytest"],
        user_response="Great testing framework"
    )
    storage.signals.save_signal(signal1)
    
    signal2 = Signal(
        id=generate_id("sig"),
        timestamp=datetime.now().isoformat(),
        type="correction",
        task="testing",
        context_tags=["python", "pytest"],
        user_response="pytest is perfect"
    )
    storage.signals.save_signal(signal2)
    
    signal3 = Signal(
        id=generate_id("sig"),
        timestamp=datetime.now().isoformat(),
        type="feedback",
        task="code_format",
        context_tags=["python", "black"],
        user_response="Black formatting excellent"
    )
    storage.signals.save_signal(signal3)
    
    # Get suggestions
    suggestions = manager.get_suggestions()
    print(f"\n🤖 Auto-Detected Suggestions ({len(suggestions)}):\n")
    
    for sugg in suggestions[:5]:
        print(f"✓ {sugg['suggested_path']}")
        print(f"  Pattern: {sugg['pattern']}")
        print(f"  Confidence: {sugg['confidence']:.0%}")
        print(f"  Evidence: {sugg['evidence_count']} occurrences\n")
