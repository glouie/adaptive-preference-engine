"""
consolidation_engine.py - Memory consolidation for preference learning

Implements a behavior-driven preference learning system inspired by neuroscience memory
consolidation processes. Preferences progress through learning stages, with confidence
and learning rates adapted to match stage strength.

Stage progression:
- initial (0-4 signals): confidence 0.3-0.5, multiplier 0.5
- emerging (5-14 signals): confidence 0.5-0.65, multiplier 0.75
- consolidating (15-29 signals): confidence 0.65-0.80, multiplier 1.0
- stable (30+ signals): confidence 0.80+, multiplier 1.2

Daily consolidation reviews signals from the last 24 hours, detects patterns,
reduces noise, and promotes preferences to higher stages when criteria are met.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import sys

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent))

from scripts.models import Preference, Signal
from scripts.storage import PreferenceStorageManager

# Configure logging
logger = logging.getLogger(__name__)


class ConsolidationEngine:
    """
    Memory consolidation engine for adaptive preference learning.

    Manages preference stages, learning rate multipliers, and daily consolidation cycles
    to stabilize learned preferences over time.
    """

    # Stage definitions: (min_signals, max_signals, confidence_min, confidence_max, multiplier)
    STAGES = {
        "initial": (0, 4, 0.30, 0.50, 0.5),
        "emerging": (5, 14, 0.50, 0.65, 0.75),
        "consolidating": (15, 29, 0.65, 0.80, 1.0),
        "stable": (30, float('inf'), 0.80, 1.0, 1.2)
    }

    def __init__(self, base_dir: str = None):
        """
        Initialize consolidation engine.

        Args:
            base_dir: Base directory for preference storage (~/.adaptive-cli if None)
        """
        self.storage = PreferenceStorageManager(base_dir)

        # Emotional intensity keywords for weighting
        self._strong_intensity_words = {
            "always", "never", "hate", "love", "perfect", "terrible",
            "constantly", "keep having to"
        }
        self._moderate_intensity_words = {
            "prefer", "better", "nice", "good", "bad", "usually"
        }

    def get_stage(self, preference_id: str) -> str:
        """
        Determine the learning stage of a preference based on signal count.

        Args:
            preference_id: ID of the preference to check

        Returns:
            Stage name: "initial", "emerging", "consolidating", or "stable"

        Raises:
            ValueError: If preference not found
        """
        pref = self.storage.preferences.get_preference(preference_id)
        if not pref:
            raise ValueError(f"Preference not found: {preference_id}")

        signal_count = pref.learning.use_count

        for stage_name, (min_sig, max_sig, _, _, _) in self.STAGES.items():
            if min_sig <= signal_count <= max_sig:
                return stage_name

        # Should not reach here given STAGES definition
        return "stable"

    def get_stage_multiplier(self, preference_id: str) -> float:
        """
        Get the learning rate multiplier for a preference's current stage.

        Higher stages have higher multipliers, allowing faster learning once
        a preference is well-established.

        Args:
            preference_id: ID of the preference

        Returns:
            Learning rate multiplier (0.5 to 1.2)

        Raises:
            ValueError: If preference not found
        """
        stage = self.get_stage(preference_id)
        return self.STAGES[stage][4]

    def check_promotion(self, preference_id: str) -> bool:
        """
        Check if a preference is ready for promotion to the next stage.

        Promotion criteria:
        - Signal count meets stage threshold
        - Confidence is in the target range for next stage
        - Recent signals (last 7 days) show positive trend

        Args:
            preference_id: ID of the preference

        Returns:
            True if preference should be promoted, False otherwise

        Raises:
            ValueError: If preference not found
        """
        pref = self.storage.preferences.get_preference(preference_id)
        if not pref:
            raise ValueError(f"Preference not found: {preference_id}")

        current_stage = self.get_stage(preference_id)
        signal_count = pref.learning.use_count
        confidence = pref.confidence

        # Check if we've exceeded current stage's signal threshold
        stage_config = self.STAGES[current_stage]
        max_signals = stage_config[1]

        if signal_count < (max_signals + 1):
            return False

        # Check confidence is in next stage's range
        next_stage_map = {
            "initial": "emerging",
            "emerging": "consolidating",
            "consolidating": "stable",
            "stable": None
        }

        next_stage = next_stage_map.get(current_stage)
        if not next_stage:
            return False  # Already at stable stage

        next_stage_config = self.STAGES[next_stage]
        conf_min, conf_max = next_stage_config[2], next_stage_config[3]

        if not (conf_min <= confidence <= conf_max):
            return False

        # Check recent trend (last 7 days)
        recent_signals = self.storage.signals.get_signals_for_preference(preference_id)
        recent_signals = [
            s for s in recent_signals
            if self._is_recent(s.timestamp, days=7)
        ]

        if not recent_signals:
            return False

        # Calculate trend: majority of recent signals should be positive
        positive_count = sum(
            1 for s in recent_signals
            if self._is_positive_signal(s)
        )

        return positive_count >= len(recent_signals) / 2

    def run_daily_consolidation(self) -> Dict:
        """
        Execute daily consolidation cycle (sleep-equivalent process).

        This reviews all signals from the last 24 hours and:
        1. Replays signals to detect patterns
        2. Reduces noise from single outlier signals
        3. Promotes preferences to next stage when criteria are met
        4. Demotes preferences if contradicted recently

        Returns:
            Dictionary with consolidation summary:
            {
                "timestamp": ISO timestamp,
                "signals_reviewed": int,
                "preferences_promoted": List[str] (preference IDs),
                "preferences_demoted": List[str],
                "confidence_updates": Dict[str, float] (pref_id -> new_confidence),
                "stage_changes": Dict[str, Dict] (pref_id -> {from: stage, to: stage}),
                "total_preferences_affected": int,
                "consolidation_details": str (human-readable summary)
            }
        """
        result = {
            "timestamp": datetime.now().isoformat(),
            "signals_reviewed": 0,
            "preferences_promoted": [],
            "preferences_demoted": [],
            "confidence_updates": {},
            "stage_changes": {},
            "total_preferences_affected": 0,
            "consolidation_details": ""
        }

        # Get signals from last 24 hours
        recent_signals = self.storage.signals.get_recent_signals(hours=24)
        result["signals_reviewed"] = len(recent_signals)

        if not recent_signals:
            result["consolidation_details"] = "No signals to consolidate."
            return result

        # Get all preferences affected by recent signals
        affected_prefs = set()
        for signal in recent_signals:
            affected_prefs.update(signal.preferences_used)

        result["total_preferences_affected"] = len(affected_prefs)

        # Process each affected preference
        for pref_id in affected_prefs:
            pref = self.storage.preferences.get_preference(pref_id)
            if not pref:
                continue

            old_stage = self.get_stage(pref_id)
            old_confidence = pref.confidence

            # Check for demotion (recent contradictions)
            if self._should_demote(pref_id, recent_signals):
                # Reduce confidence slightly
                pref.confidence = max(0.3, pref.confidence - 0.1)
                result["preferences_demoted"].append(pref_id)

            # Check for promotion
            if self.check_promotion(pref_id):
                next_stage_map = {
                    "initial": "emerging",
                    "emerging": "consolidating",
                    "consolidating": "stable"
                }
                next_stage = next_stage_map.get(old_stage)

                if next_stage:
                    new_stage = next_stage
                    # Increase confidence to match new stage's minimum
                    new_min_conf = self.STAGES[new_stage][2]
                    pref.confidence = max(pref.confidence, new_min_conf)

                    result["preferences_promoted"].append(pref_id)
                    result["stage_changes"][pref_id] = {
                        "from": old_stage,
                        "to": new_stage
                    }

            # Record confidence update if it changed
            if pref.confidence != old_confidence:
                result["confidence_updates"][pref_id] = pref.confidence
                pref.last_updated = datetime.now().isoformat()
                self.storage.preferences.save_preference(pref)

        # Build details summary
        details_lines = [
            f"Consolidation cycle completed at {result['timestamp']}",
            f"Signals reviewed: {result['signals_reviewed']}",
            f"Preferences affected: {result['total_preferences_affected']}"
        ]

        if result["preferences_promoted"]:
            details_lines.append(f"Promoted: {len(result['preferences_promoted'])} preferences")
            for pref_id in result["preferences_promoted"][:5]:
                change = result["stage_changes"].get(pref_id, {})
                details_lines.append(
                    f"  - {pref_id}: {change.get('from')} → {change.get('to')}"
                )
            if len(result["preferences_promoted"]) > 5:
                details_lines.append(f"  ... and {len(result['preferences_promoted']) - 5} more")

        if result["preferences_demoted"]:
            details_lines.append(f"Demoted: {len(result['preferences_demoted'])} preferences")

        result["consolidation_details"] = "\n".join(details_lines)

        return result

    def get_consolidation_report(self) -> str:
        """
        Generate a human-readable consolidation report for all preferences.

        Includes stage distribution, confidence statistics, and trending preferences.

        Returns:
            Formatted report string
        """
        prefs = self.storage.preferences.get_all_preferences()

        if not prefs:
            return "No preferences to report."

        # Organize by stage
        stage_groups = {stage: [] for stage in self.STAGES.keys()}
        for pref in prefs:
            stage = self.get_stage(pref.id)
            stage_groups[stage].append(pref)

        # Build report
        lines = ["=" * 80]
        lines.append("CONSOLIDATION REPORT")
        lines.append(f"Generated: {datetime.now().isoformat()}")
        lines.append("=" * 80)

        lines.append(f"\nTotal Preferences: {len(prefs)}")

        # Stage summary
        lines.append("\nSTAGE DISTRIBUTION:")
        lines.append("-" * 40)

        for stage_name in ["initial", "emerging", "consolidating", "stable"]:
            count = len(stage_groups[stage_name])
            pct = (count / len(prefs) * 100) if prefs else 0
            lines.append(f"  {stage_name:15s}: {count:3d} ({pct:5.1f}%)")

        # Confidence statistics
        lines.append("\nCONFIDENCE STATISTICS:")
        lines.append("-" * 40)

        confidences = [p.confidence for p in prefs]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0
        min_conf = min(confidences) if confidences else 0
        max_conf = max(confidences) if confidences else 0

        lines.append(f"  Average:  {avg_conf:.2%}")
        lines.append(f"  Minimum:  {min_conf:.2%}")
        lines.append(f"  Maximum:  {max_conf:.2%}")

        # Top trending preferences (highest confidence growth)
        lines.append("\nTOP PREFERENCES BY CONFIDENCE:")
        lines.append("-" * 40)

        sorted_by_conf = sorted(prefs, key=lambda p: p.confidence, reverse=True)
        for pref in sorted_by_conf[:10]:
            stage = self.get_stage(pref.id)
            trend = pref.learning.trend
            lines.append(
                f"  {pref.path:40s} | {pref.confidence:.0%} | "
                f"{stage:12s} | {trend}"
            )

        if len(sorted_by_conf) > 10:
            lines.append(f"  ... and {len(sorted_by_conf) - 10} more")

        # Recently promoted preferences
        promoted = [p for p in prefs if p.learning.use_count >= self.STAGES["emerging"][0]]
        if promoted:
            lines.append("\nRECENTLY ACTIVE (5+ signals):")
            lines.append("-" * 40)
            for pref in promoted[:8]:
                stage = self.get_stage(pref.id)
                lines.append(
                    f"  {pref.path:40s} | {pref.learning.use_count:3d} signals | "
                    f"{stage}"
                )

        lines.append("\n" + "=" * 80)

        return "\n".join(lines)

    def context_aware_consolidation(self, preference_id: str, context_tags: List[str]) -> Dict:
        """
        Apply context-aware learning rate using Jaccard similarity.

        Uses Jaccard similarity coefficient between current context tags and stored
        preference context tags to determine learning rate multiplier.

        Jaccard similarity: |intersection| / |union|
        Maps to learning rate multiplier:
        - 0.0 (no match) → 1.0x
        - 0.0-0.3 (low similarity) → 1.05x
        - 0.3-0.6 (medium similarity) → 1.15x
        - 0.6-0.9 (high similarity) → 1.25x
        - 0.9-1.0 (exact match) → 1.3x

        Args:
            preference_id: ID of the preference to consolidate
            context_tags: List of context tags for current session

        Returns:
            Dictionary with consolidation result:
            {
                "preference_id": str,
                "jaccard_similarity": float,
                "learning_rate_multiplier": float,
                "consolidation_details": str
            }

        Raises:
            ValueError: If preference not found
        """
        pref = self.storage.preferences.get_preference(preference_id)
        if not pref:
            raise ValueError(f"Preference not found: {preference_id}")

        # Calculate Jaccard similarity with normalized tags
        stored_context_tags = getattr(pref, 'context_tags', [])
        stored_set = self._normalize_tags(stored_context_tags)
        current_set = self._normalize_tags(context_tags)

        if not stored_set and not current_set:
            # Both empty
            jaccard = 1.0
        elif not stored_set or not current_set:
            # One empty, one not
            jaccard = 0.0
        else:
            intersection = len(stored_set & current_set)
            union = len(stored_set | current_set)
            jaccard = intersection / union if union > 0 else 0.0

        # Map Jaccard similarity to learning rate multiplier
        learning_rate_multiplier = self._jaccard_to_multiplier(jaccard)

        details = (
            f"Context match for {preference_id}. "
            f"Jaccard similarity: {jaccard:.3f}, Learning rate: {learning_rate_multiplier:.2f}x. "
            f"Current tags: {context_tags}, Stored tags: {stored_context_tags}"
        )

        return {
            "preference_id": preference_id,
            "jaccard_similarity": jaccard,
            "learning_rate_multiplier": learning_rate_multiplier,
            "consolidation_details": details
        }

    def _jaccard_to_multiplier(self, jaccard: float) -> float:
        """
        Map Jaccard similarity coefficient to learning rate multiplier.

        Args:
            jaccard: Jaccard similarity (0.0 to 1.0)

        Returns:
            Learning rate multiplier (1.0 to 1.3)
        """
        if jaccard < 0.0:
            return 1.0
        elif jaccard < 0.3:
            return 1.05
        elif jaccard < 0.6:
            return 1.15
        elif jaccard < 0.9:
            return 1.25
        else:  # 0.9 to 1.0
            return 1.3

    # ---- Private helper methods ----

    def _normalize_tags(self, tags: List[str]) -> set:
        """
        Normalize context tags for comparison.

        Performs normalization:
        - Lowercases each tag
        - Strips whitespace
        - Removes empty strings
        - Returns a set

        Args:
            tags: List of context tags to normalize

        Returns:
            Set of normalized tags
        """
        normalized = set()
        for tag in tags:
            if tag:
                normalized_tag = tag.strip().lower()
                if normalized_tag:  # Only add non-empty tags
                    normalized.add(normalized_tag)
        return normalized

    def _detect_emotional_intensity(self, signal: Signal) -> float:
        """
        Detect emotional intensity from signal message with negation handling.

        Analyzes the signal's message content for emotional intensity keywords,
        returning a multiplier for confidence updates:
        - 1.5: Strong emotional indicators (always, never, hate, love, perfect, terrible, constantly, keep having to)
        - 1.2: Moderate emotional indicators (prefer, better, nice, good, bad, usually)
        - 1.0: Neutral (no emotional indicators)

        Handles negation by detecting negation words within 5 tokens before intensity keywords,
        with boundary detection at sentence endings:
        - "don't hate" → 1.0 (neutral) instead of 1.5
        - "not perfect" → 1.0 instead of 1.5
        - "not really prefer" → 1.0 instead of 1.2
        - "without being good" → 1.0 instead of 1.2
        - Negation from previous sentence does not apply due to boundary detection

        Case-insensitive matching against signal message and user_response.

        Args:
            signal: Signal object to analyze

        Returns:
            Emotional intensity multiplier (1.0 to 1.5)
        """
        # Combine all text fields to search
        text_fields = []

        if signal.type == "correction":
            # Use agent_proposed and user_corrected_to
            if signal.agent_proposed:
                text_fields.append(signal.agent_proposed.lower())
            if signal.user_corrected_to:
                text_fields.append(signal.user_corrected_to.lower())
        elif signal.type == "feedback":
            # Use user_response
            if signal.user_response:
                text_fields.append(signal.user_response.lower())
        else:
            # General signals, check user_response
            if signal.user_response:
                text_fields.append(signal.user_response.lower())

        combined_text = " ".join(text_fields)

        # Tokenize for negation detection
        tokens = combined_text.split()
        negation_words = {
            "not", "don't", "doesn't", "never", "no", "without", "hardly",
            "wouldn't", "couldn't", "shouldn't", "can't", "won't", "doesn't",
            "didn't", "haven't", "isn't", "aren't", "wasn't", "weren't"
        }

        # Check for strong intensity words
        for word in self._strong_intensity_words:
            word_lower = word.lower()
            if word_lower in combined_text:
                # Check if negation appears within 3 tokens before this word
                if self._is_negated(tokens, word_lower, negation_words):
                    return 1.0
                return 1.5

        # Check for moderate intensity words
        for word in self._moderate_intensity_words:
            word_lower = word.lower()
            if word_lower in combined_text:
                # Check if negation appears within 3 tokens before this word
                if self._is_negated(tokens, word_lower, negation_words):
                    return 1.0
                return 1.2

        # No emotional indicators
        return 1.0

    def _is_negated(self, tokens: List[str], target_word: str, negation_words: set) -> bool:
        """
        Check if target word is negated by a negation word within 5 tokens before it.

        Stops the lookback at sentence-ending punctuation (., !, ?) so negation from
        a previous sentence doesn't bleed through.

        Args:
            tokens: List of tokens from the text
            target_word: The intensity word to check
            negation_words: Set of negation words to look for

        Returns:
            True if target word is negated, False otherwise
        """
        for i, token in enumerate(tokens):
            if target_word in token:
                # Look back up to 5 tokens for negation, stopping at sentence boundaries
                start = max(0, i - 5)
                for j in range(start, i):
                    # Stop lookback at sentence-ending punctuation
                    if tokens[j].endswith('.') or tokens[j].endswith('!') or tokens[j].endswith('?'):
                        # Only check tokens after this boundary
                        start = j + 1
                        break

                # Check for negation in the lookback window
                for j in range(start, i):
                    if tokens[j] in negation_words:
                        return True
                return False
        return False

    def _apply_emotional_weight(self, base_confidence: float, signal: Signal) -> float:
        """
        Apply emotional intensity weighting to confidence update with temporal decay.

        Multiplies the confidence delta by the emotional intensity multiplier
        detected in the signal, applies temporal decay for older signals, then caps
        the result at 0.95 to maintain realistic confidence bounds.

        Temporal decay:
        - Signals lose half their emotional weight after 30 days
        - Formula: temporal_weight = max(0.5, 1.0 - (days_old / 30.0))
        - If no timestamp available, temporal_weight = 1.0 (no decay)

        Formula: new_confidence = min(0.95, base_confidence * emotional_intensity * temporal_weight)

        Args:
            base_confidence: Base confidence value before emotional weighting (0.0 to 1.0)
            signal: Signal object to analyze for emotional intensity

        Returns:
            Emotionally-weighted and temporally-decayed confidence (0.0 to 0.95)
        """
        emotional_intensity = self._detect_emotional_intensity(signal)

        # Calculate temporal decay
        temporal_weight = 1.0
        if hasattr(signal, 'timestamp') and signal.timestamp:
            try:
                signal_time = datetime.fromisoformat(signal.timestamp)
                days_old = (datetime.now() - signal_time).days
                temporal_weight = max(0.5, 1.0 - (days_old / 30.0))
            except (ValueError, TypeError):
                temporal_weight = 1.0
        elif hasattr(signal, 'created_at') and signal.created_at:
            try:
                signal_time = datetime.fromisoformat(signal.created_at)
                days_old = (datetime.now() - signal_time).days
                temporal_weight = max(0.5, 1.0 - (days_old / 30.0))
            except (ValueError, TypeError):
                temporal_weight = 1.0

        # Apply both emotional intensity and temporal decay
        weighted_confidence = base_confidence * emotional_intensity * temporal_weight
        # Cap at 0.95 to avoid overconfidence
        return min(0.95, weighted_confidence)

    def _is_recent(self, timestamp: str, days: int = 1) -> bool:
        """Check if timestamp is within N days of now."""
        try:
            signal_time = datetime.fromisoformat(timestamp)
            cutoff = datetime.now() - timedelta(days=days)
            return signal_time >= cutoff
        except (ValueError, TypeError):
            return False

    def _is_positive_signal(self, signal: Signal) -> bool:
        """Determine if a signal represents positive reinforcement."""
        if signal.type == "correction":
            return True  # User corrected = signal is tracking
        elif signal.type == "feedback":
            if signal.emotional_tone in ["satisfied", "neutral"]:
                return True
            return False
        elif signal.type == "usage":
            return True  # Usage is positive signal
        elif signal.type == "override":
            return False  # Override indicates user went against preference
        return False

    def _should_demote(self, pref_id: str, recent_signals: List[Signal]) -> bool:
        """
        Check if preference should be demoted based on recent contradictions.

        A preference should be demoted if:
        - Multiple contradicting signals in last 24 hours
        - Recent override signals
        - Low satisfaction feedback
        """
        pref_signals = [s for s in recent_signals if pref_id in s.preferences_used]

        if not pref_signals:
            return False

        # Count negative signals
        negative_count = sum(
            1 for s in pref_signals
            if not self._is_positive_signal(s)
        )

        # Demote if more than 30% of recent signals are negative
        return negative_count > len(pref_signals) * 0.3


if __name__ == "__main__":
    # Quick test
    engine = ConsolidationEngine("/tmp/test_consolidation")
    print("Consolidation engine initialized successfully")
    print(f"Storage info: {engine.storage.get_storage_info()}")
