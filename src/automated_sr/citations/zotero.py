"""Zotero integration for accessing citations and PDFs."""

import logging
import re
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

    def get_library_id(self) -> str | None:
        """Try to get the library ID from local Zotero.

        Returns:
            Library ID if available, None otherwise.
        """
        try:
            data = self.get_selected_collection()
            if data:
                library_id = data.get("libraryID")
                if library_id is not None:
                    return str(library_id)
        except Exception:
            pass
        return None

    def get_selected_collection(self) -> dict[str, Any] | None:
        """Get the currently selected collection and collection tree from Zotero.

        Returns:
            Dict with collection info and targets, or None if unavailable.
            Response includes:
            - libraryID: int
            - libraryName: str
            - id: int (selected collection ID)
            - name: str (selected collection name)
            - targets: list of available collections with treeViewID (e.g., "C4", "L1")
        """
        try:
            response = self._http.post(
                f"{self.base_url}/connector/getSelectedCollection",
                json={},
                headers={"Content-Type": "application/json"},
            )
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return None

    def find_collection_by_name(self, name: str) -> dict[str, Any] | None:
        """Find a collection in the Zotero library by name.

        Args:
            name: The collection name to search for

        Returns:
            Dict with collection info (id, name, level) or None if not found.
        """
        data = self.get_selected_collection()
        if not data or "targets" not in data:
            return None

        for target in data["targets"]:
            if target.get("name") == name:
                return target
        return None

    def get_collections(self) -> list[dict[str, Any]]:
        """Get all collections from the Zotero library.

        Returns:
            List of collections with their treeViewID, name, and level.
        """
        data = self.get_selected_collection()
        if not data or "targets" not in data:
            return []
        return data["targets"]

    def _get_local_library_id(self) -> str:
        """Get the library ID for local Zotero API access.

        Tries in order:
        1. ZOTERO_LIBRARY_ID environment variable
        2. User ID 0 (special "current user" value for local API)
        3. Extract from error message if 0 doesn't work

        Returns:
            Library ID string that works with local API
        """
        import os
        import re

        # Check environment first
        env_id = os.environ.get("ZOTERO_LIBRARY_ID")
        if env_id:
            return env_id

        # Try user ID 0 first (special value for "current user" in local mode)
        # If that fails, the error message tells us the correct ID
        try:
            test_zot = zotero.Zotero("0", "user", local=True)
            test_zot.top(limit=1)
            return "0"
        except Exception as e:
            error_msg = str(e)
            # Error message format: "use userID 0 or 11007483"
            match = re.search(r"use userID 0 or (\d+)", error_msg)
            if match:
                user_id = match.group(1)
                logger.info("Auto-detected Zotero user ID: %s", user_id)
                return user_id

        # Fallback to 0
        return "0"

    def get_items_with_pdfs(self, library_id: str | None = None) -> list[dict[str, Any]]:
        """Get items from the currently selected collection with their PDF paths.

        Uses pyzotero local mode to query items and their attachments.
        Library ID is auto-detected if not provided.

        Args:
            library_id: Optional library ID (auto-detected if not provided)

        Returns:
            List of dicts with 'doi', 'title', 'pdf_path', 'zotero_key'
        """
        # Get library_id (auto-detect if not provided)
        if library_id is None:
            library_id = self._get_local_library_id()

        # Get selected collection info
        selected = self.get_selected_collection()
        if not selected:
            raise ZoteroError("Cannot get selected collection from Zotero")

        collection_name = selected.get("name")
        logger.info("Getting items from collection '%s'", collection_name)

        # Use pyzotero local mode
        zot = zotero.Zotero(library_id, "user", local=True)

        results = []
        try:
            # Find collection key by name (connector API gives numeric ID, pyzotero needs key)
            collection_key = None
            if collection_name:
                collections = cast(list[dict[str, Any]], zot.collections())
                for coll in collections:
                    if coll.get("data", {}).get("name") == collection_name:
                        collection_key = coll.get("key")
                        logger.info("Found collection key: %s", collection_key)
                        break

            # Get items from collection
            if collection_key:
                items = cast(list[dict[str, Any]], zot.collection_items(collection_key, limit=500))
            else:
                logger.warning("Collection key not found, getting all items")
                items = cast(list[dict[str, Any]], zot.top(limit=500))

            for item in items:
                data = item.get("data", {})
                item_type = data.get("itemType")

                # Skip attachments and notes
                if item_type in ("attachment", "note"):
                    continue

                doi = data.get("DOI")
                title = data.get("title")
                item_key = item.get("key")

                if not item_key:
                    continue

                # Extract authors from creators
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
                    year_match = re.search(r"\b(19|20)\d{2}\b", date_str)
                    if year_match:
                        year = int(year_match.group())

                # Get PDF attachment
                pdf_path = self._get_pdf_for_item(zot, item_key)

                results.append(
                    {
                        "doi": doi,
                        "title": title,
                        "authors": authors,
                        "year": year,
                        "abstract": data.get("abstractNote"),
                        "journal": data.get("publicationTitle") or data.get("journalAbbreviation"),
                        "pdf_path": pdf_path,
                        "zotero_key": item_key,
                    }
                )

            logger.info("Found %d items, %d with PDFs", len(results), sum(1 for r in results if r["pdf_path"]))
            return results

        except Exception:
            logger.exception("Failed to get items from Zotero")
            raise ZoteroError("Failed to query Zotero library") from None

    def _get_pdf_for_item(self, zot: "zotero.Zotero", item_key: str) -> Path | None:
        """Get PDF path for a Zotero item using pyzotero."""
        try:
            children = cast(list[dict[str, Any]], zot.children(item_key))

            for child in children:
                data = child.get("data", {})
                if data.get("contentType") == "application/pdf":
                    # For linked files
                    if data.get("linkMode") == "linked_file":
                        path_str = data.get("path")
                        if path_str:
                            path = Path(path_str)
                            if path.exists():
                                return path
                    # For stored files
                    else:
                        attachment_key = child.get("key")
                        if attachment_key:
                            # Find in Zotero storage
                            possible_dirs = [
                                Path.home() / "Zotero" / "storage" / attachment_key,
                                Path.home() / "Library" / "Application Support" / "Zotero" / "storage" / attachment_key,
                            ]
                            for storage_dir in possible_dirs:
                                if storage_dir.exists():
                                    for file in storage_dir.iterdir():
                                        if file.suffix.lower() == ".pdf":
                                            return file
            return None
        except Exception:
            return None

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

    def save_to_collection(
        self,
        citations: list[Citation],
        collection_name: str,
        library_id: str | None = None,
    ) -> tuple[str | None, int, int]:
        """
        Save citations to a specific Zotero collection using pyzotero local mode.

        Note: The local API is read-only for write operations like creating collections.
        This method will fail if the collection doesn't exist.

        Args:
            citations: List of citations to save
            collection_name: Name of the collection to create/use
            library_id: Optional library ID (auto-detected if not provided)

        Returns:
            Tuple of (collection_key, successful_count, failed_count)

        Raises:
            ZoteroError: If collection creation fails (local API limitation)
        """
        # Get library_id (auto-detect if not provided)
        if library_id is None:
            library_id = self._get_local_library_id()

        # Use pyzotero with local mode
        zot = zotero.Zotero(library_id, "user", local=True)

        # Find or create collection
        collection_key = None
        try:
            collections = cast(list[dict[str, Any]], zot.collections())
            for coll in collections:
                if coll.get("data", {}).get("name") == collection_name:
                    collection_key = coll.get("key")
                    logger.info("Using existing collection '%s' (%s)", collection_name, collection_key)
                    break

            if collection_key is None:
                # Create new collection
                result = zot.create_collections([{"name": collection_name}])
                if result and "successful" in result and "0" in result["successful"]:
                    collection_key = result["successful"]["0"]["key"]
                    logger.info("Created collection '%s' (%s)", collection_name, collection_key)
                else:
                    logger.error("Failed to create collection: %s", result)
                    return None, 0, len(citations)
        except Exception:
            logger.exception("Failed to manage collections")
            return None, 0, len(citations)

        # Convert citations to Zotero format and add to collection
        successful = 0
        failed = 0
        batch_size = 50

        for i in range(0, len(citations), batch_size):
            batch = citations[i : i + batch_size]
            items = []

            for citation in batch:
                item = self._citation_to_zotero_item(citation)
                item["collections"] = [collection_key]
                items.append(item)

            try:
                result = zot.create_items(items)
                if result:
                    batch_successful = len(result.get("successful", {}))
                    batch_failed = len(result.get("failed", {}))
                    successful += batch_successful
                    failed += batch_failed
                    logger.info("Saved batch of %d items to collection", batch_successful)

                    if result.get("failed"):
                        for idx, error in result["failed"].items():
                            logger.warning("Failed to create item %s: %s", idx, error)
                else:
                    failed += len(batch)
            except Exception:
                logger.exception("Failed to create batch of %d items", len(batch))
                failed += len(batch)

        logger.info("Saved %d citations to collection '%s' (%d failed)", successful, collection_name, failed)
        return collection_key, successful, failed


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
