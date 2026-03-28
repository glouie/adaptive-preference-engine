"""
suggestion_engine.py - Generates predictive preference suggestions
"""

import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from models import generate_id
from storage import PreferenceStorageManager
from pattern_analyzer import PatternManager, AffinityCalculator


class SuggestionEngine:
    """Generates preference suggestions based on context and patterns"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
        self.pattern_manager = PatternManager(storage_manager)
        self.affinity_calc = AffinityCalculator(storage_manager)
        self.min_suggestion_confidence = 0.60
    
    def suggest_for_context(self,
                           context_tags: List[str],
                           exclude_active: bool = True) -> List[Dict]:
        """
        Generate suggestions based on context.
        
        Algorithm:
        1. Find context preferences
        2. Locate their clusters
        3. Suggest non-context members with high cluster affinity
        """
        
        suggestions = []
        
        # Get clusters
        clusters = self.pattern_manager.get_clusters()
        
        # Find context preferences
        all_prefs = self.storage.preferences.get_all_preferences()
        context_prefs = set()
        
        for pref in all_prefs:
            for tag in context_tags:
                if tag.lower() in pref.path.lower() or tag.lower() == pref.name.lower():
                    context_prefs.add(pref.id)
        
        # Find applicable clusters (contain context prefs)
        for cluster in clusters:
            cluster_members = set(cluster["members"])
            
            # How many context prefs are in this cluster?
            overlap = context_prefs & cluster_members
            if not overlap:
                continue
            
            # Calculate match score
            match_score = len(overlap) / max(len(cluster_members), 1)
            
            if match_score < 0.3:  # Require at least 30% overlap
                continue
            
            # Suggest non-context members
            non_context = cluster_members - context_prefs
            
            for pref_id in non_context:
                pref = self.storage.preferences.get_preference(pref_id)
                if not pref:
                    continue
                
                # Calculate suggestion confidence
                # = cluster strength × match score
                suggestion_confidence = (
                    cluster["intra_cluster_strength"] * match_score
                )
                
                if suggestion_confidence >= self.min_suggestion_confidence:
                    suggestion = {
                        "id": generate_id("sugg"),
                        "preference_id": pref_id,
                        "preference_path": pref.path,
                        "preference_name": pref.name,
                        "confidence": suggestion_confidence,
                        "reason": f"Used with {', '.join([p.name for p in [self.storage.preferences.get_preference(oid) for oid in overlap] if p])} {cluster['co_occurrence_rate']:.0%} of the time",
                        "cluster_id": cluster["id"],
                        "cluster_strength": cluster["intra_cluster_strength"],
                        "created": datetime.now().isoformat(),
                        "source": "cluster"
                    }
                    
                    suggestions.append(suggestion)
        
        # Sort by confidence
        suggestions = sorted(
            suggestions,
            key=lambda x: x["confidence"],
            reverse=True
        )
        
        # Deduplicate
        seen = set()
        unique = []
        for sugg in suggestions:
            if sugg["preference_id"] not in seen:
                seen.add(sugg["preference_id"])
                unique.append(sugg)
        
        return unique
    
    def suggest_from_affinities(self,
                               active_preferences: List[str],
                               top_n: int = 5) -> List[Dict]:
        """
        Suggest preferences with high affinity to active preferences.
        """
        
        suggestions = []
        affinities = self.affinity_calc.calculate_all_affinities()
        
        # For each active preference, find high-affinity preferences
        affinity_scores = {}
        
        for active_pref in active_preferences:
            pref_affinities = self.affinity_calc.get_affinities_for_preference(active_pref)
            
            for pref_id, affinity in pref_affinities.items():
                if pref_id not in active_preferences:
                    if pref_id not in affinity_scores:
                        affinity_scores[pref_id] = []
                    affinity_scores[pref_id].append(affinity)
        
        # Calculate average affinity for each candidate
        for pref_id, affinities_list in affinity_scores.items():
            avg_affinity = sum(affinities_list) / len(affinities_list)
            
            if avg_affinity >= self.min_suggestion_confidence:
                pref = self.storage.preferences.get_preference(pref_id)
                if pref:
                    suggestion = {
                        "id": generate_id("sugg"),
                        "preference_id": pref_id,
                        "preference_path": pref.path,
                        "preference_name": pref.name,
                        "confidence": avg_affinity,
                        "reason": f"Has strong affinity ({avg_affinity:.0%}) with active preferences",
                        "source": "affinity",
                        "created": datetime.now().isoformat()
                    }
                    suggestions.append(suggestion)
        
        # Sort and return top N
        return sorted(
            suggestions,
            key=lambda x: x["confidence"],
            reverse=True
        )[:top_n]
    
    def suggest_based_on_recent_signals(self,
                                       hours: int = 24) -> List[Dict]:
        """
        Suggest based on recent behavioral signals.
        If user just corrected something multiple times, suggest related preferences.
        """
        
        suggestions = []
        
        # Get recent signals
        recent_signals = self.storage.signals.get_recent_signals(hours=hours)
        
        if not recent_signals:
            return []
        
        # Analyze patterns
        from collections import defaultdict
        preference_frequency = defaultdict(int)
        
        for signal in recent_signals:
            for pref in signal.get("preferences_used", []):
                preference_frequency[pref] += 1
        
        # Find frequently used preferences
        frequent = {pref: count for pref, count in preference_frequency.items() if count >= 2}
        
        if not frequent:
            return []
        
        # Suggest similar preferences
        for pref_id in frequent.keys():
            affinities = self.affinity_calc.get_affinities_for_preference(pref_id)
            
            for related_id, affinity in affinities.items():
                if related_id not in frequent and affinity >= self.min_suggestion_confidence:
                    pref = self.storage.preferences.get_preference(related_id)
                    if pref:
                        suggestion = {
                            "id": generate_id("sugg"),
                            "preference_id": related_id,
                            "preference_path": pref.path,
                            "preference_name": pref.name,
                            "confidence": affinity,
                            "reason": f"You've been using {self.storage.preferences.get_preference(pref_id).name} recently, consider {pref.name}",
                            "source": "recent_behavior",
                            "created": datetime.now().isoformat()
                        }
                        suggestions.append(suggestion)
        
        return sorted(
            suggestions,
            key=lambda x: x["confidence"],
            reverse=True
        )[:5]
    
    def rank_suggestions(self,
                        suggestions: List[Dict],
                        weights: Dict[str, float] = None) -> List[Dict]:
        """
        Rank suggestions using weighted scoring.
        
        Default weights:
        - cluster: 0.4
        - affinity: 0.3
        - recent_behavior: 0.3
        """
        
        if weights is None:
            weights = {
                "cluster": 0.4,
                "affinity": 0.3,
                "recent_behavior": 0.3
            }
        
        # Apply source weighting
        for sugg in suggestions:
            source = sugg.get("source", "cluster")
            weight = weights.get(source, 0.3)
            sugg["weighted_confidence"] = sugg["confidence"] * weight
        
        # Sort by weighted confidence
        return sorted(
            suggestions,
            key=lambda x: x["weighted_confidence"],
            reverse=True
        )
    
    def get_all_suggestions(self,
                           context_tags: List[str],
                           active_preferences: List[str] = None) -> List[Dict]:
        """
        Get all suggestions from all sources, ranked and deduplicated.
        """
        
        if active_preferences is None:
            active_preferences = []
        
        all_suggestions = []
        
        # Get suggestions from all sources
        all_suggestions.extend(self.suggest_for_context(context_tags))
        all_suggestions.extend(self.suggest_from_affinities(active_preferences))
        all_suggestions.extend(self.suggest_based_on_recent_signals())
        
        # Rank
        ranked = self.rank_suggestions(all_suggestions)
        
        # Deduplicate by preference_id
        seen = set()
        unique = []
        for sugg in ranked:
            pref_id = sugg["preference_id"]
            if pref_id not in seen and pref_id not in active_preferences:
                seen.add(pref_id)
                unique.append(sugg)
        
        return unique[:10]  # Return top 10


class SuggestionTracker:
    """Track suggestion effectiveness"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
    
    def record_suggestion_accepted(self, suggestion_id: str) -> None:
        """Record when user accepts a suggestion"""
        # Would track in database for effectiveness calculation
        pass
    
    def record_suggestion_rejected(self, suggestion_id: str) -> None:
        """Record when user ignores a suggestion"""
        pass
    
    def get_suggestion_effectiveness(self) -> Dict:
        """Calculate suggestion engine effectiveness"""
        
        # Placeholder: would calculate from tracked data
        return {
            "total_suggestions": 0,
            "accepted": 0,
            "rejected": 0,
            "acceptance_rate": 0.0,
            "avg_confidence_accepted": 0.0,
            "avg_confidence_rejected": 0.0
        }


if __name__ == "__main__":
    # Quick test
    storage = PreferenceStorageManager("/tmp/test_suggestions")
    
    # Create test data (same as pattern_analyzer test)
    from models import Preference, Association, Signal
    
    prefs = [
        Preference(id="pref_python", path="coding.language.python", parent_id=None, name="python", type="variant", confidence=0.9),
        Preference(id="pref_pytest", path="testing.framework.pytest", parent_id=None, name="pytest", type="variant", confidence=0.85),
        Preference(id="pref_tdd", path="workflow.testing.tdd", parent_id=None, name="tdd", type="variant", confidence=0.88),
        Preference(id="pref_bullets", path="communication.output_format.bullets", parent_id=None, name="bullets", type="variant", confidence=0.8),
    ]
    
    for pref in prefs:
        storage.preferences.save_preference(pref)
    
    # Create associations
    assocs = [
        Association(id="a1", from_id="pref_python", to_id="pref_pytest", strength_forward=0.9, strength_backward=0.8),
        Association(id="a2", from_id="pref_pytest", to_id="pref_tdd", strength_forward=0.85, strength_backward=0.8),
        Association(id="a3", from_id="pref_python", to_id="pref_tdd", strength_forward=0.88, strength_backward=0.85),
    ]
    
    for assoc in assocs:
        storage.associations.save_association(assoc)
    
    # Create signals
    for i in range(5):
        sig = Signal(
            id=generate_id("sig"),
            timestamp=datetime.now().isoformat(),
            type="usage",
            preferences_used=["pref_python", "pref_pytest", "pref_tdd"]
        )
        storage.signals.save_signal(sig)
    
    # Get suggestions
    engine = SuggestionEngine(storage)
    suggestions = engine.get_all_suggestions(
        context_tags=["python", "testing"],
        active_preferences=["pref_python"]
    )
    
    print("\n🔮 Predictive Suggestions:\n")
    for sugg in suggestions[:5]:
        print(f"✓ {sugg['preference_path']}")
        print(f"  Confidence: {sugg['confidence']:.0%}")
        print(f"  Reason: {sugg['reason']}\n")
