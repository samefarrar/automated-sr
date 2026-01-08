"""Analysis module for secondary filtering and meta-analysis."""

from automated_sr.analysis.filters import FilterReason, FilterResult, SecondaryFilter
from automated_sr.analysis.forest_plot import ForestPlot, create_comparison_forest_plot
from automated_sr.analysis.statistics import (
    EffectMeasure,
    EffectSize,
    MetaAnalysis,
    PooledEffect,
    PoolingMethod,
)

__all__ = [
    # Filters
    "FilterReason",
    "FilterResult",
    "SecondaryFilter",
    # Statistics
    "EffectMeasure",
    "EffectSize",
    "MetaAnalysis",
    "PooledEffect",
    "PoolingMethod",
    # Forest plots
    "ForestPlot",
    "create_comparison_forest_plot",
]
