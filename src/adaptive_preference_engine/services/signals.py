"""
signal_processor.py - Process behavioral signals (corrections, feedback) to learn and evolve preferences
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path
from adaptive_preference_engine.models import Signal, Association, AssociationLearning, generate_id
from adaptive_preference_engine.paths import get_base_dir
from adaptive_preference_engine.storage import PreferenceStorageManager
from adaptive_preference_engine.services.habits import HabitTracker
from scripts.bayesian_strength_calculator import BayesianStrengthCalculator
import json
import logging
import re


class FrictionMetrics:
    """Tracks attempt-to-success ratios for friction analysis"""

    def __init__(self, metrics_file: Path = None, base_dir: Optional[Path] = None):
        """
        Initialize friction metrics tracker.

        Args:
            metrics_file: Path to JSONL metrics file. Defaults to ~/.adaptive-cli/metrics.jsonl
        """
        if metrics_file is None:
            resolved_base_dir = Path(base_dir) if base_dir is not None else get_base_dir()
            resolved_base_dir.mkdir(parents=True, exist_ok=True)
            metrics_file = resolved_base_dir / "metrics.jsonl"

        self.metrics_file = Path(metrics_file)
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)

    def record_attempt(self, operation: str, success: bool, duration_ms: float = 0):
        """
        Record an attempt for an operation.

        Args:
            operation: Name of the operation (e.g., "correction", "feedback")
            success: Whether the operation succeeded
            duration_ms: Duration in milliseconds
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "success": success,
            "duration_ms": duration_ms
        }

        # Append to JSONL file
        with open(self.metrics_file, 'a') as f:
            f.write(json.dumps(record) + '\n')

    def get_success_rate(self, operation: str) -> float:
        """
        Get success rate for an operation.

        Args:
            operation: Name of the operation

        Returns:
            Success rate (0.0 to 1.0), or 0.0 if no records exist
        """
        if not self.metrics_file.exists():
            return 0.0

        attempts = 0
        successes = 0

        with open(self.metrics_file, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        record = json.loads(line)
                        if record.get("operation") == operation:
                            attempts += 1
                            if record.get("success"):
                                successes += 1
                    except json.JSONDecodeError:
                        continue

        if attempts == 0:
            return 0.0

        return successes / attempts

    def get_summary(self) -> dict:
        """
        Get summary of all operations.

        Returns:
            Dict mapping operation names to {attempts, successes, success_rate}
        """
        if not self.metrics_file.exists():
            return {}

        operations = {}

        with open(self.metrics_file, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        record = json.loads(line)
                        op = record.get("operation")
                        if op not in operations:
                            operations[op] = {"attempts": 0, "successes": 0}

                        operations[op]["attempts"] += 1
                        if record.get("success"):
                            operations[op]["successes"] += 1
                    except json.JSONDecodeError:
                        continue

        # Calculate success rates
        for op in operations:
            attempts = operations[op]["attempts"]
            successes = operations[op]["successes"]
            operations[op]["success_rate"] = successes / attempts if attempts > 0 else 0.0

        return operations


class PreferenceMatchResult:
    """Result of matching a correction against existing preferences."""

    def __init__(self, matched: bool, preference=None, similarity: float = 0.0,
                 match_type: str = "none"):
        self.matched = matched
        self.preference = preference
        self.similarity = similarity
        self.match_type = match_type  # "path", "value_keyword", "none"


class SignalProcessor:
    """Process behavioral signals to update preferences and associations"""

    # Minimum keyword overlap ratio to consider a match
    MATCH_THRESHOLD = 0.35

    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
        self._bayesian_calc = BayesianStrengthCalculator()

    # ---- Preference Matching ----

    def match_existing_preference(self, correction_text: str,
                                   task: str = "") -> PreferenceMatchResult:
        """Match a correction against existing preferences.

        Checks path overlap first, then keyword overlap against preference
        values. Returns the best match above MATCH_THRESHOLD.
        """
        all_prefs = self.storage.preferences.get_all_preferences()
        if not all_prefs:
            return PreferenceMatchResult(matched=False)

        correction_words = self._tokenize(correction_text)
        if not correction_words:
            return PreferenceMatchResult(matched=False)

        best_match = None
        best_score = 0.0
        best_type = "none"

        for pref in all_prefs:
            # Path-based matching: compare task/correction words against path segments
            path_words = set(pref.path.replace(".", " ").replace("_", " ").lower().split())
            path_overlap = len(correction_words & path_words) / max(len(path_words), 1)

            # Value-based matching: keyword overlap with preference value
            value_words = self._tokenize(pref.value or "")
            if value_words:
                overlap = len(correction_words & value_words)
                value_score = overlap / max(min(len(correction_words), len(value_words)), 1)
            else:
                value_score = 0.0

            # Take the better of path and value match
            if path_overlap >= value_score and path_overlap > best_score:
                best_score = path_overlap
                best_match = pref
                best_type = "path"
            elif value_score > best_score:
                best_score = value_score
                best_match = pref
                best_type = "value_keyword"

        if best_score >= self.MATCH_THRESHOLD and best_match is not None:
            return PreferenceMatchResult(
                matched=True,
                preference=best_match,
                similarity=best_score,
                match_type=best_type,
            )

        return PreferenceMatchResult(matched=False, similarity=best_score)

    @staticmethod
    def _tokenize(text: str) -> set:
        """Extract lowercase keyword tokens, dropping stop words."""
        stop_words = {
            "a", "an", "the", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "shall",
            "can", "to", "of", "in", "for", "on", "with", "at", "by",
            "from", "as", "into", "through", "during", "before", "after",
            "and", "but", "or", "nor", "not", "so", "yet", "both",
            "either", "neither", "each", "every", "all", "any", "few",
            "more", "most", "other", "some", "such", "no", "only", "own",
            "same", "than", "too", "very", "just", "because", "if", "when",
            "that", "this", "it", "its", "i", "me", "my", "we", "our",
            "you", "your", "he", "she", "they", "them", "their",
        }
        words = set(re.findall(r"[a-z][a-z0-9_]+", text.lower()))
        return words - stop_words

    def _create_metrics_tracker(self) -> FrictionMetrics:
        """Create a metrics tracker scoped to this storage manager."""
        return FrictionMetrics(base_dir=self.storage.base_dir)

    def _record_attempt_metrics(self, metrics: FrictionMetrics, operation: str, success: bool, start_time: datetime) -> None:
        """Best-effort metrics recording that never masks the main operation result."""
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        try:
            metrics.record_attempt(operation, success, duration_ms)
        except Exception as exc:
            logging.warning("Failed to record %s metrics: %s", operation, exc)
    
    # Emotional tone detection
    POSITIVE_INDICATORS = [
        "perfect", "exactly", "yes", "great", "good", "love", "awesome",
        "excellent", "brilliant", "ideal", "right", "correct", "thanks"
    ]
    
    NEGATIVE_INDICATORS = [
        "no", "wrong", "bad", "hate", "awful", "terrible", "frustrating",
        "incorrect", "useless", "nope", "don't", "didn't"
    ]
    
    def process_correction(self,
                         task: str,
                         context_tags: List[str],
                         agent_proposed: str,
                         user_corrected_to: str,
                         user_message: str = "") -> Signal:
        """
        Process a correction event where user overrides agent's choice.

        Before creating a new correction signal, attempts to match the
        correction text against existing preferences. If a strong match
        is found, the signal is routed as a confirmation that strengthens
        the existing preference (and optionally expands its value), rather
        than creating a blind new correction signal.
        """
        # Track metrics
        metrics = self._create_metrics_tracker()
        start_time = datetime.now()
        success = False

        try:
            # --- Preference matching: check if this correction maps to an existing pref ---
            match = self.match_existing_preference(user_corrected_to, task)
            if match.matched and match.preference is not None:
                return self._route_as_confirmation(
                    match=match,
                    task=task,
                    context_tags=context_tags,
                    agent_proposed=agent_proposed,
                    user_corrected_to=user_corrected_to,
                    user_message=user_message,
                    metrics=metrics,
                    start_time=start_time,
                )

            # --- No match: proceed with standard correction flow ---

            # Detect emotional tone from message
            emotional_tone = self._detect_emotional_tone(user_message)
            emotional_indicators = self._extract_emotional_indicators(user_message)

            # Create signal record
            signal = Signal(
                id=generate_id("sig"),
                timestamp=datetime.now().isoformat(),
                type="correction",
                task=task,
                context_tags=context_tags,
                agent_proposed=agent_proposed,
                user_corrected_to=user_corrected_to,
                user_response=user_message,
                emotional_tone=emotional_tone,
                emotional_indicators=emotional_indicators,
                preferences_used=[agent_proposed, user_corrected_to]
            )

            # STEP 1: Update associations
            # Decrement the association with old (proposed) preference
            old_assocs = self.storage.associations.get_associations_for_preference(agent_proposed)
            for assoc in old_assocs:
                impact = self._update_association_for_correction(
                    assoc,
                    agent_proposed,
                    is_positive=False,
                    emotional_tone=emotional_tone
                )
                signal.associations_affected.append({
                    "assoc_id": assoc.id,
                    "pref_id": agent_proposed,
                    "action": "decrement",
                    "impact": impact
                })

            # Increment the association with new (corrected) preference
            new_assocs = self.storage.associations.get_associations_for_preference(user_corrected_to)
            for assoc in new_assocs:
                impact = self._update_association_for_correction(
                    assoc,
                    user_corrected_to,
                    is_positive=True,
                    emotional_tone=emotional_tone
                )
                signal.associations_affected.append({
                    "assoc_id": assoc.id,
                    "pref_id": user_corrected_to,
                    "action": "increment",
                    "impact": impact
                })

            # STEP 2: Update preference confidences
            self._update_preference_for_correction(
                agent_proposed,
                is_positive=False,
                adjustment=-0.03
            )
            self._update_preference_for_correction(
                user_corrected_to,
                is_positive=True,
                adjustment=+0.03
            )

            signal.preferences_affected = [
                {"pref_id": agent_proposed, "action": "decrement"},
                {"pref_id": user_corrected_to, "action": "increment"}
            ]

            # STEP 3: Save signal
            self.storage.signals.save_signal(signal)

            # STEP 4: Record habit usage (with error handling)
            try:
                context = context_tags[0] if context_tags else "general"
                tracker = HabitTracker(self.storage.base_dir)
                tracker.record_usage(context)
            except Exception as e:
                logging.warning(f"Signal processing failed during habit tracking: {e}")

            success = True
            return signal

        except Exception as e:
            logging.warning(f"Signal processing failed: {e}")
            raise

        finally:
            self._record_attempt_metrics(metrics, "correction", success, start_time)
    
    def process_feedback(self,
                        task: str,
                        context_tags: List[str],
                        preferences_used: List[str],
                        user_response: str,
                        satisfaction_level: Optional[float] = None) -> Signal:
        """
        Process feedback signal (user expresses satisfaction/dissatisfaction).

        This helps us understand which preferences work well in which contexts.
        """
        # Track metrics
        metrics = self._create_metrics_tracker()
        start_time = datetime.now()
        success = False

        try:
            # Detect emotional tone
            if satisfaction_level is None:
                emotional_tone = self._detect_emotional_tone(user_response)
                satisfaction_level = self._emotion_to_satisfaction(emotional_tone)
            else:
                emotional_tone = self._satisfaction_to_emotion(satisfaction_level)

            emotional_indicators = self._extract_emotional_indicators(user_response)

            # Resolve generic placeholders to actual preference IDs
            resolved_prefs = self._resolve_preferences_used(preferences_used, context_tags)

            signal = Signal(
                id=generate_id("sig"),
                timestamp=datetime.now().isoformat(),
                type="feedback",
                task=task,
                context_tags=context_tags,
                user_response=user_response,
                emotional_tone=emotional_tone,
                emotional_indicators=emotional_indicators,
                preferences_used=resolved_prefs
            )

            # STEP 1: Boost confidence in used preferences based on satisfaction
            for pref_id in resolved_prefs:
                adjustment = (satisfaction_level - 0.5) * 0.1  # -0.05 to +0.05
                self._update_preference_for_feedback(pref_id, adjustment)

                signal.preferences_affected.append({
                    "pref_id": pref_id,
                    "action": "adjust_confidence",
                    "impact": adjustment
                })

            # STEP 2: Boost associations between used preferences
            for i, pref_id in enumerate(preferences_used):
                assocs = self.storage.associations.get_associations_for_preference(pref_id)
                for assoc in assocs:
                    # Check if this association involves other used preferences
                    other_used = [p for p in preferences_used if p != pref_id]
                    for other in other_used:
                        if assoc.from_id == other or assoc.to_id == other:
                            impact = self._update_association_for_feedback(
                                assoc,
                                pref_id,
                                satisfaction_level
                            )
                            signal.associations_affected.append({
                                "assoc_id": assoc.id,
                                "prefs": [pref_id, other],
                                "action": "reinforce",
                                "impact": impact
                            })

            # STEP 3: Save signal
            self.storage.signals.save_signal(signal)

            # STEP 4: Record habit usage (with error handling)
            try:
                context = context_tags[0] if context_tags else "general"
                tracker = HabitTracker(self.storage.base_dir)
                tracker.record_usage(context)
            except Exception as e:
                logging.warning(f"Signal processing failed during habit tracking: {e}")

            success = True
            return signal

        except Exception as e:
            logging.warning(f"Signal processing failed: {e}")
            raise

        finally:
            self._record_attempt_metrics(metrics, "feedback", success, start_time)
    
    # ---- Confirmation Routing ----

    def _route_as_confirmation(self, match: PreferenceMatchResult,
                                task: str, context_tags: List[str],
                                agent_proposed: str, user_corrected_to: str,
                                user_message: str, metrics: FrictionMetrics,
                                start_time: datetime) -> Signal:
        """Route a correction as a confirmation of an existing preference.

        Instead of creating a new correction signal, this:
        1. Boosts the matched preference's confidence
        2. Records a feedback signal (type="feedback") referencing the pref
        3. Returns the signal with match metadata for CLI display
        """
        pref = match.preference
        emotional_tone = self._detect_emotional_tone(user_message)
        emotional_indicators = self._extract_emotional_indicators(user_message)

        # Boost confidence on the matched preference (+0.05 per confirmation)
        new_confidence = min(pref.confidence + 0.05, 1.0)
        pref.confidence = new_confidence
        pref.learning.use_count += 1
        pref.learning.last_used = datetime.now().isoformat()
        pref.last_updated = datetime.now().isoformat()
        self.storage.preferences.save_preference(pref)

        # Create a feedback signal (not correction) referencing the matched pref
        signal = Signal(
            id=generate_id("sig"),
            timestamp=datetime.now().isoformat(),
            type="feedback",
            task=task,
            context_tags=context_tags,
            user_response=(
                f"[auto-matched to {pref.path} ({match.match_type}, "
                f"similarity={match.similarity:.0%})]\n{user_corrected_to}"
            ),
            emotional_tone=emotional_tone,
            emotional_indicators=emotional_indicators,
            preferences_used=[pref.id],
        )
        signal.preferences_affected = [{
            "pref_id": pref.id,
            "action": "confirm_strengthen",
            "new_confidence": new_confidence,
            "match_similarity": match.similarity,
            "match_type": match.match_type,
        }]

        self.storage.signals.save_signal(signal)

        # Record habit usage
        try:
            context = context_tags[0] if context_tags else "general"
            tracker = HabitTracker(self.storage.base_dir)
            tracker.record_usage(context)
        except Exception as e:
            logging.warning(f"Confirmation routing failed during habit tracking: {e}")

        self._record_attempt_metrics(metrics, "confirmation_routed", True, start_time)
        return signal

    # ---- Helper Methods ----

    def _resolve_preferences_used(
        self,
        preferences_used: List[str],
        context_tags: List[str],
    ) -> List[str]:
        """Resolve generic placeholders to actual preference IDs.

        When the caller passes ['general'] or other non-ID values, look up
        preferences that match the context tags.  If real pref IDs are passed,
        return them unchanged.
        """
        # Check if any entry is a real preference ID
        real_ids = [
            pid for pid in preferences_used
            if self.storage.preferences.get_preference(pid) is not None
        ]
        if real_ids:
            return real_ids

        # Fallback: find preferences whose path overlaps with context tags
        all_prefs = self.storage.preferences.get_all_preferences()
        if not all_prefs:
            return preferences_used  # nothing to resolve to

        matched = []
        for pref in all_prefs:
            path_parts = set(pref.path.split("."))
            if path_parts & set(context_tags):
                matched.append(pref.id)

        # If no tag match, boost all preferences (broad positive signal)
        if not matched:
            matched = [p.id for p in all_prefs]

        return matched

    def _detect_emotional_tone(self, text: str) -> str:
        """Detect emotional tone from user text"""
        if not text:
            return "neutral"
        
        text_lower = text.lower()
        
        positive_count = sum(1 for indicator in self.POSITIVE_INDICATORS
                            if re.search(r'\b' + re.escape(indicator) + r'\b', text_lower))
        negative_count = sum(1 for indicator in self.NEGATIVE_INDICATORS
                            if re.search(r'\b' + re.escape(indicator) + r'\b', text_lower))
        
        if positive_count > negative_count:
            return "satisfied"
        elif negative_count > positive_count:
            return "frustrated"
        else:
            return "neutral"
    
    def _extract_emotional_indicators(self, text: str) -> List[str]:
        """Extract emotional indicator words from text"""
        if not text:
            return []
        
        text_lower = text.lower()
        indicators = []
        
        for indicator in self.POSITIVE_INDICATORS + self.NEGATIVE_INDICATORS:
            if re.search(r'\b' + re.escape(indicator) + r'\b', text_lower):
                indicators.append(indicator)
        
        return list(set(indicators))  # Remove duplicates
    
    def _emotion_to_satisfaction(self, emotional_tone: str) -> float:
        """Convert emotional tone to satisfaction score (0.0 to 1.0)"""
        mapping = {
            "satisfied": 0.85,
            "frustrated": 0.20,
            "neutral": 0.50
        }
        return mapping.get(emotional_tone, 0.50)
    
    def _satisfaction_to_emotion(self, satisfaction: float) -> str:
        """Convert satisfaction score to emotional tone"""
        if satisfaction > 0.7:
            return "satisfied"
        elif satisfaction < 0.4:
            return "frustrated"
        else:
            return "neutral"
    
    def _update_association_for_correction(self,
                                          assoc: Association,
                                          pref_id: str,
                                          is_positive: bool,
                                          emotional_tone: str) -> float:
        """Update association strength for a correction signal"""
        old_strength = assoc.get_strength_for_direction(pref_id)
        
        # Determine direction
        if assoc.from_id == pref_id:
            learning = assoc.learning_forward
            is_forward = True
        else:
            learning = assoc.learning_backward
            is_forward = False
        
        # Adjust use count and satisfaction
        if is_positive:
            learning.use_count += 1
            learning.satisfaction_rate = min(learning.satisfaction_rate + 0.05, 1.0)
            learning.last_used = datetime.now().isoformat()
        else:
            learning.use_count = max(learning.use_count - 1, 0)
            learning.satisfaction_rate = max(learning.satisfaction_rate - 0.05, 0.0)
        
        # Recalculate strength
        new_strength = self._calculate_strength(learning)
        
        if is_forward:
            assoc.strength_forward = new_strength
            assoc.learning_forward = learning
        else:
            assoc.strength_backward = new_strength
            assoc.learning_backward = learning
        
        # Save updated association
        self.storage.associations.save_association(assoc)
        
        return new_strength - old_strength
    
    def _update_association_for_feedback(self,
                                        assoc: Association,
                                        pref_id: str,
                                        satisfaction_level: float) -> float:
        """Update association strength based on feedback signal"""
        old_strength = assoc.get_strength_for_direction(pref_id)
        
        # Determine direction
        if assoc.from_id == pref_id:
            learning = assoc.learning_forward
            is_forward = True
        else:
            learning = assoc.learning_backward
            is_forward = False
        
        # Use satisfaction to update
        learning.satisfaction_rate = (learning.satisfaction_rate * 0.7 + satisfaction_level * 0.3)
        learning.last_used = datetime.now().isoformat()
        
        new_strength = self._calculate_strength(learning)
        
        if is_forward:
            assoc.strength_forward = new_strength
            assoc.learning_forward = learning
        else:
            assoc.strength_backward = new_strength
            assoc.learning_backward = learning
        
        self.storage.associations.save_association(assoc)
        
        return new_strength - old_strength
    
    def _update_preference_for_correction(self,
                                         pref_id: str,
                                         is_positive: bool,
                                         adjustment: float) -> None:
        """Update preference confidence based on correction"""
        pref = self.storage.preferences.get_preference(pref_id)
        if not pref:
            return
        
        # Adjust confidence
        new_confidence = pref.confidence + adjustment
        new_confidence = max(0.0, min(new_confidence, 1.0))  # Clamp 0-1
        
        pref.confidence = new_confidence
        pref.last_updated = datetime.now().isoformat()
        
        # Update learning data
        if is_positive:
            pref.learning.use_count += 1
        
        self.storage.preferences.save_preference(pref)
    
    def _update_preference_for_feedback(self,
                                       pref_id: str,
                                       adjustment: float) -> None:
        """Update preference based on feedback"""
        pref = self.storage.preferences.get_preference(pref_id)
        if not pref:
            return
        
        new_confidence = pref.confidence + adjustment
        new_confidence = max(0.0, min(new_confidence, 1.0))
        
        pref.confidence = new_confidence
        pref.learning.use_count += 1
        pref.learning.last_used = datetime.now().isoformat()
        pref.last_updated = datetime.now().isoformat()
        
        self.storage.preferences.save_preference(pref)
    
    def _calculate_strength(self, learning: AssociationLearning) -> float:
        """
        Calculate association strength from learning data using Bayesian inference.

        Delegates to BayesianStrengthCalculator which models strength as a
        posterior: P(preference|evidence) ∝ P(freq) × P(satisfaction) × P(trend),
        then applies a separate recency decay.  This replaces the old ad-hoc
        multiplicative formula (frequency × trend_mult × emotion_mult × recency_mult).
        """
        days_unused = (
            (datetime.now() - datetime.fromisoformat(learning.last_used)).days
            if learning.last_used else 0
        )

        calc = self._bayesian_calc
        result = calc.calculate_strength_bayesian(
            use_count=learning.use_count,
            satisfaction_rate=learning.satisfaction_rate,
            trend=learning.trend,
            recency_days_unused=float(days_unused),
        )
        return result["strength"]


class StrengthCalculator:
    """Utility class for recalculating all association strengths"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
        self.processor = SignalProcessor(storage_manager)
    
    def recalculate_all(self) -> Dict[str, Any]:
        """Recalculate strengths for all associations"""
        associations = self.storage.associations.get_all_associations()
        
        results = {
            "total": len(associations),
            "updated": 0,
            "details": []
        }
        
        for assoc in associations:
            # Recalculate both directions
            old_forward = assoc.strength_forward
            old_backward = assoc.strength_backward
            
            assoc.strength_forward = self.processor._calculate_strength(assoc.learning_forward)
            assoc.strength_backward = self.processor._calculate_strength(assoc.learning_backward)
            
            self.storage.associations.save_association(assoc)
            
            results["updated"] += 1
            results["details"].append({
                "assoc_id": assoc.id,
                "forward": {"old": old_forward, "new": assoc.strength_forward},
                "backward": {"old": old_backward, "new": assoc.strength_backward}
            })
        
        return results
    
    def apply_time_decay(self) -> Dict[str, Any]:
        """Apply time decay to all associations"""
        associations = self.storage.associations.get_all_associations()
        
        results = {
            "total": len(associations),
            "decayed": 0,
            "details": []
        }
        
        for assoc in associations:
            # Calculate days since last decay
            last_decay = datetime.fromisoformat(assoc.last_decay_applied)
            days_since_decay = (datetime.now() - last_decay).days
            
            if days_since_decay > 0:
                # Apply daily decay for each day
                old_forward = assoc.strength_forward
                old_backward = assoc.strength_backward
                
                decay = assoc.time_decay_factor ** days_since_decay
                assoc.strength_forward *= decay
                assoc.strength_backward *= decay
                assoc.last_decay_applied = datetime.now().isoformat()
                
                self.storage.associations.save_association(assoc)
                
                results["decayed"] += 1
                results["details"].append({
                    "assoc_id": assoc.id,
                    "days_since_decay": days_since_decay,
                    "decay_multiplier": decay,
                    "forward": {"old": old_forward, "new": assoc.strength_forward},
                    "backward": {"old": old_backward, "new": assoc.strength_backward}
                })
        
        return results


if __name__ == "__main__":
    # Quick test
    storage = PreferenceStorageManager("/tmp/test_signal")
    processor = SignalProcessor(storage)
    
    # Test emotion detection
    messages = [
        "Perfect! That's exactly what I needed!",
        "No, that's not right at all.",
        "Yeah, it's okay I guess."
    ]
    
    for msg in messages:
        tone = processor._detect_emotional_tone(msg)
        indicators = processor._extract_emotional_indicators(msg)
        print(f"Message: '{msg}'")
        print(f"  Tone: {tone}")
        print(f"  Indicators: {indicators}\n")
