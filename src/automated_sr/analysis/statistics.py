"""Statistical functions for meta-analysis.

Implements effect size calculations and pooling methods commonly used in
systematic reviews and meta-analyses.

Supported effect measures:
- Mean Difference (MD)
- Standardized Mean Difference (SMD / Hedges' g)
- Odds Ratio (OR)
- Risk Ratio (RR)

Pooling methods:
- Fixed effects (inverse-variance weighted)
- Random effects (DerSimonian-Laird)
"""

import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


class EffectMeasure(str, Enum):
    """Supported effect size measures."""

    MD = "MD"  # Mean Difference
    SMD = "SMD"  # Standardized Mean Difference
    OR = "OR"  # Odds Ratio
    RR = "RR"  # Risk Ratio


class PoolingMethod(str, Enum):
    """Meta-analysis pooling methods."""

    FIXED = "fixed"
    RANDOM = "random"


@dataclass
class EffectSize:
    """Represents a single study effect size."""

    study_id: int
    study_name: str
    effect: float  # The effect size value
    se: float  # Standard error
    ci_lower: float  # 95% CI lower bound
    ci_upper: float  # 95% CI upper bound
    weight: float | None = None  # Weight in meta-analysis
    n_total: int | None = None  # Total sample size


@dataclass
class PooledEffect:
    """Result of meta-analysis pooling."""

    effect: float  # Pooled effect size
    se: float  # Standard error of pooled effect
    ci_lower: float  # 95% CI lower bound
    ci_upper: float  # 95% CI upper bound
    z_score: float  # Z-score for significance test
    p_value: float  # Two-tailed p-value
    i_squared: float  # Heterogeneity (I-squared, 0-100%)
    tau_squared: float | None  # Between-study variance (random effects only)
    q_statistic: float  # Cochran's Q statistic
    df: int  # Degrees of freedom
    method: PoolingMethod  # Pooling method used
    n_studies: int  # Number of studies included


class MetaAnalysis:
    """Performs statistical meta-analysis calculations."""

    @staticmethod
    def calculate_mean_difference(
        mean1: float,
        sd1: float,
        n1: int,
        mean2: float,
        sd2: float,
        n2: int,
        study_id: int = 0,
        study_name: str = "",
    ) -> EffectSize:
        """
        Calculate mean difference between two groups.

        Args:
            mean1: Mean of treatment/intervention group
            sd1: Standard deviation of treatment group
            n1: Sample size of treatment group
            mean2: Mean of control/comparison group
            sd2: Standard deviation of control group
            n2: Sample size of control group
            study_id: Study identifier
            study_name: Study name for display

        Returns:
            EffectSize with mean difference and standard error
        """
        md = mean1 - mean2
        se = np.sqrt((sd1**2 / n1) + (sd2**2 / n2))
        ci_lower = md - 1.96 * se
        ci_upper = md + 1.96 * se

        return EffectSize(
            study_id=study_id,
            study_name=study_name,
            effect=float(md),
            se=float(se),
            ci_lower=float(ci_lower),
            ci_upper=float(ci_upper),
            n_total=n1 + n2,
        )

    @staticmethod
    def calculate_standardized_mean_difference(
        mean1: float,
        sd1: float,
        n1: int,
        mean2: float,
        sd2: float,
        n2: int,
        study_id: int = 0,
        study_name: str = "",
    ) -> EffectSize:
        """
        Calculate standardized mean difference (Hedges' g).

        Uses pooled standard deviation and Hedges' correction for small samples.

        Args:
            mean1: Mean of treatment/intervention group
            sd1: Standard deviation of treatment group
            n1: Sample size of treatment group
            mean2: Mean of control/comparison group
            sd2: Standard deviation of control group
            n2: Sample size of control group
            study_id: Study identifier
            study_name: Study name for display

        Returns:
            EffectSize with standardized mean difference
        """
        # Pooled standard deviation
        pooled_sd = np.sqrt(((n1 - 1) * sd1**2 + (n2 - 1) * sd2**2) / (n1 + n2 - 2))

        # Cohen's d
        d = (mean1 - mean2) / pooled_sd

        # Hedges' correction factor (small sample correction)
        j = 1 - (3 / (4 * (n1 + n2 - 2) - 1))
        g = d * j

        # Standard error of Hedges' g
        se = np.sqrt((n1 + n2) / (n1 * n2) + g**2 / (2 * (n1 + n2)))

        ci_lower = g - 1.96 * se
        ci_upper = g + 1.96 * se

        return EffectSize(
            study_id=study_id,
            study_name=study_name,
            effect=float(g),
            se=float(se),
            ci_lower=float(ci_lower),
            ci_upper=float(ci_upper),
            n_total=n1 + n2,
        )

    @staticmethod
    def calculate_odds_ratio(
        events1: int,
        total1: int,
        events2: int,
        total2: int,
        study_id: int = 0,
        study_name: str = "",
    ) -> EffectSize:
        """
        Calculate odds ratio between two groups.

        Uses 0.5 continuity correction for zero cells.

        Args:
            events1: Number of events in treatment group
            total1: Total in treatment group
            events2: Number of events in control group
            total2: Total in control group
            study_id: Study identifier
            study_name: Study name for display

        Returns:
            EffectSize with odds ratio (on natural log scale internally, exponentiated for display)
        """
        # Add 0.5 continuity correction if any cell is zero
        a = events1 + 0.5
        b = (total1 - events1) + 0.5
        c = events2 + 0.5
        d = (total2 - events2) + 0.5

        log_or = np.log((a * d) / (b * c))
        se = np.sqrt(1 / a + 1 / b + 1 / c + 1 / d)

        # Confidence interval on log scale, then exponentiate
        ci_lower = np.exp(log_or - 1.96 * se)
        ci_upper = np.exp(log_or + 1.96 * se)

        return EffectSize(
            study_id=study_id,
            study_name=study_name,
            effect=float(np.exp(log_or)),
            se=float(se),  # SE is on log scale
            ci_lower=float(ci_lower),
            ci_upper=float(ci_upper),
            n_total=total1 + total2,
        )

    @staticmethod
    def calculate_risk_ratio(
        events1: int,
        total1: int,
        events2: int,
        total2: int,
        study_id: int = 0,
        study_name: str = "",
    ) -> EffectSize:
        """
        Calculate risk ratio between two groups.

        Uses 0.5 continuity correction for zero cells.

        Args:
            events1: Number of events in treatment group
            total1: Total in treatment group
            events2: Number of events in control group
            total2: Total in control group
            study_id: Study identifier
            study_name: Study name for display

        Returns:
            EffectSize with risk ratio
        """
        # Add 0.5 continuity correction if needed
        e1 = events1 + 0.5 if events1 == 0 or events1 == total1 else events1
        t1 = total1 + 1 if events1 == 0 or events1 == total1 else total1
        e2 = events2 + 0.5 if events2 == 0 or events2 == total2 else events2
        t2 = total2 + 1 if events2 == 0 or events2 == total2 else total2

        p1 = e1 / t1
        p2 = e2 / t2

        log_rr = np.log(p1 / p2)
        se = np.sqrt((1 - p1) / e1 + (1 - p2) / e2)

        ci_lower = np.exp(log_rr - 1.96 * se)
        ci_upper = np.exp(log_rr + 1.96 * se)

        return EffectSize(
            study_id=study_id,
            study_name=study_name,
            effect=float(np.exp(log_rr)),
            se=float(se),  # SE is on log scale
            ci_lower=float(ci_lower),
            ci_upper=float(ci_upper),
            n_total=total1 + total2,
        )

    @staticmethod
    def fixed_effects(effects: list[EffectSize], log_scale: bool = False) -> PooledEffect:
        """
        Inverse-variance weighted fixed effects meta-analysis.

        Args:
            effects: List of EffectSize objects from individual studies
            log_scale: If True, effects are on log scale (for OR, RR)

        Returns:
            PooledEffect with pooled estimate and heterogeneity statistics
        """
        if len(effects) == 0:
            raise ValueError("No effects to pool")

        # Get effect values (transform to log scale if needed)
        if log_scale:
            effect_values = [np.log(e.effect) if e.effect > 0 else 0 for e in effects]
        else:
            effect_values = [e.effect for e in effects]

        # Inverse-variance weights
        weights = [1 / (e.se**2) for e in effects]
        total_weight = sum(weights)

        # Pooled effect
        pooled = sum(w * e for w, e in zip(weights, effect_values, strict=False)) / total_weight
        se = np.sqrt(1 / total_weight)

        # Heterogeneity: Cochran's Q
        q = sum(w * (e - pooled) ** 2 for w, e in zip(weights, effect_values, strict=False))
        df = len(effects) - 1
        i_squared = max(0, (q - df) / q * 100) if q > 0 else 0

        # Significance test
        z = pooled / se
        p_value = 2 * (1 - stats.norm.cdf(abs(z)))

        # Transform back from log scale if needed
        if log_scale:
            effect_final = float(np.exp(pooled))
            ci_lower = float(np.exp(pooled - 1.96 * se))
            ci_upper = float(np.exp(pooled + 1.96 * se))
        else:
            effect_final = float(pooled)
            ci_lower = float(pooled - 1.96 * se)
            ci_upper = float(pooled + 1.96 * se)

        # Assign weights back to effects
        for effect, weight in zip(effects, weights, strict=False):
            effect.weight = weight / total_weight * 100  # As percentage

        return PooledEffect(
            effect=effect_final,
            se=float(se),
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            z_score=float(z),
            p_value=float(p_value),
            i_squared=float(i_squared),
            tau_squared=None,
            q_statistic=float(q),
            df=df,
            method=PoolingMethod.FIXED,
            n_studies=len(effects),
        )

    @staticmethod
    def random_effects(effects: list[EffectSize], log_scale: bool = False) -> PooledEffect:
        """
        DerSimonian-Laird random effects meta-analysis.

        Args:
            effects: List of EffectSize objects from individual studies
            log_scale: If True, effects are on log scale (for OR, RR)

        Returns:
            PooledEffect with pooled estimate and heterogeneity statistics
        """
        if len(effects) == 0:
            raise ValueError("No effects to pool")

        # First run fixed effects to get Q statistic
        fixed = MetaAnalysis.fixed_effects(effects, log_scale=log_scale)

        # Get effect values
        if log_scale:
            effect_values = [np.log(e.effect) if e.effect > 0 else 0 for e in effects]
        else:
            effect_values = [e.effect for e in effects]

        # Fixed effects weights
        fe_weights = [1 / (e.se**2) for e in effects]

        # Calculate tau-squared (between-study variance)
        c = sum(fe_weights) - sum(w**2 for w in fe_weights) / sum(fe_weights)
        tau_sq = max(0, (fixed.q_statistic - fixed.df) / c) if c > 0 else 0

        # Random effects weights
        re_weights = [1 / (e.se**2 + tau_sq) for e in effects]
        total_weight = sum(re_weights)

        # Pooled effect with random effects weights
        pooled = sum(w * e for w, e in zip(re_weights, effect_values, strict=False)) / total_weight
        se = np.sqrt(1 / total_weight)

        # Significance test
        z = pooled / se
        p_value = 2 * (1 - stats.norm.cdf(abs(z)))

        # Transform back from log scale if needed
        if log_scale:
            effect_final = float(np.exp(pooled))
            ci_lower = float(np.exp(pooled - 1.96 * se))
            ci_upper = float(np.exp(pooled + 1.96 * se))
        else:
            effect_final = float(pooled)
            ci_lower = float(pooled - 1.96 * se)
            ci_upper = float(pooled + 1.96 * se)

        # Assign weights back to effects
        for effect, weight in zip(effects, re_weights, strict=False):
            effect.weight = weight / total_weight * 100  # As percentage

        return PooledEffect(
            effect=effect_final,
            se=float(se),
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            z_score=float(z),
            p_value=float(p_value),
            i_squared=fixed.i_squared,
            tau_squared=float(tau_sq),
            q_statistic=fixed.q_statistic,
            df=fixed.df,
            method=PoolingMethod.RANDOM,
            n_studies=len(effects),
        )

    @staticmethod
    def pool(
        effects: list[EffectSize],
        method: PoolingMethod = PoolingMethod.RANDOM,
        effect_measure: EffectMeasure = EffectMeasure.MD,
    ) -> PooledEffect:
        """
        Pool effect sizes using the specified method.

        Args:
            effects: List of EffectSize objects
            method: Pooling method (fixed or random effects)
            effect_measure: Type of effect measure (determines if log scale needed)

        Returns:
            PooledEffect with pooled estimate
        """
        # OR and RR are calculated on log scale
        log_scale = effect_measure in (EffectMeasure.OR, EffectMeasure.RR)

        if method == PoolingMethod.FIXED:
            return MetaAnalysis.fixed_effects(effects, log_scale=log_scale)
        else:
            return MetaAnalysis.random_effects(effects, log_scale=log_scale)
