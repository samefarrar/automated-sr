"""OpenAlex API client for searching and retrieving scholarly works."""

import logging
import os
from typing import Any

import pyalex
from pyalex import Works

from automated_sr.models import Citation

logger = logging.getLogger(__name__)


class OpenAlexClient:
    """Client for searching and retrieving articles via OpenAlex API."""

    def __init__(self, email: str | None = None) -> None:
        """
        Initialize the OpenAlex client.

        Args:
            email: Email for the polite pool (recommended for better rate limits).
                   If not provided, uses OPENALEX_EMAIL env var.
        """
        self.email = email or os.environ.get("OPENALEX_EMAIL")
        if self.email:
            pyalex.config.email = self.email
            logger.debug("OpenAlex configured with email for polite pool")
        else:
            logger.warning("No email configured for OpenAlex - using common pool with lower rate limits")

    def search(
        self,
        query: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Search for works matching query and/or filters.

        Args:
            query: Full-text search query (searches title, abstract)
            filters: Filter dictionary (e.g., {"publication_year": 2023, "is_oa": True})
            limit: Maximum number of results to return

        Returns:
            List of work dictionaries from OpenAlex
        """
        works = Works()

        if query:
            works = works.search(query)

        if filters:
            works = works.filter(**filters)

        results: list[dict[str, Any]] = []
        per_page = min(limit, 200)  # OpenAlex max is 200 per page

        for page in works.paginate(per_page=per_page):
            results.extend(page)
            if len(results) >= limit:
                break

        logger.info("OpenAlex search returned %d results", len(results[:limit]))
        return results[:limit]

    def search_by_keywords(
        self,
        keywords: list[str],
        year_from: int | None = None,
        year_to: int | None = None,
        open_access_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Search for works by keywords with common filters.

        Args:
            keywords: List of keywords to search for
            year_from: Minimum publication year
            year_to: Maximum publication year
            open_access_only: Only return open access works
            limit: Maximum number of results

        Returns:
            List of work dictionaries
        """
        query = " ".join(keywords)

        filters: dict[str, Any] = {}
        if year_from:
            filters["from_publication_date"] = f"{year_from}-01-01"
        if year_to:
            filters["to_publication_date"] = f"{year_to}-12-31"
        if open_access_only:
            filters["is_oa"] = True

        return self.search(query=query, filters=filters if filters else None, limit=limit)

    def get_by_doi(self, doi: str) -> dict[str, Any] | None:
        """
        Look up a work by DOI.

        Args:
            doi: The DOI (with or without https://doi.org/ prefix)

        Returns:
            Work dictionary if found, None otherwise
        """
        # Normalize DOI format
        if not doi.startswith("https://doi.org/"):
            doi = f"https://doi.org/{doi}"

        try:
            work = Works()[doi]
            logger.debug("Found work for DOI: %s", doi)
            return work  # type: ignore[return-value]
        except Exception:
            logger.debug("No work found for DOI: %s", doi)
            return None

    def get_by_dois(self, dois: list[str], batch_size: int = 50) -> list[dict[str, Any]]:
        """
        Look up multiple works by DOI in batches.

        Args:
            dois: List of DOIs to look up
            batch_size: Number of DOIs per batch (max 50)

        Returns:
            List of found work dictionaries
        """
        results: list[dict[str, Any]] = []

        # Process in batches
        for i in range(0, len(dois), batch_size):
            batch = dois[i : i + batch_size]

            # Normalize DOIs
            normalized = [f"https://doi.org/{d}" if not d.startswith("https://doi.org/") else d for d in batch]

            # Use OR filter for batch lookup
            doi_filter = "|".join(normalized)
            try:
                works = Works().filter(doi=doi_filter).get()
                # Handle pyalex return type (could be list or tuple)
                if isinstance(works, tuple):
                    results.extend(list(works[0]))
                else:
                    results.extend(list(works))
            except Exception:
                logger.exception("Error fetching batch of DOIs")

        logger.info("Found %d of %d DOIs", len(results), len(dois))
        return results

    def _reconstruct_abstract(self, abstract_inverted_index: dict[str, list[int]] | None) -> str | None:
        """
        Reconstruct abstract text from OpenAlex inverted index format.

        OpenAlex stores abstracts as {word: [positions]} to save space.
        This reconstructs the original text.

        Args:
            abstract_inverted_index: The inverted index dictionary

        Returns:
            Reconstructed abstract text, or None if not available
        """
        if not abstract_inverted_index:
            return None

        # Build list of (position, word) tuples
        word_positions: list[tuple[int, str]] = []
        for word, positions in abstract_inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))

        # Sort by position and join
        word_positions.sort(key=lambda x: x[0])
        return " ".join(word for _, word in word_positions)

    def to_citation(self, work: dict[str, Any]) -> Citation:
        """
        Convert an OpenAlex work to a Citation object.

        Args:
            work: OpenAlex work dictionary

        Returns:
            Citation object
        """
        # Extract authors
        authors: list[str] = []
        for authorship in work.get("authorships", []):
            author = authorship.get("author", {})
            name = author.get("display_name")
            if name:
                authors.append(name)

        # Extract DOI (remove prefix)
        doi = work.get("doi")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi[16:]  # Remove "https://doi.org/"

        # Extract journal name
        journal = None
        primary_location = work.get("primary_location", {})
        if primary_location:
            source = primary_location.get("source", {})
            if source:
                journal = source.get("display_name")

        # Get abstract - try direct field first, then inverted index
        abstract = work.get("abstract")
        if not abstract:
            abstract = self._reconstruct_abstract(work.get("abstract_inverted_index"))

        return Citation(
            source="openalex",
            source_key=work.get("id"),
            title=work.get("title", ""),
            authors=authors,
            abstract=abstract,
            year=work.get("publication_year"),
            doi=doi,
            journal=journal,
        )

    def to_citations(self, works: list[dict[str, Any]]) -> list[Citation]:
        """
        Convert multiple OpenAlex works to Citation objects.

        Args:
            works: List of OpenAlex work dictionaries

        Returns:
            List of Citation objects
        """
        return [self.to_citation(work) for work in works]


def deduplicate_by_doi(citations: list[Citation]) -> list[Citation]:
    """
    Remove duplicate citations based on DOI.

    Args:
        citations: List of citations (may contain duplicates)

    Returns:
        Deduplicated list of citations
    """
    seen_dois: set[str] = set()
    unique: list[Citation] = []

    for citation in citations:
        if citation.doi:
            if citation.doi.lower() not in seen_dois:
                seen_dois.add(citation.doi.lower())
                unique.append(citation)
        else:
            # Keep citations without DOIs (can't deduplicate)
            unique.append(citation)

    logger.info("Deduplicated %d -> %d citations by DOI", len(citations), len(unique))
    return unique
