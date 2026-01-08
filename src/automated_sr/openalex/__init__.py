"""OpenAlex integration for article search and PDF retrieval."""

from automated_sr.openalex.client import OpenAlexClient, deduplicate_by_doi
from automated_sr.openalex.pdf_retrieval import PDFRetrievalError, PDFRetriever, get_open_access_status

__all__ = [
    "OpenAlexClient",
    "PDFRetriever",
    "PDFRetrievalError",
    "deduplicate_by_doi",
    "get_open_access_status",
]
