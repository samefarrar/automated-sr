"""Export functionality for systematic review results."""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from automated_sr.database import Database

logger = logging.getLogger(__name__)


class Exporter:
    """Exports systematic review results to various formats."""

    def __init__(self, db: Database) -> None:
        """
        Initialize the exporter.

        Args:
            db: Database instance to export from
        """
        self.db = db

    def export_json(self, review_id: int, output_path: Path) -> None:
        """
        Export all review data to JSON.

        Args:
            review_id: ID of the review to export
            output_path: Path to write the JSON file
        """
        review = self.db.get_review(review_id)
        if not review:
            raise ValueError(f"Review not found: {review_id}")

        citations = self.db.get_citations(review_id)
        stats = self.db.get_stats(review_id)

        data: dict[str, Any] = {
            "review": {
                "id": review["id"],
                "name": review["name"],
                "protocol_path": review.get("protocol_path"),
                "created_at": review.get("created_at"),
                "updated_at": review.get("updated_at"),
            },
            "statistics": stats.model_dump(),
            "citations": [],
        }

        for citation in citations:
            citation_data: dict[str, Any] = {
                "id": citation.id,
                "title": citation.title,
                "authors": citation.authors,
                "year": citation.year,
                "doi": citation.doi,
                "journal": citation.journal,
                "abstract": citation.abstract,
                "source": citation.source,
                "pdf_available": citation.has_pdf(),
            }

            # Add screening results
            abstract_result = self.db.get_abstract_screening(citation.id)  # type: ignore[arg-type]
            if abstract_result:
                citation_data["abstract_screening"] = {
                    "decision": abstract_result.decision.value,
                    "reasoning": abstract_result.reasoning,
                    "model": abstract_result.model,
                    "screened_at": abstract_result.screened_at.isoformat(),
                }

            fulltext_result = self.db.get_fulltext_screening(citation.id)  # type: ignore[arg-type]
            if fulltext_result:
                citation_data["fulltext_screening"] = {
                    "decision": fulltext_result.decision.value,
                    "reasoning": fulltext_result.reasoning,
                    "model": fulltext_result.model,
                    "screened_at": fulltext_result.screened_at.isoformat(),
                    "pdf_error": fulltext_result.pdf_error,
                }

            # Add extraction results
            extraction = self.db.get_extraction(citation.id)  # type: ignore[arg-type]
            if extraction:
                citation_data["extraction"] = {
                    "data": extraction.extracted_data,
                    "model": extraction.model,
                    "extracted_at": extraction.extracted_at.isoformat(),
                }

            data["citations"].append(citation_data)

        # Write JSON
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info("Exported review to JSON: %s", output_path)

    def export_csv(self, review_id: int, output_path: Path) -> None:
        """
        Export extraction results to CSV.

        Args:
            review_id: ID of the review to export
            output_path: Path to write the CSV file
        """
        extractions = self.db.get_all_extractions(review_id)

        if not extractions:
            logger.warning("No extractions to export for review %d", review_id)
            return

        # Collect all unique variable names
        all_variables: set[str] = set()
        for _, extraction in extractions:
            all_variables.update(extraction.extracted_data.keys())

        # Sort variable names for consistent column ordering
        variable_names = sorted(all_variables)

        # Prepare CSV rows
        fieldnames = [
            "citation_id",
            "title",
            "authors",
            "year",
            "doi",
            "journal",
            *variable_names,
        ]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for citation, extraction in extractions:
                row = {
                    "citation_id": citation.id,
                    "title": citation.title,
                    "authors": "; ".join(citation.authors),
                    "year": citation.year,
                    "doi": citation.doi,
                    "journal": citation.journal,
                }

                # Add extracted data, preferring citation metadata for
                # first_author and publication_year over LLM-extracted values
                for var in variable_names:
                    value = extraction.extracted_data.get(var)

                    if var == "first_author" and citation.authors:
                        # Use first author's last name from structured metadata
                        first = citation.authors[0]
                        value = first.split(",")[0].strip() if first else value

                    if var == "publication_year" and citation.year:
                        value = citation.year

                    if isinstance(value, list):
                        row[var] = "; ".join(str(v) for v in value)
                    else:
                        row[var] = value

                writer.writerow(row)

        logger.info("Exported extractions to CSV: %s", output_path)

    def export_screening_csv(self, review_id: int, output_path: Path, stage: str = "abstract") -> None:
        """
        Export screening results to CSV.

        Args:
            review_id: ID of the review to export
            output_path: Path to write the CSV file
            stage: "abstract" or "fulltext"
        """
        citations = self.db.get_citations(review_id)

        fieldnames = [
            "citation_id",
            "title",
            "authors",
            "year",
            "doi",
            "decision",
            "reasoning",
            "model",
            "screened_at",
        ]

        if stage == "fulltext":
            fieldnames.append("pdf_error")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for citation in citations:
                if stage == "abstract":
                    result = self.db.get_abstract_screening(citation.id)  # type: ignore[arg-type]
                else:
                    result = self.db.get_fulltext_screening(citation.id)  # type: ignore[arg-type]

                if result:
                    row: dict[str, Any] = {
                        "citation_id": citation.id,
                        "title": citation.title,
                        "authors": "; ".join(citation.authors),
                        "year": citation.year,
                        "doi": citation.doi,
                        "decision": result.decision.value,
                        "reasoning": result.reasoning,
                        "model": result.model,
                        "screened_at": result.screened_at.isoformat(),
                    }
                    if stage == "fulltext":
                        row["pdf_error"] = result.pdf_error
                    writer.writerow(row)

        logger.info("Exported %s screening to CSV: %s", stage, output_path)

    def export_prisma_data(self, review_id: int) -> dict[str, dict[str, int]]:
        """
        Get data for a PRISMA flow diagram.

        Args:
            review_id: ID of the review

        Returns:
            Dictionary with counts for PRISMA diagram
        """
        stats = self.db.get_stats(review_id)

        return {
            "identification": {
                "records_identified": stats.total_citations,
            },
            "screening": {
                "records_screened": stats.abstract_screened,
                "records_excluded_abstract": stats.abstract_excluded,
            },
            "eligibility": {
                "full_text_assessed": stats.fulltext_screened,
                "full_text_excluded": stats.fulltext_excluded,
                "pdf_not_available": stats.fulltext_pdf_errors,
            },
            "included": {
                "studies_included": stats.fulltext_included,
                "studies_extracted": stats.extracted,
            },
        }

    def generate_summary(self, review_id: int) -> str:
        """
        Generate a text summary of the review.

        Args:
            review_id: ID of the review

        Returns:
            Formatted summary string
        """
        review = self.db.get_review(review_id)
        if not review:
            raise ValueError(f"Review not found: {review_id}")

        stats = self.db.get_stats(review_id)

        lines = [
            f"# Systematic Review Summary: {review['name']}",
            f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "\n## PRISMA Flow",
            "\n### Identification",
            f"- Records identified: {stats.total_citations}",
            "\n### Screening",
            f"- Records screened (abstract): {stats.abstract_screened}",
            f"- Records included after abstract: {stats.abstract_included}",
            f"- Records excluded at abstract: {stats.abstract_excluded}",
            f"- Records uncertain: {stats.abstract_uncertain}",
            "\n### Eligibility",
            f"- Full-text articles assessed: {stats.fulltext_screened}",
            f"- Full-text included: {stats.fulltext_included}",
            f"- Full-text excluded: {stats.fulltext_excluded}",
            f"- PDF errors/unavailable: {stats.fulltext_pdf_errors}",
            "\n### Included",
            f"- Studies included in review: {stats.fulltext_included}",
            f"- Studies with data extracted: {stats.extracted}",
        ]

        # Calculate percentages
        if stats.total_citations > 0:
            include_rate = (stats.fulltext_included / stats.total_citations) * 100
            lines.append("\n## Summary Statistics")
            lines.append(f"- Overall inclusion rate: {include_rate:.1f}%")

        if stats.abstract_screened > 0:
            abstract_include = (stats.abstract_included / stats.abstract_screened) * 100
            lines.append(f"- Abstract screening inclusion rate: {abstract_include:.1f}%")

        if stats.fulltext_screened > 0:
            fulltext_include = (stats.fulltext_included / stats.fulltext_screened) * 100
            lines.append(f"- Full-text screening inclusion rate: {fulltext_include:.1f}%")

        return "\n".join(lines)
