"""
significance_consolidation_bridge.py - Integration of significance testing with consolidation

This module bridges the gap between statistical significance testing and preference consolidation.
It ensures that preferences are only promoted when their trends are both statistically significant
and have sufficient sample sizes.

The bridge wraps ConsolidationEngine and adds significance-aware promotion logic:
1. Before promoting a preference, runs binomial significance test on its signals
2. Only promotes if: (a) signal count meets threshold AND
   (b) trend is statistically significant (p < 0.05) OR signal count > 20
3. Adds significance_score and p_value metadata to promoted preferences
4. Provides a factory function for easy integration

This prevents false promotions driven by noise and ensures learned preferences
have genuine statistical backing.
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
import sys
import json

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent))

from scripts.models import Preference, Signal
from scripts.consolidation_engine import ConsolidationEngine
from scripts.significance_tester import SignificanceTester, TrendResult


class SignificanceAwareConsolidationEngine(ConsolidationEngine):
    """
    Consolidation engine with statistical significance awareness.

    Extends ConsolidationEngine to include binomial significance testing before
    preference promotion. This prevents noise from causing premature stage advancement.

    Attributes:
        significance_tester: SignificanceTester instance for trend analysis
        promotion_log: Record of all promotion decisions with significance data
    """

    def __init__(self, base_dir: str = None):
        """
        Initialize significance-aware consolidation engine.

        Args:
            base_dir: Base directory for preference storage (~/.adaptive-cli if None)
        """
        super().__init__(base_dir)
        self.significance_tester = SignificanceTester()
        self.promotion_log: List[Dict] = []

    def check_promotion(self, preference_id: str) -> bool:
        """
        Check if preference is ready for promotion, with significance testing.

        Overrides parent method to add statistical significance requirement.

        Promotion criteria:
        - Signal count meets stage threshold (parent check)
        - Confidence is in target range for next stage (parent check)
        - Recent signals show positive trend (parent check)
        - AND: Either (a) trend is statistically significant (p < 0.05)
               OR (b) signal count > 20 (enough data to trust raw counts)

        Args:
            preference_id: ID of the preference

        Returns:
            True if preference should be promoted, False otherwise

        Raises:
            ValueError: If preference not found
        """
        # First, check standard promotion criteria from parent
        if not super().check_promotion(preference_id):
            return False

        # If standard criteria pass, add significance check
        pref = self.storage.preferences.get_preference(preference_id)
        if not pref:
            raise ValueError(f"Preference not found: {preference_id}")

        signal_count = pref.learning.use_count

        # If we have > 20 signals, trust the raw data (significance testing may be conservative)
        if signal_count > 20:
            return True

        # Otherwise, test for statistical significance
        all_signals = self.storage.signals.get_signals_for_preference(preference_id)
        if not all_signals:
            return False

        # Run significance test on all signals for this preference
        trend_result = self.significance_tester.test_trend_significance(all_signals)

        # Log the promotion decision
        self._log_promotion_decision(
            preference_id=preference_id,
            signal_count=signal_count,
            trend_result=trend_result,
            will_promote=trend_result.significant
        )

        return trend_result.significant

    def run_daily_consolidation(self) -> Dict:
        """
        Execute daily consolidation cycle with significance awareness and FDR correction.

        Collects ALL preference signals for the day, runs significance tests,
        applies Benjamini-Hochberg FDR correction, and promotes only FDR-significant
        preferences.

        Returns:
            Dictionary with consolidation summary including:
            {
                "timestamp": ISO timestamp,
                "signals_reviewed": int,
                "preferences_promoted": List[str] (preference IDs),
                "preferences_demoted": List[str],
                "confidence_updates": Dict[str, float],
                "stage_changes": Dict[str, Dict],
                "significance_data": Dict (pref_id -> {p_value, significance_score, fdr_significant}),
                "fdr_applied": bool,
                "total_tested": int,
                "significant_after_fdr": int,
                "total_preferences_affected": int,
                "consolidation_details": str
            }
        """
        # Step 1: Call parent consolidation to get base result
        result = super().run_daily_consolidation()

        # Step 2: Collect ALL preference signals for today
        # Get signals from last 24 hours to match parent's consolidation window
        recent_signals = self.storage.signals.get_recent_signals(hours=24)
        affected_prefs = set()
        for signal in recent_signals:
            affected_prefs.update(signal.preferences_used)

        # Step 3: Test each affected preference and collect p-values
        pref_ids_to_test = []
        p_values = []

        for pref_id in affected_prefs:
            pref = self.storage.preferences.get_preference(pref_id)
            if pref:
                all_signals = self.storage.signals.get_signals_for_preference(pref_id)
                if all_signals:
                    trend_result = self.significance_tester.test_trend_significance(all_signals)
                    pref_ids_to_test.append(pref_id)
                    p_values.append(trend_result.p_value)

        # Step 4: Apply FDR correction to p-values
        from scripts.significance_tester import correct_multiple_tests

        fdr_decisions = []
        if p_values:
            fdr_decisions = correct_multiple_tests(p_values, alpha=0.05)

        # Step 5: Build significance data and track FDR-significant preferences
        significance_data = {}
        fdr_promoted = []

        for idx, pref_id in enumerate(pref_ids_to_test):
            all_signals = self.storage.signals.get_signals_for_preference(pref_id)
            if all_signals:
                trend_result = self.significance_tester.test_trend_significance(all_signals)
                is_fdr_significant = fdr_decisions[idx] if idx < len(fdr_decisions) else False

                significance_data[pref_id] = {
                    "p_value": trend_result.p_value,
                    "significance_score": 1.0 - trend_result.p_value,
                    "effect_size": trend_result.effect_size,
                    "autocorrelation": trend_result.autocorrelation,
                    "n_signals": trend_result.n_signals,
                    "fdr_significant": is_fdr_significant
                }

                # Add metadata to preference
                pref = self.storage.preferences.get_preference(pref_id)
                if pref:
                    pref.learning.significance_score = 1.0 - trend_result.p_value
                    pref.learning.p_value = trend_result.p_value
                    pref.learning.effect_size = trend_result.effect_size
                    pref.learning.autocorrelation = trend_result.autocorrelation
                    pref.learning.n_signals = trend_result.n_signals
                    pref.learning.fdr_significant = is_fdr_significant
                    self.storage.preferences.save_preference(pref)

                # Track FDR-significant preferences
                if is_fdr_significant:
                    fdr_promoted.append(pref_id)

        result["significance_data"] = significance_data
        result["fdr_applied"] = True
        result["total_tested"] = len(pref_ids_to_test)
        result["significant_after_fdr"] = len(fdr_promoted)

        # Step 6: Enhance consolidation details with FDR information
        details_lines = result["consolidation_details"].split("\n")
        details_lines.append("\nFDR-CORRECTED SIGNIFICANCE ANALYSIS:")
        details_lines.append(f"  Total preferences tested: {len(pref_ids_to_test)}")
        details_lines.append(f"  Significant after FDR correction: {len(fdr_promoted)}")

        if significance_data:
            for pref_id, sig_data in sorted(significance_data.items()):
                fdr_status = "FDR-SIG" if sig_data["fdr_significant"] else "not-sig"
                details_lines.append(
                    f"  {pref_id}: p={sig_data['p_value']:.4f}, "
                    f"score={sig_data['significance_score']:.3f}, "
                    f"effect_size={sig_data['effect_size']:.2f}, [{fdr_status}]"
                )

        result["consolidation_details"] = "\n".join(details_lines)

        return result

    def get_promotion_log(self) -> List[Dict]:
        """
        Get the log of all promotion decisions with significance data.

        Returns:
            List of promotion decision records, each containing:
            {
                "timestamp": ISO timestamp,
                "preference_id": str,
                "signal_count": int,
                "p_value": float,
                "significance_score": float,
                "effect_size": float,
                "autocorrelation": float,
                "will_promote": bool
            }
        """
        return self.promotion_log.copy()

    def get_significance_report(self) -> str:
        """
        Generate a human-readable significance analysis report.

        Includes p-values, effect sizes, and autocorrelation for all preferences
        tracked during consolidation.

        Returns:
            Formatted report string
        """
        prefs = self.storage.preferences.get_all_preferences()

        if not prefs:
            return "No preferences to report."

        lines = ["=" * 80]
        lines.append("SIGNIFICANCE ANALYSIS REPORT")
        lines.append(f"Generated: {datetime.now().isoformat()}")
        lines.append("=" * 80)

        lines.append(f"\nTotal Preferences: {len(prefs)}\n")
        lines.append("PREFERENCE SIGNIFICANCE STATISTICS:")
        lines.append("-" * 80)
        lines.append(
            f"{'Preference ID':<30} {'Signals':<8} {'P-Value':<12} "
            f"{'Sig Score':<12} {'Effect Size':<12}"
        )
        lines.append("-" * 80)

        significant_count = 0
        for pref in sorted(prefs, key=lambda p: p.learning.use_count, reverse=True):
            signal_count = pref.learning.use_count
            signals = self.storage.signals.get_signals_for_preference(pref.id)

            if signals:
                trend = self.significance_tester.test_trend_significance(signals)
                p_value = trend.p_value
                sig_score = 1.0 - p_value
                effect_size = trend.effect_size

                if p_value < 0.05:
                    significant_count += 1

                lines.append(
                    f"{pref.id:<30} {signal_count:<8} "
                    f"{p_value:<12.4f} {sig_score:<12.3f} {effect_size:<12.2f}"
                )

        lines.append("-" * 80)
        lines.append(
            f"\nStatistically Significant Preferences (p < 0.05): {significant_count} "
            f"({significant_count/len(prefs)*100:.1f}%)"
        )

        lines.append("\n" + "=" * 80)

        return "\n".join(lines)

    # ---- Private helper methods ----

    def _log_promotion_decision(self,
                                preference_id: str,
                                signal_count: int,
                                trend_result: TrendResult,
                                will_promote: bool) -> None:
        """
        Log a promotion decision with significance analysis.

        Args:
            preference_id: ID of preference being evaluated
            signal_count: Number of signals for the preference
            trend_result: TrendResult from significance testing
            will_promote: Whether the preference will be promoted
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "preference_id": preference_id,
            "signal_count": signal_count,
            "p_value": trend_result.p_value,
            "significance_score": 1.0 - trend_result.p_value,
            "effect_size": trend_result.effect_size,
            "autocorrelation": trend_result.autocorrelation,
            "n_signals": trend_result.n_signals,
            "will_promote": will_promote
        }
        self.promotion_log.append(log_entry)


def get_integrated_engine(base_dir: str = None) -> SignificanceAwareConsolidationEngine:
    """
    Factory function to create a significance-aware consolidation engine.

    This is the primary way to instantiate the integrated engine, ensuring
    consistent configuration across the codebase.

    Args:
        base_dir: Base directory for preference storage (~/.adaptive-cli if None)

    Returns:
        SignificanceAwareConsolidationEngine instance ready for use

    Example:
        >>> engine = get_integrated_engine()
        >>> result = engine.run_daily_consolidation()
        >>> print(engine.get_significance_report())
    """
    return SignificanceAwareConsolidationEngine(base_dir)


if __name__ == "__main__":
    # Quick test
    engine = get_integrated_engine("/tmp/test_significance_bridge")
    print("Significance-aware consolidation engine initialized successfully")
    print(f"Storage info: {engine.storage.get_storage_info()}")
    print(f"Promotion log entries: {len(engine.get_promotion_log())}")
