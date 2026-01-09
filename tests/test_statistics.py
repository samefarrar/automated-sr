"""Tests for meta-analysis statistics."""

import pytest

from automated_sr.analysis.statistics import (
    EffectMeasure,
    EffectSize,
    MetaAnalysis,
    PoolingMethod,
)


class TestEffectMeasure:
    """Tests for EffectMeasure enum."""

    def test_effect_measure_values(self) -> None:
        """Test effect measure enum values."""
        assert EffectMeasure.MD.value == "MD"
        assert EffectMeasure.SMD.value == "SMD"
        assert EffectMeasure.OR.value == "OR"
        assert EffectMeasure.RR.value == "RR"


class TestPoolingMethod:
    """Tests for PoolingMethod enum."""

    def test_pooling_method_values(self) -> None:
        """Test pooling method enum values."""
        assert PoolingMethod.FIXED.value == "fixed"
        assert PoolingMethod.RANDOM.value == "random"


class TestMeanDifference:
    """Tests for mean difference calculation."""

    def test_mean_difference_positive(self) -> None:
        """Test positive mean difference."""
        result = MetaAnalysis.calculate_mean_difference(
            mean1=10.0,
            sd1=2.0,
            n1=50,
            mean2=8.0,
            sd2=2.5,
            n2=50,
            study_id=1,
            study_name="Test Study",
        )
        assert result.effect == pytest.approx(2.0, rel=0.01)
        assert result.ci_lower < result.effect < result.ci_upper
        assert result.n_total == 100

    def test_mean_difference_negative(self) -> None:
        """Test negative mean difference."""
        result = MetaAnalysis.calculate_mean_difference(mean1=5.0, sd1=1.0, n1=30, mean2=7.0, sd2=1.0, n2=30)
        assert result.effect == pytest.approx(-2.0, rel=0.01)

    def test_mean_difference_zero(self) -> None:
        """Test zero mean difference."""
        result = MetaAnalysis.calculate_mean_difference(mean1=10.0, sd1=2.0, n1=50, mean2=10.0, sd2=2.0, n2=50)
        assert result.effect == pytest.approx(0.0, abs=0.01)


class TestStandardizedMeanDifference:
    """Tests for standardized mean difference (Hedges' g) calculation."""

    def test_smd_moderate_effect(self) -> None:
        """Test SMD for moderate effect size."""
        result = MetaAnalysis.calculate_standardized_mean_difference(
            mean1=10.0, sd1=2.0, n1=50, mean2=8.0, sd2=2.0, n2=50
        )
        # Cohen's d would be 1.0, Hedges' g slightly smaller
        assert 0.9 < result.effect < 1.1
        assert result.ci_lower < result.effect < result.ci_upper

    def test_smd_small_sample_correction(self) -> None:
        """Test that small samples have Hedges' correction applied."""
        # Small sample
        small = MetaAnalysis.calculate_standardized_mean_difference(
            mean1=10.0, sd1=2.0, n1=10, mean2=8.0, sd2=2.0, n2=10
        )
        # Large sample
        large = MetaAnalysis.calculate_standardized_mean_difference(
            mean1=10.0, sd1=2.0, n1=100, mean2=8.0, sd2=2.0, n2=100
        )
        # Small sample should have more correction (lower effect)
        assert small.effect < large.effect


class TestOddsRatio:
    """Tests for odds ratio calculation."""

    def test_odds_ratio_equal_odds(self) -> None:
        """Test OR when odds are equal (should be ~1)."""
        result = MetaAnalysis.calculate_odds_ratio(events1=10, total1=100, events2=10, total2=100)
        assert result.effect == pytest.approx(1.0, rel=0.1)

    def test_odds_ratio_higher_treatment(self) -> None:
        """Test OR when treatment has higher odds."""
        result = MetaAnalysis.calculate_odds_ratio(events1=30, total1=100, events2=10, total2=100)
        assert result.effect > 1.0

    def test_odds_ratio_lower_treatment(self) -> None:
        """Test OR when treatment has lower odds."""
        result = MetaAnalysis.calculate_odds_ratio(events1=10, total1=100, events2=30, total2=100)
        assert result.effect < 1.0

    def test_odds_ratio_zero_events(self) -> None:
        """Test OR with zero events (continuity correction)."""
        result = MetaAnalysis.calculate_odds_ratio(events1=0, total1=50, events2=5, total2=50)
        # Should handle zero without error
        assert result.effect >= 0
        assert result.ci_lower > 0  # CI should be positive


class TestRiskRatio:
    """Tests for risk ratio calculation."""

    def test_risk_ratio_equal_risk(self) -> None:
        """Test RR when risks are equal (should be ~1)."""
        result = MetaAnalysis.calculate_risk_ratio(events1=10, total1=100, events2=10, total2=100)
        assert result.effect == pytest.approx(1.0, rel=0.1)

    def test_risk_ratio_doubled_risk(self) -> None:
        """Test RR when treatment has double the risk."""
        result = MetaAnalysis.calculate_risk_ratio(events1=20, total1=100, events2=10, total2=100)
        assert result.effect == pytest.approx(2.0, rel=0.1)


class TestFixedEffects:
    """Tests for fixed effects meta-analysis."""

    @pytest.fixture
    def three_studies(self) -> list[EffectSize]:
        """Create three study effect sizes."""
        return [
            EffectSize(study_id=1, study_name="Study A", effect=0.5, se=0.1, ci_lower=0.3, ci_upper=0.7),
            EffectSize(study_id=2, study_name="Study B", effect=0.6, se=0.15, ci_lower=0.3, ci_upper=0.9),
            EffectSize(study_id=3, study_name="Study C", effect=0.4, se=0.12, ci_lower=0.16, ci_upper=0.64),
        ]

    def test_fixed_effects_pooled_estimate(self, three_studies: list[EffectSize]) -> None:
        """Test pooled estimate is weighted average."""
        result = MetaAnalysis.fixed_effects(three_studies)
        # Pooled should be between individual effects
        assert 0.4 <= result.effect <= 0.6

    def test_fixed_effects_assigns_weights(self, three_studies: list[EffectSize]) -> None:
        """Test that weights are assigned to studies."""
        MetaAnalysis.fixed_effects(three_studies)
        for study in three_studies:
            assert study.weight is not None
            assert study.weight > 0

    def test_fixed_effects_weights_sum_to_100(self, three_studies: list[EffectSize]) -> None:
        """Test that weights sum to 100%."""
        MetaAnalysis.fixed_effects(three_studies)
        total_weight = sum(s.weight for s in three_studies if s.weight)
        assert total_weight == pytest.approx(100.0, rel=0.01)

    def test_fixed_effects_heterogeneity(self, three_studies: list[EffectSize]) -> None:
        """Test heterogeneity statistics are calculated."""
        result = MetaAnalysis.fixed_effects(three_studies)
        assert result.i_squared >= 0
        assert result.i_squared <= 100
        assert result.q_statistic >= 0

    def test_fixed_effects_empty_raises(self) -> None:
        """Test that empty list raises error."""
        with pytest.raises(ValueError, match="No effects to pool"):
            MetaAnalysis.fixed_effects([])

    def test_fixed_effects_method_is_fixed(self, three_studies: list[EffectSize]) -> None:
        """Test that method is set to fixed."""
        result = MetaAnalysis.fixed_effects(three_studies)
        assert result.method == PoolingMethod.FIXED


class TestRandomEffects:
    """Tests for random effects meta-analysis."""

    @pytest.fixture
    def heterogeneous_studies(self) -> list[EffectSize]:
        """Create studies with high heterogeneity."""
        return [
            EffectSize(study_id=1, study_name="Study A", effect=0.2, se=0.1, ci_lower=0.0, ci_upper=0.4),
            EffectSize(study_id=2, study_name="Study B", effect=0.8, se=0.1, ci_lower=0.6, ci_upper=1.0),
            EffectSize(study_id=3, study_name="Study C", effect=0.5, se=0.1, ci_lower=0.3, ci_upper=0.7),
        ]

    def test_random_effects_calculates_tau_squared(self, heterogeneous_studies: list[EffectSize]) -> None:
        """Test tau-squared is calculated."""
        result = MetaAnalysis.random_effects(heterogeneous_studies)
        assert result.tau_squared is not None
        assert result.tau_squared >= 0

    def test_random_effects_method_is_random(self, heterogeneous_studies: list[EffectSize]) -> None:
        """Test that method is set to random."""
        result = MetaAnalysis.random_effects(heterogeneous_studies)
        assert result.method == PoolingMethod.RANDOM

    def test_random_effects_wider_ci_with_heterogeneity(self, heterogeneous_studies: list[EffectSize]) -> None:
        """Test that random effects has wider CI with heterogeneity."""
        fixed = MetaAnalysis.fixed_effects(heterogeneous_studies)
        random = MetaAnalysis.random_effects(heterogeneous_studies)

        fixed_width = fixed.ci_upper - fixed.ci_lower
        random_width = random.ci_upper - random.ci_lower

        # Random effects should have wider CI (or equal if no heterogeneity)
        assert random_width >= fixed_width - 0.01  # Small tolerance


class TestPool:
    """Tests for the pool convenience function."""

    @pytest.fixture
    def studies(self) -> list[EffectSize]:
        """Create sample studies."""
        return [
            EffectSize(study_id=1, study_name="A", effect=0.5, se=0.1, ci_lower=0.3, ci_upper=0.7),
            EffectSize(study_id=2, study_name="B", effect=0.6, se=0.1, ci_lower=0.4, ci_upper=0.8),
        ]

    def test_pool_fixed(self, studies: list[EffectSize]) -> None:
        """Test pool with fixed effects."""
        result = MetaAnalysis.pool(studies, method=PoolingMethod.FIXED)
        assert result.method == PoolingMethod.FIXED

    def test_pool_random(self, studies: list[EffectSize]) -> None:
        """Test pool with random effects."""
        result = MetaAnalysis.pool(studies, method=PoolingMethod.RANDOM)
        assert result.method == PoolingMethod.RANDOM

    def test_pool_defaults_to_random(self, studies: list[EffectSize]) -> None:
        """Test that pool defaults to random effects."""
        result = MetaAnalysis.pool(studies)
        assert result.method == PoolingMethod.RANDOM
