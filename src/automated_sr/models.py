"""Data models for the systematic review automation tool."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ScreeningDecision(str, Enum):
    """Possible screening decisions."""

    INCLUDE = "include"
    EXCLUDE = "exclude"
    UNCERTAIN = "uncertain"


class APIProvider(str, Enum):
    """Supported LLM API providers."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OPENROUTER = "openrouter"


class Citation(BaseModel):
    """A citation/reference from a systematic review search."""

    id: int | None = None
    review_id: int | None = None
    source: str = "unknown"  # 'ris' or 'zotero'
    source_key: str | None = None  # Zotero item key or RIS index
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    year: int | None = None
    doi: str | None = None
    journal: str | None = None
    pdf_path: Path | None = None
    created_at: datetime | None = None

    def has_abstract(self) -> bool:
        """Check if the citation has an abstract."""
        return bool(self.abstract and self.abstract.strip())

    def has_pdf(self) -> bool:
        """Check if a PDF is available for this citation."""
        return self.pdf_path is not None and self.pdf_path.exists()


class ScreeningResult(BaseModel):
    """Result of screening a citation."""

    citation_id: int
    decision: ScreeningDecision
    reasoning: str
    model: str
    reviewer_name: str | None = None  # Name of the reviewer (for multi-reviewer)
    screened_at: datetime = Field(default_factory=datetime.now)
    pdf_error: str | None = None  # For full-text screening errors


class ExtractionVariable(BaseModel):
    """A variable to extract from articles."""

    name: str
    description: str
    type: str = "string"  # string, integer, float, boolean, list


class ExtractionResult(BaseModel):
    """Result of extracting data from an article."""

    citation_id: int
    extracted_data: dict[str, Any]
    model: str
    extracted_at: datetime = Field(default_factory=datetime.now)


class ReviewerConfig(BaseModel):
    """Configuration for a single reviewer in multi-reviewer mode."""

    name: str
    model: str  # e.g., "claude-sonnet-4-20250514", "gpt-4.1"
    api: APIProvider
    prompt_template: str = "rigorous"  # "rigorous", "sensitive", "specific", or custom
    custom_prompt: str | None = None  # Custom prompt if template is "custom"
    role: str = "primary"  # "primary" or "tiebreaker"


class MultiReviewerScreeningResult(BaseModel):
    """Result from multiple reviewers screening a citation."""

    citation_id: int
    reviewer_results: list[ScreeningResult]
    consensus_decision: ScreeningDecision
    required_tiebreaker: bool = False
    tiebreaker_result: ScreeningResult | None = None
    screened_at: datetime = Field(default_factory=datetime.now)


class ReviewProtocol(BaseModel):
    """A systematic review protocol defining objectives and criteria."""

    name: str
    objective: str
    inclusion_criteria: list[str]
    exclusion_criteria: list[str]
    extraction_variables: list[ExtractionVariable] = Field(default_factory=list)
    model: str = "claude-sonnet-4-5-20250929"
    reviewers: list[ReviewerConfig] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path) -> "ReviewProtocol":
        """Load a protocol from a YAML file."""
        import yaml

        with open(path) as f:
            data = yaml.safe_load(f)

        # Handle settings.model override
        if "settings" in data and "model" in data["settings"]:
            data["model"] = data["settings"]["model"]
            del data["settings"]

        # Convert extraction_variables dicts to ExtractionVariable objects
        if "extraction_variables" in data:
            data["extraction_variables"] = [
                ExtractionVariable(**var) if isinstance(var, dict) else var for var in data["extraction_variables"]
            ]

        # Convert reviewers dicts to ReviewerConfig objects
        if "reviewers" in data:
            data["reviewers"] = [ReviewerConfig(**rev) if isinstance(rev, dict) else rev for rev in data["reviewers"]]

        return cls(**data)

    def to_yaml(self, path: Path) -> None:
        """Save the protocol to a YAML file."""
        import yaml

        data = {
            "name": self.name,
            "objective": self.objective,
            "inclusion_criteria": self.inclusion_criteria,
            "exclusion_criteria": self.exclusion_criteria,
            "extraction_variables": [var.model_dump() for var in self.extraction_variables],
            "settings": {"model": self.model},
        }

        # Include reviewers if configured
        if self.reviewers:
            data["reviewers"] = [rev.model_dump() for rev in self.reviewers]

        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def get_primary_reviewers(self) -> list[ReviewerConfig]:
        """Get reviewers with role='primary'."""
        return [r for r in self.reviewers if r.role == "primary"]

    def get_tiebreaker(self) -> ReviewerConfig | None:
        """Get the tiebreaker reviewer if configured."""
        tiebreakers = [r for r in self.reviewers if r.role == "tiebreaker"]
        return tiebreakers[0] if tiebreakers else None

    def has_multi_reviewer(self) -> bool:
        """Check if multi-reviewer mode is configured."""
        return len(self.get_primary_reviewers()) > 1


class ReviewStats(BaseModel):
    """Statistics for a systematic review."""

    total_citations: int = 0
    abstract_screened: int = 0
    abstract_included: int = 0
    abstract_excluded: int = 0
    abstract_uncertain: int = 0
    fulltext_screened: int = 0
    fulltext_included: int = 0
    fulltext_excluded: int = 0
    fulltext_uncertain: int = 0
    fulltext_pdf_errors: int = 0
    extracted: int = 0


class SearchStrategy(BaseModel):
    """A generated search strategy for a specific database."""

    name: str
    database: str
    search_string: str
    concepts: list[str]
    rationale: str
    estimated_sensitivity: str = "medium"  # "high", "medium", "low"
    estimated_specificity: str = "medium"  # "high", "medium", "low"


class SearchSuggestionResult(BaseModel):
    """Result of search strategy generation."""

    question: str
    concept_breakdown: dict[str, list[str]] = Field(default_factory=dict)
    strategies: list[SearchStrategy]
    model: str
    generated_at: datetime = Field(default_factory=datetime.now)
