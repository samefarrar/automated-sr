"""PDF retrieval from open access sources via OpenAlex."""

import logging
from pathlib import Path
from typing import Any

import httpx

from automated_sr.models import Citation
from automated_sr.openalex.client import OpenAlexClient

logger = logging.getLogger(__name__)

# Common PDF content type indicators
PDF_CONTENT_TYPES = ["application/pdf", "application/x-pdf"]
PDF_MAGIC_BYTES = b"%PDF"


class PDFRetrievalError(Exception):
    """Error retrieving or downloading a PDF."""

    pass


class PDFRetriever:
    """Retrieves PDFs from open access sources using OpenAlex metadata."""

    def __init__(self, download_dir: Path, timeout: float = 30.0) -> None:
        """
        Initialize the PDF retriever.

        Args:
            download_dir: Directory to save downloaded PDFs
            timeout: HTTP request timeout in seconds
        """
        self.download_dir = download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(follow_redirects=True, timeout=timeout)
        self._openalex = OpenAlexClient()

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "PDFRetriever":
        """Context manager entry."""
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit."""
        self.close()

    def get_pdf_url(self, work: dict[str, Any]) -> str | None:
        """
        Extract the best PDF URL from an OpenAlex work.

        Checks locations in order of preference:
        1. Primary location pdf_url
        2. Best OA location pdf_url
        3. Any location with pdf_url

        Args:
            work: OpenAlex work dictionary

        Returns:
            PDF URL if found, None otherwise
        """
        # Check primary location
        primary = work.get("primary_location", {})
        if primary and primary.get("pdf_url"):
            return primary["pdf_url"]

        # Check best OA location
        best_oa = work.get("best_oa_location", {})
        if best_oa and best_oa.get("pdf_url"):
            return best_oa["pdf_url"]

        # Check all locations
        for location in work.get("locations", []):
            if location.get("pdf_url"):
                return location["pdf_url"]

        return None

    def download_pdf(self, url: str, filename: str) -> Path | None:
        """
        Download a PDF from a URL.

        Args:
            url: URL to download from
            filename: Filename to save as (without .pdf extension)

        Returns:
            Path to downloaded file, or None if download failed
        """
        try:
            logger.debug("Downloading PDF from %s", url)
            response = self._client.get(url)
            response.raise_for_status()

            content = response.content

            # Verify it's actually a PDF
            if not content.startswith(PDF_MAGIC_BYTES):
                # Check content-type header
                content_type = response.headers.get("content-type", "").lower()
                if not any(pdf_type in content_type for pdf_type in PDF_CONTENT_TYPES):
                    logger.warning("URL did not return a PDF: %s (content-type: %s)", url, content_type)
                    return None

            # Sanitize filename
            safe_filename = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)
            path = self.download_dir / f"{safe_filename}.pdf"

            path.write_bytes(content)
            logger.info("Downloaded PDF to %s (%d bytes)", path, len(content))
            return path

        except httpx.HTTPError:
            logger.exception("Failed to download PDF from %s", url)
            return None

    def retrieve_for_work(self, work: dict[str, Any]) -> Path | None:
        """
        Attempt to retrieve a PDF for an OpenAlex work.

        Args:
            work: OpenAlex work dictionary

        Returns:
            Path to downloaded PDF, or None if not available
        """
        pdf_url = self.get_pdf_url(work)
        if not pdf_url:
            logger.debug("No PDF URL found for work: %s", work.get("id"))
            return None

        # Use DOI or OpenAlex ID as filename
        doi = work.get("doi", "")
        if doi:
            filename = doi.replace("https://doi.org/", "").replace("/", "_")
        else:
            filename = work.get("id", "unknown").split("/")[-1]

        return self.download_pdf(pdf_url, filename)

    def retrieve_for_citation(self, citation: Citation) -> Path | None:
        """
        Attempt to retrieve a PDF for a citation.

        Looks up the citation in OpenAlex by DOI and attempts to download the PDF.

        Args:
            citation: Citation object (must have DOI)

        Returns:
            Path to downloaded PDF, or None if not available
        """
        if not citation.doi:
            logger.debug("Citation has no DOI, cannot retrieve PDF: %s", citation.title)
            return None

        # Look up in OpenAlex
        work = self._openalex.get_by_doi(citation.doi)
        if not work:
            logger.debug("Citation not found in OpenAlex: %s", citation.doi)
            return None

        return self.retrieve_for_work(work)

    def retrieve_batch(
        self,
        citations: list[Citation],
        skip_existing: bool = True,
    ) -> dict[int, Path | None]:
        """
        Attempt to retrieve PDFs for multiple citations.

        Args:
            citations: List of citations to retrieve PDFs for
            skip_existing: Skip citations that already have a pdf_path

        Returns:
            Dictionary mapping citation ID to downloaded path (or None if failed)
        """
        results: dict[int, Path | None] = {}

        for citation in citations:
            if citation.id is None:
                continue

            # Skip if already has PDF
            if skip_existing and citation.pdf_path and citation.pdf_path.exists():
                logger.debug("Skipping citation with existing PDF: %s", citation.id)
                results[citation.id] = citation.pdf_path
                continue

            # Try to retrieve
            path = self.retrieve_for_citation(citation)
            results[citation.id] = path

            if path:
                logger.info("Retrieved PDF for citation %d: %s", citation.id, citation.title[:50])
            else:
                logger.debug("Could not retrieve PDF for citation %d: %s", citation.id, citation.title[:50])

        # Summary
        success = sum(1 for p in results.values() if p is not None)
        logger.info("Retrieved %d of %d PDFs", success, len(results))

        return results


def get_open_access_status(work: dict[str, Any]) -> dict[str, Any]:
    """
    Get open access information for a work.

    Args:
        work: OpenAlex work dictionary

    Returns:
        Dictionary with OA status information
    """
    return {
        "is_oa": work.get("is_oa", False),
        "oa_status": work.get("oa_status"),
        "has_fulltext": work.get("has_fulltext", False),
        "pdf_url": PDFRetriever(Path(".")).get_pdf_url(work),
    }
