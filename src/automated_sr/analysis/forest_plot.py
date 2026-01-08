"""Forest plot visualization for meta-analysis results."""

import logging
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from automated_sr.analysis.statistics import EffectMeasure, EffectSize, PooledEffect

logger = logging.getLogger(__name__)


class ForestPlot:
    """Generates forest plots for meta-analysis visualization.

    Forest plots display individual study effect sizes as points with confidence
    interval lines, and the pooled effect as a diamond at the bottom.
    """

    def __init__(
        self,
        effect_measure: EffectMeasure = EffectMeasure.MD,
        show_weights: bool = True,
        show_heterogeneity: bool = True,
        figsize: tuple[float, float] | None = None,
    ) -> None:
        """
        Initialize the forest plot generator.

        Args:
            effect_measure: Type of effect measure (MD, SMD, OR, RR)
            show_weights: Whether to show study weights
            show_heterogeneity: Whether to show heterogeneity statistics
            figsize: Figure size (width, height) in inches. If None, auto-calculated.
        """
        self.effect_measure = effect_measure
        self.show_weights = show_weights
        self.show_heterogeneity = show_heterogeneity
        self.figsize = figsize

    def _get_null_value(self) -> float:
        """Get the null effect value (no effect line)."""
        if self.effect_measure in (EffectMeasure.OR, EffectMeasure.RR):
            return 1.0
        return 0.0

    def _format_effect(self, value: float) -> str:
        """Format an effect size value for display."""
        if self.effect_measure in (EffectMeasure.OR, EffectMeasure.RR):
            return f"{value:.2f}"
        return f"{value:.2f}"

    def create(
        self,
        effects: list[EffectSize],
        pooled: PooledEffect,
        title: str = "Forest Plot",
    ) -> Figure:
        """
        Create a forest plot figure.

        Args:
            effects: List of individual study effect sizes
            pooled: Pooled effect from meta-analysis
            title: Plot title

        Returns:
            Matplotlib Figure object
        """
        n_studies = len(effects)

        # Calculate figure size
        if self.figsize:
            fig_width, fig_height = self.figsize
        else:
            fig_height = max(6, n_studies * 0.4 + 3)
            fig_width = 12

        fig, ax = plt.subplots(figsize=(fig_width, fig_height))

        # Y positions for studies (top to bottom)
        y_positions = list(range(n_studies, 0, -1))

        # Determine x-axis range
        all_ci_lower = [e.ci_lower for e in effects] + [pooled.ci_lower]
        all_ci_upper = [e.ci_upper for e in effects] + [pooled.ci_upper]
        x_min = min(all_ci_lower) * 1.1 if min(all_ci_lower) < 0 else min(all_ci_lower) * 0.9
        x_max = max(all_ci_upper) * 1.1

        # For ratio measures, use log scale
        if self.effect_measure in (EffectMeasure.OR, EffectMeasure.RR):
            ax.set_xscale("log")
            x_min = max(0.01, min(all_ci_lower) * 0.8)
            x_max = max(all_ci_upper) * 1.2

        # Plot each study
        for effect, y in zip(effects, y_positions, strict=False):
            # Effect point - size proportional to weight
            marker_size = 6
            if effect.weight is not None:
                marker_size = max(4, min(12, effect.weight / 5))

            ax.plot(effect.effect, y, "ks", markersize=marker_size)

            # Confidence interval line
            ax.hlines(y, effect.ci_lower, effect.ci_upper, colors="black", linewidth=1.5)

            # Truncation markers if CI extends beyond plot
            if effect.ci_lower < x_min:
                ax.plot(x_min, y, "<", color="black", markersize=5)
            if effect.ci_upper > x_max:
                ax.plot(x_max, y, ">", color="black", markersize=5)

        # Plot pooled effect as diamond
        y_pooled = 0
        diamond_height = 0.4

        # Create diamond vertices
        diamond_x = [
            pooled.ci_lower,
            pooled.effect,
            pooled.ci_upper,
            pooled.effect,
            pooled.ci_lower,
        ]
        diamond_y = [
            y_pooled,
            y_pooled + diamond_height / 2,
            y_pooled,
            y_pooled - diamond_height / 2,
            y_pooled,
        ]

        ax.fill(diamond_x, diamond_y, color="steelblue", edgecolor="black", linewidth=1)

        # Line of no effect
        null_value = self._get_null_value()
        ax.axvline(x=null_value, color="gray", linestyle="--", linewidth=1, alpha=0.7)

        # Set axis limits and labels
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(-1, n_studies + 1)

        # X-axis label
        effect_label = self.effect_measure.value
        if self.effect_measure in (EffectMeasure.OR, EffectMeasure.RR):
            ax.set_xlabel(f"{effect_label} (log scale)")
        else:
            ax.set_xlabel(effect_label)

        # Remove y-axis
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)

        # Add study labels on the left
        for effect, y in zip(effects, y_positions, strict=False):
            # Truncate long names
            name = effect.study_name[:30] + "..." if len(effect.study_name) > 30 else effect.study_name
            ax.text(
                -0.02,
                y,
                name,
                ha="right",
                va="center",
                transform=ax.get_yaxis_transform(),
                fontsize=9,
            )

        # Add "Overall" label for pooled effect
        ax.text(
            -0.02,
            y_pooled,
            "Overall",
            ha="right",
            va="center",
            transform=ax.get_yaxis_transform(),
            fontsize=9,
            fontweight="bold",
        )

        # Add effect size and CI text on the right
        for effect, y in zip(effects, y_positions, strict=False):
            effect_text = (
                f"{self._format_effect(effect.effect)} "
                f"[{self._format_effect(effect.ci_lower)}, {self._format_effect(effect.ci_upper)}]"
            )
            if self.show_weights and effect.weight is not None:
                effect_text += f" ({effect.weight:.1f}%)"
            ax.text(
                1.02,
                y,
                effect_text,
                ha="left",
                va="center",
                transform=ax.get_yaxis_transform(),
                fontsize=8,
            )

        # Pooled effect text
        pooled_text = (
            f"{self._format_effect(pooled.effect)} "
            f"[{self._format_effect(pooled.ci_lower)}, {self._format_effect(pooled.ci_upper)}]"
        )
        ax.text(
            1.02,
            y_pooled,
            pooled_text,
            ha="left",
            va="center",
            transform=ax.get_yaxis_transform(),
            fontsize=8,
            fontweight="bold",
        )

        # Title
        ax.set_title(title, fontsize=12, fontweight="bold", pad=20)

        # Heterogeneity statistics at bottom
        if self.show_heterogeneity:
            het_text = f"Heterogeneity: I² = {pooled.i_squared:.1f}%, Q = {pooled.q_statistic:.2f} (df = {pooled.df})"
            if pooled.tau_squared is not None:
                het_text += f", τ² = {pooled.tau_squared:.3f}"

            # Test for overall effect
            sig = "p < 0.001" if pooled.p_value < 0.001 else f"p = {pooled.p_value:.3f}"
            het_text += f"\nTest for overall effect: Z = {pooled.z_score:.2f}, {sig}"

            ax.text(
                0.5,
                -0.08,
                het_text,
                ha="center",
                va="top",
                transform=ax.transAxes,
                fontsize=8,
                style="italic",
            )

        plt.tight_layout()
        return fig

    def save(self, fig: Figure, path: Path, dpi: int = 300) -> None:
        """
        Save the forest plot to a file.

        Args:
            fig: Matplotlib Figure to save
            path: Output file path (supports .png, .pdf, .svg)
            dpi: Resolution for raster formats
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=dpi, bbox_inches="tight")
        logger.info("Saved forest plot to %s", path)
        plt.close(fig)

    def create_and_save(
        self,
        effects: list[EffectSize],
        pooled: PooledEffect,
        output_path: Path,
        title: str = "Forest Plot",
        dpi: int = 300,
    ) -> None:
        """
        Create and save a forest plot in one step.

        Args:
            effects: List of individual study effect sizes
            pooled: Pooled effect from meta-analysis
            output_path: Output file path
            title: Plot title
            dpi: Resolution for raster formats
        """
        fig = self.create(effects, pooled, title)
        self.save(fig, output_path, dpi)


def create_comparison_forest_plot(
    effects_list: list[list[EffectSize]],
    pooled_list: list[PooledEffect],
    labels: list[str],
    title: str = "Comparison Forest Plot",
    effect_measure: EffectMeasure = EffectMeasure.MD,
) -> Figure:
    """
    Create a forest plot comparing multiple analyses.

    Useful for comparing original vs updated meta-analyses.

    Args:
        effects_list: List of effect size lists (one per analysis)
        pooled_list: List of pooled effects (one per analysis)
        labels: Labels for each analysis
        title: Plot title
        effect_measure: Type of effect measure

    Returns:
        Matplotlib Figure object
    """
    n_analyses = len(pooled_list)
    fig_height = max(4, n_analyses * 1.5 + 2)

    fig, ax = plt.subplots(figsize=(10, fig_height))

    # Y positions
    y_positions = list(range(n_analyses, 0, -1))

    # Determine x-axis range
    all_ci = [(p.ci_lower, p.ci_upper) for p in pooled_list]
    x_min = min(ci[0] for ci in all_ci) * 1.1 if min(ci[0] for ci in all_ci) < 0 else min(ci[0] for ci in all_ci) * 0.9
    x_max = max(ci[1] for ci in all_ci) * 1.1

    # For ratio measures
    if effect_measure in (EffectMeasure.OR, EffectMeasure.RR):
        ax.set_xscale("log")
        x_min = max(0.01, min(ci[0] for ci in all_ci) * 0.8)
        x_max = max(ci[1] for ci in all_ci) * 1.2

    colors = ["steelblue", "darkgreen", "darkorange", "purple"]

    for pooled, y, label, color in zip(pooled_list, y_positions, labels, colors, strict=False):
        # Diamond for pooled effect
        diamond_height = 0.3
        diamond_x = [pooled.ci_lower, pooled.effect, pooled.ci_upper, pooled.effect, pooled.ci_lower]
        diamond_y = [y, y + diamond_height / 2, y, y - diamond_height / 2, y]

        ax.fill(diamond_x, diamond_y, color=color, edgecolor="black", linewidth=1, alpha=0.8)

        # Label
        ax.text(-0.02, y, label, ha="right", va="center", transform=ax.get_yaxis_transform(), fontsize=10)

        # Effect text
        formatter = ForestPlot(effect_measure=effect_measure)
        effect_text = (
            f"{formatter._format_effect(pooled.effect)} "
            f"[{formatter._format_effect(pooled.ci_lower)}, {formatter._format_effect(pooled.ci_upper)}]"
        )
        ax.text(1.02, y, effect_text, ha="left", va="center", transform=ax.get_yaxis_transform(), fontsize=9)

    # Line of no effect
    null_value = 1.0 if effect_measure in (EffectMeasure.OR, EffectMeasure.RR) else 0.0
    ax.axvline(x=null_value, color="gray", linestyle="--", linewidth=1)

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(0, n_analyses + 1)
    ax.set_xlabel(effect_measure.value)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.set_title(title, fontsize=12, fontweight="bold")

    plt.tight_layout()
    return fig
