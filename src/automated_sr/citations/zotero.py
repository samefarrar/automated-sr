"""Zotero integration for accessing citations and PDFs."""

import logging
from pathlib import Path
from typing import Any, cast

from pyzotero import zotero

from automated_sr.config import ZoteroConfig
from automated_sr.models import Citation

logger = logging.getLogger(__name__)


class ZoteroError(Exception):
    """Error interacting with Zotero."""


class ZoteroClient:
    """Client for interacting with Zotero libraries."""

    def __init__(self, config: ZoteroConfig) -> None:
        """
        Initialize the Zotero client.

        Args:
            config: Zotero configuration settings

        Raises:
            ZoteroError: If required configuration is missing
        """
        if not config.library_id:
            raise ZoteroError("Zotero library_id is required. Set ZOTERO_LIBRARY_ID environment variable.")

        self.config = config
        self._client: zotero.Zotero | None = None

    @property
    def client(self) -> zotero.Zotero:
        """Get the Zotero client, creating it if necessary."""
        if self._client is None:
            self._client = zotero.Zotero(
                self.config.library_id,
                self.config.library_type,
                self.config.api_key,
                local=self.config.local,
            )
        return self._client

    def test_connection(self) -> bool:
        """Test the connection to Zotero."""
        try:
            # Try to fetch a single item to verify connection
            self.client.top(limit=1)
            return True
        except Exception:
            logger.exception("Failed to connect to Zotero")
            return False

    def list_collections(self) -> list[dict[str, Any]]:
        """List all collections in the library."""
        try:
            collections = cast(list[dict[str, Any]], self.client.collections())
            return [
                {"key": c["key"], "name": c["data"]["name"], "parent": c["data"].get("parentCollection")}
                for c in collections
            ]
        except Exception:
            logger.exception("Failed to list Zotero collections")
            return []

    def get_items(self, collection_key: str | None = None, limit: int | None = None) -> list[Citation]:
        """
        Get items from Zotero, optionally filtered by collection.

        Args:
            collection_key: Optional collection key to filter by
            limit: Maximum number of items to return

        Returns:
            List of Citation objects
        """
        try:
            items: list[dict[str, Any]]
            if collection_key:
                items = cast(list[dict[str, Any]], self.client.collection_items(collection_key, limit=limit or 100))
            else:
                items = cast(list[dict[str, Any]], self.client.top(limit=limit or 100))

            citations = []
            for item in items:
                citation = self._item_to_citation(item)
                if citation:
                    citations.append(citation)

            logger.info("Retrieved %d citations from Zotero", len(citations))
            return citations

        except Exception:
            logger.exception("Failed to get items from Zotero")
            return []

    def _item_to_citation(self, item: dict[str, Any]) -> Citation | None:
        """Convert a Zotero item to a Citation object."""
        data = item.get("data", {})
        item_type = data.get("itemType")

        # Skip attachments and notes - we only want bibliographic items
        if item_type in ("attachment", "note"):
            return None

        title = data.get("title", "")
        if not title:
            return None

        # Extract authors
        creators = data.get("creators", [])
        authors = []
        for creator in creators:
            if creator.get("creatorType") in ("author", "editor"):
                name_parts = []
                if creator.get("lastName"):
                    name_parts.append(creator["lastName"])
                if creator.get("firstName"):
                    name_parts.append(creator["firstName"])
                if name_parts:
                    authors.append(", ".join(name_parts))
                elif creator.get("name"):
                    authors.append(creator["name"])

        # Parse year from date
        year = None
        date_str = data.get("date", "")
        if date_str:
            # Try to extract 4-digit year
            import re

            year_match = re.search(r"\b(19|20)\d{2}\b", date_str)
            if year_match:
                year = int(year_match.group())

        return Citation(
            source="zotero",
            source_key=item.get("key"),
            title=title,
            authors=authors,
            abstract=data.get("abstractNote"),
            year=year,
            doi=data.get("DOI"),
            journal=data.get("publicationTitle") or data.get("journalAbbreviation"),
        )

    def get_pdf_path(self, item_key: str) -> Path | None:
        """
        Get the local path to the PDF attachment for an item.

        Args:
            item_key: The Zotero item key

        Returns:
            Path to the PDF file, or None if not found
        """
        try:
            children = cast(list[dict[str, Any]], self.client.children(item_key))

            for child in children:
                data: dict[str, Any] = child.get("data", {})
                if data.get("contentType") == "application/pdf":
                    # For linked files, use the path directly
                    if data.get("linkMode") == "linked_file":
                        path_str = data.get("path")
                        if path_str:
                            path = Path(path_str)
                            if path.exists():
                                return path
                            logger.warning("PDF path does not exist: %s", path)
                    # For stored files, we need to get the storage path
                    else:
                        # The file is stored in Zotero's storage
                        attachment_key = child.get("key")
                        if attachment_key:
                            return self._get_stored_pdf_path(attachment_key)

            logger.debug("No PDF attachment found for item %s", item_key)
            return None

        except Exception:
            logger.exception("Failed to get PDF path for item %s", item_key)
            return None

    def _get_stored_pdf_path(self, attachment_key: str) -> Path | None:
        """Get the path to a PDF stored in Zotero's storage."""
        # Zotero stores files in a directory structure based on the attachment key
        # The exact location depends on the Zotero data directory
        try:
            # Try common Zotero data directory locations
            possible_data_dirs = [
                Path.home() / "Zotero",
                Path.home() / ".zotero" / "zotero",
                Path.home() / "Library" / "Application Support" / "Zotero",  # macOS
            ]

            for data_dir in possible_data_dirs:
                storage_dir = data_dir / "storage" / attachment_key
                if storage_dir.exists():
                    # Find PDF file in the storage directory
                    for file in storage_dir.iterdir():
                        if file.suffix.lower() == ".pdf":
                            return file

            return None

        except Exception:
            logger.exception("Failed to find stored PDF for attachment %s", attachment_key)
            return None

    def get_pdf_content(self, item_key: str) -> bytes | None:
        """
        Get the PDF content for an item via the Zotero API.

        Args:
            item_key: The Zotero item key

        Returns:
            PDF content as bytes, or None if not available
        """
        try:
            children = cast(list[dict[str, Any]], self.client.children(item_key))

            for child in children:
                data: dict[str, Any] = child.get("data", {})
                if data.get("contentType") == "application/pdf":
                    attachment_key = child.get("key")
                    if attachment_key:
                        content = cast(bytes, self.client.file(attachment_key))
                        return content

            logger.debug("No PDF attachment found for item %s", item_key)
            return None

        except Exception:
            logger.exception("Failed to get PDF content for item %s", item_key)
            return None

    def get_citations_with_pdfs(
        self, collection_key: str | None = None, limit: int | None = None
    ) -> tuple[list[Citation], list[Citation]]:
        """
        Get citations and check for PDF availability.

        Args:
            collection_key: Optional collection key to filter by
            limit: Maximum number of items to return

        Returns:
            Tuple of (citations_with_pdfs, citations_without_pdfs)
        """
        citations = self.get_items(collection_key, limit)

        with_pdfs = []
        without_pdfs = []

        for citation in citations:
            if citation.source_key:
                pdf_path = self.get_pdf_path(citation.source_key)
                if pdf_path:
                    citation.pdf_path = pdf_path
                    with_pdfs.append(citation)
                else:
                    without_pdfs.append(citation)
                    logger.warning("No PDF found for: %s", citation.title[:50])
            else:
                without_pdfs.append(citation)

        logger.info("Found %d citations with PDFs, %d without", len(with_pdfs), len(without_pdfs))
        return with_pdfs, without_pdfs
