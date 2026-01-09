"""Extract DOI from PDF files using LLM."""

import logging
import re
from pathlib import Path

import pymupdf

from automated_sr.llm import LLMClient, create_client

logger = logging.getLogger(__name__)

# Regex pattern for DOI - catches most common formats
DOI_PATTERN = re.compile(r"10\.\d{4,}/[^\s\"'<>\]]+", re.IGNORECASE)

# Model to use for DOI extraction (fast and cheap)
DOI_EXTRACTION_MODEL = "anthropic/claude-3-5-haiku-20241022"

DOI_EXTRACTION_PROMPT = """Extract the DOI (Digital Object Identifier) from this academic paper text.

The DOI typically appears near the title, in the header/footer, or in the citation information.
It starts with "10." followed by a number and then a slash, like: 10.1000/xyz123

Text from first pages of PDF:
---
{text}
---

If you find a DOI, respond with ONLY the DOI (e.g., "10.1016/j.example.2024.123456").
If you cannot find a DOI, respond with exactly "NOT_FOUND".

DOI:"""


def extract_text_first_pages(pdf_path: Path, max_pages: int = 2) -> str:
    """
    Extract text from the first few pages of a PDF.

    Args:
        pdf_path: Path to the PDF file
        max_pages: Maximum number of pages to extract

    Returns:
        Extracted text from the first pages
    """
    try:
        doc = pymupdf.open(pdf_path)
        text_parts = []

        page_count = min(len(doc), max_pages)
        for page_num in range(page_count):
            page = doc[page_num]
            text = str(page.get_text())
            if text.strip():
                text_parts.append(text)

        doc.close()
        return "\n\n".join(text_parts)
    except Exception:
        logger.exception("Failed to extract text from PDF: %s", pdf_path)
        return ""


def extract_doi_regex(text: str) -> str | None:
    """
    Try to extract DOI using regex pattern matching.

    Args:
        text: Text to search for DOI

    Returns:
        DOI if found, None otherwise
    """
    match = DOI_PATTERN.search(text)
    if match:
        doi = match.group(0)
        # Clean up trailing punctuation that might have been captured
        doi = doi.rstrip(".,;:")
        return doi
    return None


def extract_doi_llm(text: str, client: LLMClient | None = None) -> str | None:
    """
    Extract DOI from text using LLM.

    Args:
        text: Text from PDF first pages
        client: Optional LLM client (creates one if not provided)

    Returns:
        DOI if found, None otherwise
    """
    if not text.strip():
        return None

    if client is None:
        client = create_client()

    # Truncate text if too long (keep first ~4000 chars)
    if len(text) > 4000:
        text = text[:4000] + "\n[...truncated...]"

    prompt = DOI_EXTRACTION_PROMPT.format(text=text)

    try:
        response = client.complete(
            prompt=prompt,
            model=DOI_EXTRACTION_MODEL,
            max_tokens=100,
            temperature=0.0,
        )

        response = response.strip()

        if response == "NOT_FOUND" or not response:
            return None

        # Validate it looks like a DOI
        if response.startswith("10."):
            # Clean up any extra text the model might have added
            doi_match = DOI_PATTERN.match(response)
            if doi_match:
                return doi_match.group(0).rstrip(".,;:")
            return response.split()[0].rstrip(".,;:")  # Take first word if regex fails

        return None

    except Exception:
        logger.exception("LLM DOI extraction failed")
        return None


def extract_doi_from_pdf(pdf_path: Path, use_llm: bool = True) -> str | None:
    """
    Extract DOI from a PDF file.

    First tries regex extraction, then falls back to LLM if enabled.

    Args:
        pdf_path: Path to the PDF file
        use_llm: Whether to use LLM as fallback (default True)

    Returns:
        DOI if found, None otherwise
    """
    text = extract_text_first_pages(pdf_path)

    if not text:
        logger.debug("No text extracted from PDF: %s", pdf_path)
        return None

    # Try regex first (fast and free)
    doi = extract_doi_regex(text)
    if doi:
        logger.debug("DOI found via regex: %s", doi)
        return doi

    # Fall back to LLM
    if use_llm:
        doi = extract_doi_llm(text)
        if doi:
            logger.debug("DOI found via LLM: %s", doi)
            return doi

    logger.debug("No DOI found in PDF: %s", pdf_path)
    return None


def normalize_doi(doi: str) -> str:
    """
    Normalize a DOI for comparison.

    Args:
        doi: DOI string

    Returns:
        Normalized DOI (lowercase, no URL prefix)
    """
    doi = doi.lower().strip()
    # Remove common prefixes
    prefixes = ["https://doi.org/", "http://doi.org/", "doi:", "doi.org/"]
    for prefix in prefixes:
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
    return doi
