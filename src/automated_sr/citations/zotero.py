"""Zotero integration for accessing citations and PDFs."""

import logging
from pathlib import Path
from typing import Any, cast

import httpx
from pyzotero import zotero

from automated_sr.config import ZoteroConfig
from automated_sr.models import Citation

logger = logging.getLogger(__name__)

# Local Zotero connector API base URL
ZOTERO_LOCAL_API = "http://localhost:23119"


class ZoteroError(Exception):
    """Error interacting with Zotero."""


class ZoteroLocalClient:
    """Client for interacting with local Zotero instance via connector API.

    This uses the local HTTP API at localhost:23119 which requires Zotero
    to be running but doesn't need any API keys.
    """

    def __init__(self, base_url: str = ZOTERO_LOCAL_API) -> None:
        """Initialize the local Zotero client."""
        self.base_url = base_url
        self._http = httpx.Client(timeout=30.0)

    def close(self) -> None:
        """Close the HTTP client."""
        self._http.close()

    def __enter__(self) -> "ZoteroLocalClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def is_running(self) -> bool:
        """Check if Zotero is running."""
        try:
            response = self._http.get(f"{self.base_url}/connector/ping")
            return "Zotero is running" in response.text
        except Exception:
            return False

    def _citation_to_zotero_item(self, citation: Citation) -> dict[str, Any]:
        """Convert a Citation to Zotero item format."""
        creators = []
        for author in citation.authors:
            if ", " in author:
                parts = author.split(", ", 1)
                creators.append(
                    {
                        "creatorType": "author",
                        "lastName": parts[0],
                        "firstName": parts[1] if len(parts) > 1 else "",
                    }
                )
            else:
                parts = author.rsplit(" ", 1)
                if len(parts) == 2:
                    creators.append(
                        {
                            "creatorType": "author",
                            "firstName": parts[0],
                            "lastName": parts[1],
                        }
                    )
                else:
                    creators.append(
                        {
                            "creatorType": "author",
                            "lastName": author,
                            "firstName": "",
                        }
                    )

        item: dict[str, Any] = {
            "itemType": "journalArticle",
            "title": citation.title,
            "creators": creators,
        }

        if citation.abstract:
            item["abstractNote"] = citation.abstract
        if citation.year:
            item["date"] = str(citation.year)
        if citation.doi:
            item["DOI"] = citation.doi
        if citation.journal:
            item["publicationTitle"] = citation.journal

        return item

    def save_citations(
        self,
        citations: list[Citation],
        collection_name: str | None = None,
    ) -> tuple[int, int]:
        """
        Save citations to Zotero via the local connector API.

        Args:
            citations: List of citations to save
            collection_name: Optional collection name (items go to selected collection if None)

        Returns:
            Tuple of (successful_count, failed_count)
        """
        successful = 0
        failed = 0

        # Convert citations to Zotero format
        items = [self._citation_to_zotero_item(c) for c in citations]

        # The connector API expects items in batches
        # We'll send them in smaller batches to avoid timeouts
        batch_size = 20

        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]

            payload = {
                "items": batch,
                "uri": "http://systematic-review-import",  # Required field
            }

            try:
                response = self._http.post(
                    f"{self.base_url}/connector/saveItems",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code == 200 or response.status_code == 201:
                    successful += len(batch)
                    logger.info("Saved batch of %d items to Zotero", len(batch))
                else:
                    failed += len(batch)
                    logger.warning("Failed to save batch: %s", response.text)

            except Exception:
                logger.exception("Error saving batch to Zotero")
                failed += len(batch)

        logger.info("Saved %d citations to Zotero (%d failed)", successful, failed)
        return successful, failed


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

    def create_collection(self, name: str, parent_key: str | None = None) -> str | None:
        """
        Create a new collection (folder) in Zotero.

        Args:
            name: Name of the collection
            parent_key: Optional parent collection key for nested collections

        Returns:
            The key of the created collection, or None if failed
        """
        try:
            collection_data: dict[str, Any] = {"name": name}
            if parent_key:
                collection_data["parentCollection"] = parent_key

            result = self.client.create_collections([collection_data])

            if result and "successful" in result:
                # Get the key of the created collection
                successful = result["successful"]
                if successful and "0" in successful:
                    key = successful["0"]["key"]
                    logger.info("Created Zotero collection '%s' with key %s", name, key)
                    return key

            logger.warning("Failed to create collection: %s", result)
            return None

        except Exception:
            logger.exception("Failed to create Zotero collection '%s'", name)
            return None

    def get_collection_by_name(self, name: str) -> str | None:
        """
        Find a collection by name.

        Args:
            name: Name of the collection to find

        Returns:
            Collection key if found, None otherwise
        """
        collections = self.list_collections()
        for collection in collections:
            if collection["name"] == name:
                return collection["key"]
        return None

    def _citation_to_zotero_item(self, citation: Citation) -> dict[str, Any]:
        """
        Convert a Citation to Zotero item format.

        Args:
            citation: Citation object to convert

        Returns:
            Dictionary in Zotero item format
        """
        # Determine item type based on source
        item_type = "journalArticle"

        # Build creators list
        creators = []
        for author in citation.authors:
            # Try to parse "Last, First" format
            if ", " in author:
                parts = author.split(", ", 1)
                creators.append(
                    {
                        "creatorType": "author",
                        "lastName": parts[0],
                        "firstName": parts[1] if len(parts) > 1 else "",
                    }
                )
            else:
                # Assume "First Last" format or single name
                parts = author.rsplit(" ", 1)
                if len(parts) == 2:
                    creators.append(
                        {
                            "creatorType": "author",
                            "firstName": parts[0],
                            "lastName": parts[1],
                        }
                    )
                else:
                    creators.append(
                        {
                            "creatorType": "author",
                            "name": author,
                        }
                    )

        item: dict[str, Any] = {
            "itemType": item_type,
            "title": citation.title,
            "creators": creators,
        }

        if citation.abstract:
            item["abstractNote"] = citation.abstract
        if citation.year:
            item["date"] = str(citation.year)
        if citation.doi:
            item["DOI"] = citation.doi
        if citation.journal:
            item["publicationTitle"] = citation.journal

        return item

    def create_items(
        self,
        citations: list[Citation],
        collection_key: str | None = None,
        batch_size: int = 50,
    ) -> tuple[int, int]:
        """
        Create Zotero items from citations.

        Args:
            citations: List of citations to create
            collection_key: Optional collection to add items to
            batch_size: Number of items to create per API call (max 50)

        Returns:
            Tuple of (successful_count, failed_count)
        """
        successful = 0
        failed = 0

        # Process in batches (Zotero API limit is 50 items per request)
        for i in range(0, len(citations), batch_size):
            batch = citations[i : i + batch_size]

            items = []
            for citation in batch:
                item = self._citation_to_zotero_item(citation)
                if collection_key:
                    item["collections"] = [collection_key]
                items.append(item)

            try:
                result = self.client.create_items(items)

                if result:
                    batch_successful = len(result.get("successful", {}))
                    batch_failed = len(result.get("failed", {}))
                    successful += batch_successful
                    failed += batch_failed

                    if result.get("failed"):
                        for idx, error in result["failed"].items():
                            logger.warning("Failed to create item %s: %s", idx, error)
                else:
                    failed += len(batch)

            except Exception:
                logger.exception("Failed to create batch of %d items", len(batch))
                failed += len(batch)

        logger.info("Created %d Zotero items (%d failed)", successful, failed)
        return successful, failed

    def export_citations_to_collection(
        self,
        citations: list[Citation],
        collection_name: str,
    ) -> tuple[str | None, int, int]:
        """
        Export citations to a Zotero collection, creating it if needed.

        Args:
            citations: List of citations to export
            collection_name: Name of the collection to create/use

        Returns:
            Tuple of (collection_key, successful_count, failed_count)
        """
        # Check if collection already exists
        collection_key = self.get_collection_by_name(collection_name)

        if collection_key:
            logger.info("Using existing collection '%s' (%s)", collection_name, collection_key)
        else:
            collection_key = self.create_collection(collection_name)
            if not collection_key:
                logger.error("Failed to create collection '%s'", collection_name)
                return None, 0, len(citations)

        # Create items in the collection
        successful, failed = self.create_items(citations, collection_key)

        return collection_key, successful, failed
