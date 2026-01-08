"""Secondary filtering logic for post-extraction study selection."""

import logging
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from automated_sr.models import Citation, ExtractionResult

logger = logging.getLogger(__name__)


class FilterReason(str, Enum):
    """Reasons for secondary filtering exclusion."""

    MISSING_PRIMARY_OUTCOME = "missing_primary_outcome"
    DUPLICATE_STUDY = "duplicate_study"
    INELIGIBLE_INTERVENTION = "ineligible_intervention"
    INELIGIBLE_COMPARATOR = "ineligible_comparator"
    DATA_EXTRACTION_ERROR = "data_extraction_error"


class FilterResult(BaseModel):
    """Result of applying a filter to a citation."""

    citation_id: int
    passed: bool
    reason: FilterReason | None = None
    details: str | None = None
    applied_at: datetime = Field(default_factory=datetime.now)


class SecondaryFilter:
    """Applies post-extraction filters to identify ineligible studies.

    After data extraction, some studies may be found to be ineligible based on:
    - Missing required outcome data
    - Being duplicates of other included studies
    - Having ineligible intervention or comparator groups

    This class implements filters similar to those used in the otto-SR paper.
    """

    def __init__(
        self,
        required_outcome_fields: list[str] | None = None,
        eligible_interventions: list[str] | None = None,
        eligible_comparators: list[str] | None = None,
        intervention_field: str = "intervention",
        comparator_field: str = "comparator",
        duplicate_fields: list[str] | None = None,
    ) -> None:
        """
        Initialize the secondary filter.

        Args:
            required_outcome_fields: Fields that must have valid values (not null/empty/na)
            eligible_interventions: List of acceptable intervention names (case-insensitive)
            eligible_comparators: List of acceptable comparator names (case-insensitive)
            intervention_field: Name of the intervention field in extracted data
            comparator_field: Name of the comparator field in extracted data
            duplicate_fields: Fields to use for duplicate detection (default: title, doi)
        """
        self.required_outcome_fields = required_outcome_fields or []
        self.eligible_interventions = [i.lower() for i in (eligible_interventions or [])]
        self.eligible_comparators = [c.lower() for c in (eligible_comparators or [])]
        self.intervention_field = intervention_field
        self.comparator_field = comparator_field
        self.duplicate_fields = duplicate_fields or ["title", "doi"]

    def _is_missing_value(self, value: Any) -> bool:
        """Check if a value represents missing data."""
        if value is None:
            return True
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized in ("", "na", "n/a", "not available", "not reported", "nr", "none")
        return False

    def check_missing_outcomes(
        self,
        citation: Citation,
        extraction: ExtractionResult,
    ) -> FilterResult:
        """
        Check if required outcome fields are present.

        Args:
            citation: The citation being checked
            extraction: The extraction result for the citation

        Returns:
            FilterResult indicating pass/fail
        """
        if not self.required_outcome_fields:
            return FilterResult(citation_id=citation.id or 0, passed=True)

        for field in self.required_outcome_fields:
            value = extraction.extracted_data.get(field)
            if self._is_missing_value(value):
                return FilterResult(
                    citation_id=citation.id or 0,
                    passed=False,
                    reason=FilterReason.MISSING_PRIMARY_OUTCOME,
                    details=f"Missing required field: {field}",
                )

        return FilterResult(citation_id=citation.id or 0, passed=True)

    def _normalize_for_comparison(self, value: str | None) -> str:
        """Normalize a string for comparison (lowercase, strip whitespace)."""
        if value is None:
            return ""
        return value.strip().lower()

    def _is_duplicate(self, citation1: Citation, citation2: Citation) -> bool:
        """Check if two citations are duplicates based on duplicate_fields."""
        for field in self.duplicate_fields:
            val1 = getattr(citation1, field, None)
            val2 = getattr(citation2, field, None)

            if val1 is None or val2 is None:
                continue

            # For DOIs, normalize and compare
            if field == "doi":
                if self._normalize_for_comparison(val1) == self._normalize_for_comparison(val2):
                    return True
            # For titles, use fuzzy matching (simple normalized comparison)
            elif field == "title":
                norm1 = self._normalize_for_comparison(val1)
                norm2 = self._normalize_for_comparison(val2)
                if norm1 and norm2 and norm1 == norm2:
                    return True

        return False

    def check_duplicates(
        self,
        citation: Citation,
        all_citations: list[Citation],
    ) -> FilterResult:
        """
        Check if citation is a duplicate of an earlier one.

        A citation is considered a duplicate if it matches an earlier citation
        (by ID) on any of the duplicate_fields.

        Args:
            citation: The citation being checked
            all_citations: All citations in the review (for comparison)

        Returns:
            FilterResult indicating pass/fail
        """
        citation_id = citation.id or 0

        for other in all_citations:
            other_id = other.id or 0
            # Only check against earlier citations (lower ID)
            if other_id >= citation_id:
                continue

            if self._is_duplicate(citation, other):
                return FilterResult(
                    citation_id=citation_id,
                    passed=False,
                    reason=FilterReason.DUPLICATE_STUDY,
                    details=f"Duplicate of citation {other_id}: {other.title[:50]}...",
                )

        return FilterResult(citation_id=citation_id, passed=True)

    def check_intervention(
        self,
        citation: Citation,
        extraction: ExtractionResult,
    ) -> FilterResult:
        """
        Check if the intervention is eligible.

        Args:
            citation: The citation being checked
            extraction: The extraction result for the citation

        Returns:
            FilterResult indicating pass/fail
        """
        if not self.eligible_interventions:
            return FilterResult(citation_id=citation.id or 0, passed=True)

        intervention = extraction.extracted_data.get(self.intervention_field)
        if intervention is None:
            return FilterResult(citation_id=citation.id or 0, passed=True)

        intervention_lower = self._normalize_for_comparison(str(intervention))

        # Check if intervention matches any eligible intervention
        for eligible in self.eligible_interventions:
            if eligible in intervention_lower or intervention_lower in eligible:
                return FilterResult(citation_id=citation.id or 0, passed=True)

        return FilterResult(
            citation_id=citation.id or 0,
            passed=False,
            reason=FilterReason.INELIGIBLE_INTERVENTION,
            details=f"Intervention '{intervention}' not in eligible list",
        )

    def check_comparator(
        self,
        citation: Citation,
        extraction: ExtractionResult,
    ) -> FilterResult:
        """
        Check if the comparator is eligible.

        Args:
            citation: The citation being checked
            extraction: The extraction result for the citation

        Returns:
            FilterResult indicating pass/fail
        """
        if not self.eligible_comparators:
            return FilterResult(citation_id=citation.id or 0, passed=True)

        comparator = extraction.extracted_data.get(self.comparator_field)
        if comparator is None:
            return FilterResult(citation_id=citation.id or 0, passed=True)

        comparator_lower = self._normalize_for_comparison(str(comparator))

        # Check if comparator matches any eligible comparator
        for eligible in self.eligible_comparators:
            if eligible in comparator_lower or comparator_lower in eligible:
                return FilterResult(citation_id=citation.id or 0, passed=True)

        return FilterResult(
            citation_id=citation.id or 0,
            passed=False,
            reason=FilterReason.INELIGIBLE_COMPARATOR,
            details=f"Comparator '{comparator}' not in eligible list",
        )

    def apply_all(
        self,
        citations_with_extractions: list[tuple[Citation, ExtractionResult]],
    ) -> tuple[list[tuple[Citation, ExtractionResult]], list[FilterResult]]:
        """
        Apply all filters and return passed citations with all filter results.

        Args:
            citations_with_extractions: List of (citation, extraction) tuples

        Returns:
            Tuple of:
            - List of (citation, extraction) tuples that passed all filters
            - List of all FilterResult objects (for tracking/reporting)
        """
        passed: list[tuple[Citation, ExtractionResult]] = []
        all_results: list[FilterResult] = []
        all_citations = [c for c, _ in citations_with_extractions]

        for citation, extraction in citations_with_extractions:
            # Run all filters
            results = [
                self.check_missing_outcomes(citation, extraction),
                self.check_duplicates(citation, all_citations),
                self.check_intervention(citation, extraction),
                self.check_comparator(citation, extraction),
            ]

            all_results.extend(results)

            # Check if any filter failed
            failed = [r for r in results if not r.passed]

            if not failed:
                passed.append((citation, extraction))
            else:
                # Log the first failure reason
                logger.debug(
                    "Citation %d filtered out: %s - %s",
                    citation.id or 0,
                    failed[0].reason,
                    failed[0].details,
                )

        logger.info(
            "Secondary filtering: %d of %d citations passed",
            len(passed),
            len(citations_with_extractions),
        )

        return passed, all_results

    def get_filter_summary(self, results: list[FilterResult]) -> dict[str, int]:
        """
        Get a summary of filter results by reason.

        Args:
            results: List of FilterResult objects

        Returns:
            Dictionary mapping reason to count
        """
        summary: dict[str, int] = {"passed": 0}

        for result in results:
            if result.passed:
                summary["passed"] += 1
            elif result.reason:
                reason_key = result.reason.value
                summary[reason_key] = summary.get(reason_key, 0) + 1

        return summary
