"""RIS file parser for importing citations."""

import logging
from pathlib import Path

import rispy

from automated_sr.models import Citation

logger = logging.getLogger(__name__)

# Mapping of RIS fields to Citation fields
RIS_FIELD_MAP = {
    "title": ["title", "primary_title", "TI", "T1"],
    "authors": ["authors", "first_authors", "AU", "A1"],
    "abstract": ["abstract", "AB", "N2"],
    "year": ["year", "publication_year", "PY", "Y1"],
    "doi": ["doi", "DO"],
    "journal": ["journal_name", "secondary_title", "JO", "JF", "T2"],
}


def _extract_field(entry: dict, field_names: list[str]) -> str | int | list | None:
    """Extract a field from a RIS entry, trying multiple possible field names."""
    for name in field_names:
        if name in entry:
            value = entry[name]
            if value:
                return value
    return None


def _parse_year(year_value: str | int | list | None) -> int | None:
    """Parse a year value from various formats."""
    if year_value is None:
        return None
    if isinstance(year_value, int):
        return year_value
    if isinstance(year_value, list):
        year_value = year_value[0] if year_value else None
        if year_value is None:
            return None
    # Handle formats like "2023", "2023/01/15", "2023///"
    year_str = str(year_value).split("/")[0].strip()
    try:
        return int(year_str)
    except ValueError:
        return None


def _normalize_authors(authors_value: str | int | list | None) -> list[str]:
    """Normalize author names to a list of strings."""
    if authors_value is None:
        return []
    if isinstance(authors_value, int):
        return []  # Authors shouldn't be an integer
    if isinstance(authors_value, str):
        # Single author or semicolon-separated
        return [a.strip() for a in authors_value.split(";") if a.strip()]
    if isinstance(authors_value, list):
        return [str(a).strip() for a in authors_value if a]
    return []


def parse_ris_entry(entry: dict, index: int) -> Citation:
    """Parse a single RIS entry into a Citation object."""
    title = _extract_field(entry, RIS_FIELD_MAP["title"])
    if not title:
        title = f"Unknown Title (RIS entry {index})"

    authors = _normalize_authors(_extract_field(entry, RIS_FIELD_MAP["authors"]))
    abstract = _extract_field(entry, RIS_FIELD_MAP["abstract"])
    year = _parse_year(_extract_field(entry, RIS_FIELD_MAP["year"]))
    doi = _extract_field(entry, RIS_FIELD_MAP["doi"])
    journal = _extract_field(entry, RIS_FIELD_MAP["journal"])

    return Citation(
        source="ris",
        source_key=str(index),
        title=str(title) if title else "Unknown Title",
        authors=authors,
        abstract=str(abstract) if abstract else None,
        year=year,
        doi=str(doi) if doi else None,
        journal=str(journal) if journal else None,
    )


def parse_ris_file(path: Path) -> list[Citation]:
    """
    Parse a RIS file and return a list of Citation objects.

    Args:
        path: Path to the RIS file

    Returns:
        List of Citation objects

    Raises:
        FileNotFoundError: If the file doesn't exist
        rispy.RISError: If the file is not valid RIS format
    """
    if not path.exists():
        raise FileNotFoundError(f"RIS file not found: {path}")

    logger.info("Parsing RIS file: %s", path)

    with open(path, encoding="utf-8", errors="replace") as f:
        entries = rispy.load(f)

    citations = []
    for i, entry in enumerate(entries):
        try:
            citation = parse_ris_entry(entry, i)
            citations.append(citation)
        except Exception:
            logger.exception("Failed to parse RIS entry %d", i)

    logger.info("Parsed %d citations from RIS file", len(citations))
    return citations


def parse_ris_string(content: str) -> list[Citation]:
    """
    Parse RIS content from a string.

    Args:
        content: RIS content as a string

    Returns:
        List of Citation objects
    """
    entries = rispy.loads(content)

    citations = []
    for i, entry in enumerate(entries):
        try:
            citation = parse_ris_entry(entry, i)
            citations.append(citation)
        except Exception:
            logger.exception("Failed to parse RIS entry %d", i)

    return citations
