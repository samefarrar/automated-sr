"""Pytest fixtures for automated_sr tests."""

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from automated_sr.models import (
    APIProvider,
    Citation,
    ExtractionVariable,
    ReviewerConfig,
    ReviewProtocol,
    ScreeningDecision,
    ScreeningResult,
)


@pytest.fixture
def sample_citation() -> Citation:
    """Create a sample citation for testing."""
    return Citation(
        id=1,
        review_id=1,
        source="test",
        source_key="test-key-1",
        title="Deep Learning for Medical Image Analysis",
        authors=["John Smith", "Jane Doe"],
        abstract="This study evaluates deep learning methods for cancer diagnosis from CT scans.",
        year=2023,
        doi="10.1234/test.2023.001",
        journal="Journal of Medical AI",
    )


@pytest.fixture
def sample_citation_no_abstract() -> Citation:
    """Create a sample citation without an abstract."""
    return Citation(
        id=2,
        review_id=1,
        source="test",
        title="Another Study on Machine Learning",
        authors=["Alice Brown"],
        year=2024,
        doi="10.1234/test.2024.002",
    )


@pytest.fixture
def sample_protocol() -> ReviewProtocol:
    """Create a sample review protocol for testing."""
    return ReviewProtocol(
        name="test-review",
        objective="Evaluate machine learning for cancer diagnosis",
        inclusion_criteria=[
            "Studies evaluating ML for cancer diagnosis",
            "Studies using medical imaging data",
            "Peer-reviewed articles",
        ],
        exclusion_criteria=[
            "Review articles or meta-analyses",
            "Conference abstracts only",
            "Non-English articles",
        ],
        extraction_variables=[
            ExtractionVariable(name="sample_size", description="Total sample size", type="integer"),
            ExtractionVariable(name="accuracy", description="Model accuracy", type="float"),
        ],
        model="anthropic/claude-3-5-haiku-20241022",
    )


@pytest.fixture
def multi_reviewer_protocol() -> ReviewProtocol:
    """Create a protocol with multi-reviewer configuration."""
    return ReviewProtocol(
        name="multi-reviewer-test",
        objective="Test multi-reviewer screening",
        inclusion_criteria=["Include criterion 1"],
        exclusion_criteria=["Exclude criterion 1"],
        reviewers=[
            ReviewerConfig(
                name="screener-1",
                model="anthropic/claude-3-5-haiku-20241022",
                api=APIProvider.ANTHROPIC,
                prompt_template="rigorous",
                role="primary",
            ),
            ReviewerConfig(
                name="screener-2",
                model="anthropic/claude-3-5-haiku-20241022",
                api=APIProvider.ANTHROPIC,
                prompt_template="sensitive",
                role="primary",
            ),
            ReviewerConfig(
                name="tiebreaker",
                model="anthropic/claude-sonnet-4-5-20250929",
                api=APIProvider.ANTHROPIC,
                prompt_template="rigorous",
                role="tiebreaker",
            ),
        ],
    )


@pytest.fixture
def sample_screening_result() -> ScreeningResult:
    """Create a sample screening result."""
    return ScreeningResult(
        citation_id=1,
        decision=ScreeningDecision.INCLUDE,
        reasoning="This study meets all inclusion criteria.",
        model="test-model",
        reviewer_name="test-reviewer",
    )


@pytest.fixture
def temp_dir() -> Generator[Path]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
