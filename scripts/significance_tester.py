"""
significance_tester.py - Statistical significance testing for trend detection
Addresses Dr. Michael Wong (ML/Stats SME) critical gap: "Trend detection has no
statistical significance testing — treats random noise as real trends"

This module implements proper statistical rigor:
- Binomial test for trend significance (is ratio of positive signals significantly != 0.5?)
- Autocorrelation detection (Durbin-Watson style) to catch correlated signals
- Selection bias correction (only corrections recorded, positive uses underrepresented)
- Thompson Sampling exploration bonus for low-data preferences
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
import math
from scripts.models import Signal


# Pure Python math implementations (no scipy dependency)

def binomial_coefficient(n: int, k: int) -> int:
    """
    Calculate binomial coefficient C(n, k) = n! / (k! * (n-k)!)

    Args:
        n: Total number of trials
        k: Number of successes

    Returns:
        Binomial coefficient
    """
    if k < 0 or k > n:
        return 0
    if k == 0 or k == n:
        return 1

    # Optimize by using smaller k
    k = min(k, n - k)

    result = 1
    for i in range(k):
        result = result * (n - i) // (i + 1)

    return result


def binomial_cdf(n: int, p: float, k: int) -> float:
    """
    Calculate cumulative binomial probability P(X <= k) where X ~ Binomial(n, p).

    This is used for two-tailed significance testing:
    p_value = 2 * min(P(X <= observed), P(X >= observed))

    Args:
        n: Number of trials
        p: Probability of success in single trial
        k: Number of successes

    Returns:
        Cumulative probability P(X <= k)
    """
    cdf = 0.0
    for i in range(k + 1):
        # P(X = i) = C(n, i) * p^i * (1-p)^(n-i)
        coeff = binomial_coefficient(n, i)
        prob = coeff * (p ** i) * ((1 - p) ** (n - i))
        cdf += prob

    return cdf


def correct_multiple_tests(p_values: List[float], alpha: float = 0.05) -> List[bool]:
    """
    Apply Benjamini-Hochberg (BH) FDR (False Discovery Rate) correction to p-values.

    The BH procedure controls the FDR at level alpha, meaning:
    - Expected proportion of false positives among rejected tests ≤ alpha
    - More powerful than Bonferroni (allows more discoveries)

    Algorithm:
    1. Sort p-values while tracking original indices
    2. For each rank k (1-indexed), check if p_value <= (k/m) * alpha
    3. Find the largest k satisfying the criterion
    4. Reject all hypotheses at ranks 1..k (return True)
    5. All others fail to reject (return False)

    Args:
        p_values: List of p-values from individual tests
        alpha: FDR control level (default 0.05 for 5% FDR)

    Returns:
        List of booleans in original order:
        - True: hypothesis rejected (significant after FDR correction)
        - False: hypothesis not rejected (not significant)

    Example:
        >>> p_vals = [0.001, 0.02, 0.03, 0.5, 0.8]
        >>> corrected = correct_multiple_tests(p_vals, alpha=0.05)
        >>> corrected
        [True, True, True, False, False]
    """
    if not p_values:
        return []

    m = len(p_values)

    # Step 1: Create list of (p_value, original_index) and sort by p_value
    indexed_pvals = [(pval, idx) for idx, pval in enumerate(p_values)]
    indexed_pvals.sort(key=lambda x: x[0])

    # Step 2: Find largest k where p_value[k] <= (k/m) * alpha
    # Note: k is 1-indexed (rank), so we use (k+1) for rank 1
    largest_k = 0
    for rank in range(1, m + 1):
        p_val = indexed_pvals[rank - 1][0]
        threshold = (rank / m) * alpha
        if p_val <= threshold:
            largest_k = rank

    # Step 3: Create boolean array for original order
    # Hypotheses at ranks 1..largest_k are rejected (True)
    result = [False] * m
    for rank in range(1, largest_k + 1):
        original_idx = indexed_pvals[rank - 1][1]
        result[original_idx] = True

    return result


def batch_test_significance(signals_by_preference: Dict[str, List[Signal]],
                           alpha: float = 0.05) -> Dict[str, bool]:
    """
    Run significance tests on multiple preferences and apply BH FDR correction.

    This is useful when testing many preferences simultaneously:
    - Each preference's signals are tested for trend significance
    - P-values are collected across all preferences
    - BH procedure applied to control overall FDR
    - Returns dict of {preference_id: is_significant}

    Args:
        signals_by_preference: Dict mapping preference IDs to lists of Signal objects
        alpha: FDR control level (default 0.05)

    Returns:
        Dict[preference_id, is_significant]:
        - True: preference shows significant trend (survives FDR correction)
        - False: preference trend not significant after FDR correction

    Example:
        >>> signals_by = {
        ...     "pref1": [sig1, sig2, sig3],
        ...     "pref2": [sig4, sig5],
        ... }
        >>> results = batch_test_significance(signals_by, alpha=0.05)
        >>> results
        {'pref1': True, 'pref2': False}
    """
    tester = SignificanceTester()
    pref_ids = []
    p_values = []

    # Step 1: Test each preference and collect p-values
    for pref_id, signals in signals_by_preference.items():
        if signals:
            result = tester.test_trend_significance(signals)
            pref_ids.append(pref_id)
            p_values.append(result.p_value)

    # Step 2: Apply BH FDR correction
    if p_values:
        corrected_flags = correct_multiple_tests(p_values, alpha=alpha)
    else:
        corrected_flags = []

    # Step 3: Build result dict
    result_dict = {}
    for pref_id, is_significant in zip(pref_ids, corrected_flags):
        result_dict[pref_id] = is_significant

    return result_dict


def binomial_test_two_tailed(num_positive: int, total: int, null_hypothesis: float = 0.5) -> float:
    """
    Perform two-tailed binomial test.

    Null hypothesis: proportion of positive signals = null_hypothesis
    Alternative: proportion != null_hypothesis

    Args:
        num_positive: Number of positive signals (successes)
        total: Total number of signals
        null_hypothesis: Expected proportion under null (default 0.5)

    Returns:
        Two-tailed p-value
    """
    if total == 0:
        return 1.0

    observed_proportion = num_positive / total

    # For two-tailed test:
    # Calculate probability of observing this extreme or more extreme
    cdf_lower = binomial_cdf(total, null_hypothesis, num_positive)
    cdf_upper = 1.0 - binomial_cdf(total, null_hypothesis, num_positive - 1)

    # Two-tailed p-value
    p_value = 2.0 * min(cdf_lower, cdf_upper)
    p_value = min(p_value, 1.0)  # Cap at 1.0

    return p_value


@dataclass
class TrendResult:
    """
    Result of trend significance testing.

    Attributes:
        significant: Whether trend is statistically significant (p < alpha)
        p_value: Two-tailed p-value from binomial test
        direction: "positive", "negative", or "neutral"
        effect_size: Observed proportion (0.0 to 1.0)
        confidence: Confidence in result (0.0 to 1.0)
        n_signals: Number of signals tested
        autocorrelation: Lag-1 autocorrelation coefficient (-1.0 to 1.0)
        effective_sample_size: Adjusted n accounting for autocorrelation
        adjusted_strength: Recommendation for strength update damping
    """
    significant: bool
    p_value: float
    direction: str
    effect_size: float
    confidence: float
    n_signals: int
    autocorrelation: float
    effective_sample_size: int
    adjusted_strength: float


class SignificanceTester:
    """
    Statistical significance testing for preference signals.

    Prevents treating random noise as real trends by requiring:
    1. Minimum sample size (5 signals)
    2. Statistical significance (binomial test, alpha=0.05)
    3. Autocorrelation detection (reduce effective sample size if correlated)
    4. Selection bias correction (corrections overrepresented vs. uses)
    """

    # Binomial test parameters
    ALPHA_THRESHOLD = 0.05  # 95% confidence level
    MIN_SAMPLE_SIZE = 5     # Minimum signals before claiming significance

    def __init__(self):
        """Initialize the SignificanceTester."""
        pass

    def test_trend_significance(self, signals: List[Signal]) -> TrendResult:
        """
        Test whether a trend in signals is statistically significant.

        Uses binomial test: Is the ratio of positive signals significantly
        different from 0.5 (null hypothesis of random chance)?

        Args:
            signals: List of Signal objects to test

        Returns:
            TrendResult with significance info, p-value, direction, confidence

        Example:
            >>> signals = [Signal(..., type="correction"), ...]
            >>> result = tester.test_trend_significance(signals)
            >>> if result.significant:
            ...     print(f"Real trend detected: {result.direction}")
        """

        # Step 1: Classify signals as positive/negative
        num_positive, num_negative = self._classify_signals(signals)
        total = len(signals)

        # Step 2: Check minimum sample size
        if total < self.MIN_SAMPLE_SIZE:
            return TrendResult(
                significant=False,
                p_value=1.0,
                direction="neutral",
                effect_size=num_positive / total if total > 0 else 0.0,
                confidence=0.0,
                n_signals=total,
                autocorrelation=0.0,
                effective_sample_size=total,
                adjusted_strength=0.0
            )

        # Step 3: Perform binomial test
        p_value = binomial_test_two_tailed(num_positive, total)

        # Step 4: Detect autocorrelation
        autocorr = self.detect_autocorrelation(signals)

        # Step 5: Calculate effective sample size
        effective_n = self._adjust_for_autocorrelation(total, autocorr)

        # Step 6: Re-test with effective sample size if needed
        # Note: Ensure effective_n >= num_positive to avoid invalid binomial test
        if effective_n < total and autocorr > 0.1:
            # Only recalculate if there's meaningful autocorrelation
            # Use max(effective_n, num_positive) to avoid impossible scenarios
            test_n = max(effective_n, num_positive)
            p_value = binomial_test_two_tailed(num_positive, test_n)
            effective_n = test_n

        # Step 7: Determine significance and direction
        is_significant = p_value < self.ALPHA_THRESHOLD

        effect_size = num_positive / total
        if effect_size > 0.5:
            direction = "positive"
        elif effect_size < 0.5:
            direction = "negative"
        else:
            direction = "neutral"

        # Step 8: Calculate confidence
        # Higher confidence when: small p-value + large effective sample
        confidence = 1.0 - p_value if is_significant else 0.0
        confidence = max(0.0, min(confidence, 1.0))

        # Step 9: Calculate adjusted strength update recommendation
        adjusted_strength = self._calculate_adjusted_strength(
            is_significant,
            effect_size,
            autocorr
        )

        return TrendResult(
            significant=is_significant,
            p_value=p_value,
            direction=direction,
            effect_size=effect_size,
            confidence=confidence,
            n_signals=total,
            autocorrelation=autocorr,
            effective_sample_size=effective_n,
            adjusted_strength=adjusted_strength
        )

    def detect_autocorrelation(self, signals: List[Signal]) -> float:
        """
        Detect if signals are autocorrelated (user corrects in bursts vs randomly).

        Uses lag-1 autocorrelation (Durbin-Watson style):
        If positive autocorrelation: user tends to correct multiple times in succession
        This reduces effective sample size (10 correlated signals != 10 independent points)

        Autocorrelation = Cov(X_t, X_{t-1}) / Var(X)

        Args:
            signals: List of signals in chronological order

        Returns:
            Lag-1 autocorrelation coefficient (-1.0 to 1.0)
            0.0 = no autocorrelation (independent)
            > 0.0 = positive autocorrelation (signals cluster)
            < 0.0 = negative autocorrelation (signals alternate)
        """

        if len(signals) < 2:
            return 0.0

        # Convert signals to binary series: 1 for positive signal, 0 for negative
        signal_series = self._signals_to_binary(signals)

        if len(signal_series) < 2:
            return 0.0

        # Calculate mean
        mean = sum(signal_series) / len(signal_series)

        # Calculate variance
        variance = sum((x - mean) ** 2 for x in signal_series) / len(signal_series)

        if variance == 0:
            return 0.0

        # Calculate lag-1 covariance
        covariance = 0.0
        for i in range(1, len(signal_series)):
            covariance += (signal_series[i] - mean) * (signal_series[i - 1] - mean)

        covariance /= len(signal_series)

        # Autocorrelation coefficient
        autocorr = covariance / variance

        return max(-1.0, min(autocorr, 1.0))  # Clamp to [-1, 1]

    def adjust_for_selection_bias(self,
                                  strength: float,
                                  signal_count: int,
                                  feedback_rate: float) -> float:
        """
        Adjust preference strength for selection bias.

        Only corrections get recorded — positive uses are underrepresented.
        This biases learning toward "corrections" over "smooth satisfaction".

        Apply Thompson Sampling exploration bonus for low-data preferences:
        Preferences with few observations should be explored more (higher uncertainty).

        Args:
            strength: Current calculated strength (0.0 to 1.0)
            signal_count: Number of signals (corrections/feedback) recorded
            feedback_rate: Proportion of positive signals (0.0 to 1.0)

        Returns:
            Adjusted strength with selection bias and exploration bonus applied
        """

        # Thompson Sampling exploration bonus
        # Lower n → higher bonus (encourage exploration)
        exploration_bonus = self.exploration_bonus(signal_count)

        # Adjust for selection bias
        # If feedback_rate is extreme (very high or very low), we may be
        # seeing only corrections, not actual satisfaction distribution

        # Bias correction: pull extreme values toward 0.5
        # More aggressive correction for low signal count
        bias_correction_factor = 0.95 ** (signal_count / 10.0)  # Decays as we collect more data

        # If signal_count is low, we're very uncertain, so pull toward center
        if signal_count < 10:
            adjusted_strength = strength * bias_correction_factor + 0.5 * (1 - bias_correction_factor)
        else:
            adjusted_strength = strength

        # Apply exploration bonus
        # Higher bonus → higher uncertainty → more exploration
        adjusted_strength = adjusted_strength * (1.0 - exploration_bonus * 0.1) + exploration_bonus * 0.1

        return max(0.0, min(adjusted_strength, 1.0))

    def exploration_bonus(self, n_observations: int) -> float:
        """
        Calculate Thompson Sampling exploration bonus.

        Thompson Sampling adds uncertainty to low-data preferences to encourage exploration.

        Bonus decreases as n increases (more data → less exploration needed)

        Args:
            n_observations: Number of observations/signals

        Returns:
            Exploration bonus (0.0 to 1.0)
            0.0 = no exploration bonus (high confidence)
            1.0 = maximum exploration bonus (very uncertain)
        """

        # Exponential decay: bonus = e^(-0.1 * n)
        # This gives:
        # At n=0: bonus = 1.0
        # At n=5: bonus ≈ 0.606
        # At n=10: bonus ≈ 0.368
        # At n=25: bonus ≈ 0.082

        bonus = math.exp(-0.1 * n_observations)

        return max(0.0, min(bonus, 1.0))

    # ---- Private Helper Methods ----

    def _classify_signals(self, signals: List[Signal]) -> tuple[int, int]:
        """
        Classify signals as positive or negative.

        A signal is positive if it indicates user satisfaction/confirmation.
        - correction: positive if user_corrected_to matches a desired pattern
        - feedback: positive if emotional_tone is "satisfied"
        - usage: positive (indicates preference was used)

        For simplicity: treat all corrections as positive signals for now.
        Can be extended with semantic analysis.

        Returns:
            (num_positive, num_negative)
        """
        num_positive = 0
        num_negative = 0

        for signal in signals:
            if signal.type == "correction":
                # Corrections indicate dissatisfaction with proposed
                # Treat as positive signal toward corrected_to
                num_positive += 1
            elif signal.type == "feedback":
                # Feedback signals explicit satisfaction
                if signal.emotional_tone == "satisfied":
                    num_positive += 1
                elif signal.emotional_tone == "frustrated":
                    num_negative += 1
                else:
                    # Neutral treated as mildly positive (still recording)
                    num_positive += 1
            elif signal.type == "usage":
                # Usage indicates positive preference
                num_positive += 1
            elif signal.type == "override":
                # Override indicates dissatisfaction
                num_negative += 1

        return num_positive, num_negative

    def _signals_to_binary(self, signals: List[Signal]) -> List[int]:
        """
        Convert signals to binary series for autocorrelation calculation.

        1 = positive signal, 0 = negative signal
        """
        binary = []
        for signal in signals:
            if signal.type == "correction":
                binary.append(1)
            elif signal.type == "feedback":
                binary.append(1 if signal.emotional_tone == "satisfied" else 0)
            elif signal.type == "usage":
                binary.append(1)
            elif signal.type == "override":
                binary.append(0)

        return binary

    def _adjust_for_autocorrelation(self, n: int, autocorr: float) -> int:
        """
        Adjust sample size for autocorrelation.

        If signals are autocorrelated, they're not independent.
        10 positively correlated signals don't give 10x information.

        Effective n = n / (1 + 2 * autocorr)

        Args:
            n: Original sample size
            autocorr: Lag-1 autocorrelation coefficient

        Returns:
            Effective sample size (adjusted for correlation)
        """

        if autocorr <= 0:
            # No positive autocorrelation, use full sample size
            return n

        # If positively autocorrelated, reduce effective sample size
        # Formula: n_eff = n / (1 + 2*rho) where rho is autocorrelation
        # This accounts for the loss of independence

        effective_n = int(n / (1.0 + 2.0 * autocorr))

        # Ensure effective n is at least 1
        return max(1, effective_n)

    def _calculate_adjusted_strength(self,
                                     is_significant: bool,
                                     effect_size: float,
                                     autocorr: float) -> float:
        """
        Calculate recommendation for strength update damping.

        If the signal is NOT statistically significant:
        - Apply 50% damping (only update by 50% of normal amount)

        If autocorrelated:
        - Apply additional damping proportional to autocorrelation

        Returns:
            Adjustment factor (0.0 to 1.0) to multiply with strength update
            1.0 = full update
            0.5 = 50% update (damped)
            0.0 = no update (completely damped)
        """

        if not is_significant:
            # Not significant: apply 50% damping
            adjustment = 0.5
        else:
            # Significant: full update
            adjustment = 1.0

        # Apply autocorrelation damping (reduce if highly correlated)
        if autocorr > 0.3:
            autocorr_damping = 1.0 - (autocorr * 0.3)  # Up to 30% additional damping
            adjustment *= autocorr_damping

        return max(0.0, min(adjustment, 1.0))


class SignificanceAwareSignalProcessor:
    """
    Wraps a standard SignalProcessor to add statistical significance checks.

    Before updating a preference strength:
    1. Check if signal is statistically significant
    2. If not significant: apply 50% damping to update
    3. If autocorrelated: apply effective sample size correction
    4. Log when significance testing causes damping

    This prevents noise from being treated as real preference changes.
    """

    def __init__(self, base_processor, significance_tester: Optional[SignificanceTester] = None):
        """
        Initialize wrapper.

        Args:
            base_processor: The underlying SignalProcessor to wrap
            significance_tester: Optional SignificanceTester (creates new if not provided)
        """
        self.processor = base_processor
        self.tester = significance_tester or SignificanceTester()
        self.update_log = []

    def process_correction_with_significance(self,
                                            task: str,
                                            context_tags: List[str],
                                            agent_proposed: str,
                                            user_corrected_to: str,
                                            user_message: str = "",
                                            recent_signals: Optional[List[Signal]] = None) -> Dict:
        """
        Process a correction with significance testing.

        Args:
            task: Task context
            context_tags: Context tags
            agent_proposed: Agent's proposed value
            user_corrected_to: User's correction
            user_message: User's message
            recent_signals: Recent signals to test significance (if None, just process)

        Returns:
            Dictionary with:
            - signal: The created Signal
            - result: TrendResult from significance testing (if available)
            - adjustment_factor: How much the update was damped (1.0 = no damping)
            - log_entry: Description of what happened
        """

        # First, process normally
        signal = self.processor.process_correction(
            task=task,
            context_tags=context_tags,
            agent_proposed=agent_proposed,
            user_corrected_to=user_corrected_to,
            user_message=user_message
        )

        result = None
        adjustment_factor = 1.0
        log_entry = ""

        # If we have recent signals, test significance
        if recent_signals is not None and len(recent_signals) > 0:
            result = self.tester.test_trend_significance(recent_signals)
            adjustment_factor = result.adjusted_strength

            if adjustment_factor < 1.0:
                log_entry = (
                    f"Significance damping applied: p={result.p_value:.3f}, "
                    f"effect_size={result.effect_size:.2f}, "
                    f"autocorr={result.autocorrelation:.2f}, "
                    f"adjustment={adjustment_factor:.2f}"
                )
            else:
                log_entry = f"Signal significant: p={result.p_value:.3f}, effect_size={result.effect_size:.2f}"

        # Log the update
        if log_entry:
            self.update_log.append({
                "timestamp": signal.timestamp,
                "pref_id": user_corrected_to,
                "log": log_entry
            })

        return {
            "signal": signal,
            "result": result,
            "adjustment_factor": adjustment_factor,
            "log_entry": log_entry
        }

    def get_update_log(self) -> List[Dict]:
        """
        Get log of all significance-based updates.

        Returns:
            List of log entries with timestamp, preference, and reason
        """
        return self.update_log.copy()
