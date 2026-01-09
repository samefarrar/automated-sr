"""Tests for Zotero integration."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from automated_sr.citations.zotero import (
    ZOTERO_LOCAL_API,
    ZoteroClient,
    ZoteroError,
    ZoteroLocalClient,
)
from automated_sr.config import ZoteroConfig
from automated_sr.models import Citation

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_citation() -> Citation:
    """Create a sample citation for testing."""
    return Citation(
        id=1,
        review_id=1,
        source="test",
        source_key="test-key-1",
        title="Deep Learning for Medical Image Analysis",
        authors=["Smith, John", "Jane Doe"],
        abstract="This study evaluates deep learning methods.",
        year=2023,
        doi="10.1234/test.2023.001",
        journal="Journal of Medical AI",
    )


@pytest.fixture
def sample_citations() -> list[Citation]:
    """Create multiple sample citations for testing."""
    return [
        Citation(
            id=1,
            source="test",
            title="Study One",
            authors=["Smith, John"],
            year=2023,
            doi="10.1234/001",
        ),
        Citation(
            id=2,
            source="test",
            title="Study Two",
            authors=["Doe, Jane", "Bob Wilson"],
            year=2024,
            abstract="Abstract text here.",
            journal="Test Journal",
        ),
        Citation(
            id=3,
            source="test",
            title="Study Three",
            authors=["SingleName"],
            year=2022,
        ),
    ]


@pytest.fixture
def zotero_config() -> ZoteroConfig:
    """Create a Zotero configuration for testing."""
    return ZoteroConfig(
        library_id="12345",
        library_type="user",
        api_key="test-api-key",
        local=False,
    )


@pytest.fixture
def mock_http_client() -> MagicMock:
    """Create a mock HTTP client for ZoteroLocalClient."""
    return MagicMock(spec=httpx.Client)


# =============================================================================
# ZoteroLocalClient Tests
# =============================================================================


class TestZoteroLocalClientInit:
    """Tests for ZoteroLocalClient initialization."""

    def test_default_base_url(self) -> None:
        """Test that default base URL is set correctly."""
        with patch("automated_sr.citations.zotero.httpx.Client"):
            client = ZoteroLocalClient()
            assert client.base_url == ZOTERO_LOCAL_API

    def test_custom_base_url(self) -> None:
        """Test that custom base URL can be specified."""
        with patch("automated_sr.citations.zotero.httpx.Client"):
            client = ZoteroLocalClient(base_url="http://custom:1234")
            assert client.base_url == "http://custom:1234"

    def test_context_manager(self) -> None:
        """Test context manager protocol."""
        with patch("automated_sr.citations.zotero.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            with ZoteroLocalClient() as client:
                assert client is not None

            mock_client.close.assert_called_once()


class TestZoteroLocalClientIsRunning:
    """Tests for ZoteroLocalClient.is_running()."""

    def test_is_running_true(self) -> None:
        """Test is_running returns True when Zotero responds correctly."""
        with patch("automated_sr.citations.zotero.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = "Zotero is running"
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            client = ZoteroLocalClient()
            assert client.is_running() is True

            mock_client.get.assert_called_once_with(f"{ZOTERO_LOCAL_API}/connector/ping")

    def test_is_running_false_wrong_response(self) -> None:
        """Test is_running returns False for unexpected response."""
        with patch("automated_sr.citations.zotero.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = "Something else"
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            client = ZoteroLocalClient()
            assert client.is_running() is False

    def test_is_running_false_connection_error(self) -> None:
        """Test is_running returns False when connection fails."""
        with patch("automated_sr.citations.zotero.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client_class.return_value = mock_client

            client = ZoteroLocalClient()
            assert client.is_running() is False


class TestZoteroLocalClientCitationConversion:
    """Tests for ZoteroLocalClient._citation_to_zotero_item()."""

    def test_convert_full_citation(self, sample_citation: Citation) -> None:
        """Test converting a citation with all fields."""
        with patch("automated_sr.citations.zotero.httpx.Client"):
            client = ZoteroLocalClient()
            item = client._citation_to_zotero_item(sample_citation)

            assert item["itemType"] == "journalArticle"
            assert item["title"] == "Deep Learning for Medical Image Analysis"
            assert item["abstractNote"] == "This study evaluates deep learning methods."
            assert item["date"] == "2023"
            assert item["DOI"] == "10.1234/test.2023.001"
            assert item["publicationTitle"] == "Journal of Medical AI"

    def test_convert_citation_authors_last_first(self) -> None:
        """Test author parsing for 'Last, First' format."""
        with patch("automated_sr.citations.zotero.httpx.Client"):
            client = ZoteroLocalClient()
            citation = Citation(
                source="test",
                title="Test",
                authors=["Smith, John", "Doe, Jane Marie"],
            )
            item = client._citation_to_zotero_item(citation)

            assert len(item["creators"]) == 2
            assert item["creators"][0] == {
                "creatorType": "author",
                "lastName": "Smith",
                "firstName": "John",
            }
            assert item["creators"][1] == {
                "creatorType": "author",
                "lastName": "Doe",
                "firstName": "Jane Marie",
            }

    def test_convert_citation_authors_first_last(self) -> None:
        """Test author parsing for 'First Last' format."""
        with patch("automated_sr.citations.zotero.httpx.Client"):
            client = ZoteroLocalClient()
            citation = Citation(
                source="test",
                title="Test",
                authors=["John Smith", "Jane Marie Doe"],
            )
            item = client._citation_to_zotero_item(citation)

            assert len(item["creators"]) == 2
            assert item["creators"][0] == {
                "creatorType": "author",
                "firstName": "John",
                "lastName": "Smith",
            }
            # Note: "Jane Marie Doe" splits to firstName="Jane Marie", lastName="Doe"
            assert item["creators"][1]["lastName"] == "Doe"

    def test_convert_citation_single_name_author(self) -> None:
        """Test author parsing for single name."""
        with patch("automated_sr.citations.zotero.httpx.Client"):
            client = ZoteroLocalClient()
            citation = Citation(
                source="test",
                title="Test",
                authors=["Madonna"],
            )
            item = client._citation_to_zotero_item(citation)

            assert item["creators"][0] == {
                "creatorType": "author",
                "lastName": "Madonna",
                "firstName": "",
            }

    def test_convert_minimal_citation(self) -> None:
        """Test converting a citation with minimal fields."""
        with patch("automated_sr.citations.zotero.httpx.Client"):
            client = ZoteroLocalClient()
            citation = Citation(
                source="test",
                title="Minimal Study",
                authors=[],
            )
            item = client._citation_to_zotero_item(citation)

            assert item["itemType"] == "journalArticle"
            assert item["title"] == "Minimal Study"
            assert item["creators"] == []
            assert "abstractNote" not in item
            assert "date" not in item
            assert "DOI" not in item


class TestZoteroLocalClientSaveCitations:
    """Tests for ZoteroLocalClient.save_citations()."""

    def test_save_citations_success(self, sample_citations: list[Citation]) -> None:
        """Test saving citations successfully."""
        with patch("automated_sr.citations.zotero.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            client = ZoteroLocalClient()
            successful, failed = client.save_citations(sample_citations)

            assert successful == 3
            assert failed == 0
            mock_client.post.assert_called_once()

    def test_save_citations_with_201_status(self, sample_citations: list[Citation]) -> None:
        """Test saving citations with 201 Created status."""
        with patch("automated_sr.citations.zotero.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            client = ZoteroLocalClient()
            successful, failed = client.save_citations(sample_citations)

            assert successful == 3
            assert failed == 0

    def test_save_citations_failure(self, sample_citations: list[Citation]) -> None:
        """Test handling failed saves."""
        with patch("automated_sr.citations.zotero.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            client = ZoteroLocalClient()
            successful, failed = client.save_citations(sample_citations)

            assert successful == 0
            assert failed == 3

    def test_save_citations_exception(self, sample_citations: list[Citation]) -> None:
        """Test handling exceptions during save."""
        with patch("automated_sr.citations.zotero.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")
            mock_client_class.return_value = mock_client

            client = ZoteroLocalClient()
            successful, failed = client.save_citations(sample_citations)

            assert successful == 0
            assert failed == 3

    def test_save_citations_batching(self) -> None:
        """Test that large citation lists are batched."""
        # Create 25 citations to test batching (batch_size=20)
        citations = [Citation(source="test", title=f"Study {i}", authors=[]) for i in range(25)]

        with patch("automated_sr.citations.zotero.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            client = ZoteroLocalClient()
            successful, failed = client.save_citations(citations)

            # Should be called twice: batch of 20, then batch of 5
            assert mock_client.post.call_count == 2
            assert successful == 25
            assert failed == 0

    def test_save_citations_empty_list(self) -> None:
        """Test saving empty citation list."""
        with patch("automated_sr.citations.zotero.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            client = ZoteroLocalClient()
            successful, failed = client.save_citations([])

            assert successful == 0
            assert failed == 0
            mock_client.post.assert_not_called()

    def test_save_citations_payload_format(self, sample_citation: Citation) -> None:
        """Test that the POST payload has correct format."""
        with patch("automated_sr.citations.zotero.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            client = ZoteroLocalClient()
            client.save_citations([sample_citation])

            call_args = mock_client.post.call_args
            assert call_args[0][0] == f"{ZOTERO_LOCAL_API}/connector/saveItems"

            payload = call_args[1]["json"]
            assert "items" in payload
            assert "uri" in payload
            assert len(payload["items"]) == 1


# =============================================================================
# ZoteroClient Tests
# =============================================================================


class TestZoteroClientInit:
    """Tests for ZoteroClient initialization."""

    def test_init_with_valid_config(self, zotero_config: ZoteroConfig) -> None:
        """Test initialization with valid config."""
        client = ZoteroClient(zotero_config)
        assert client.config == zotero_config

    def test_init_without_library_id_raises(self) -> None:
        """Test that missing library_id raises error."""
        config = ZoteroConfig(library_id=None)
        with pytest.raises(ZoteroError) as exc_info:
            ZoteroClient(config)
        assert "library_id is required" in str(exc_info.value)


class TestZoteroClientConnection:
    """Tests for ZoteroClient connection methods."""

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_test_connection_success(self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig) -> None:
        """Test successful connection test."""
        mock_zotero = MagicMock()
        mock_zotero.top.return_value = [{"key": "abc123"}]
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        assert client.test_connection() is True

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_test_connection_failure(self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig) -> None:
        """Test failed connection test."""
        mock_zotero = MagicMock()
        mock_zotero.top.side_effect = Exception("Connection failed")
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        assert client.test_connection() is False


class TestZoteroClientCollections:
    """Tests for ZoteroClient collection methods."""

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_list_collections(self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig) -> None:
        """Test listing collections."""
        mock_zotero = MagicMock()
        mock_zotero.collections.return_value = [
            {"key": "ABC123", "data": {"name": "Review 1", "parentCollection": None}},
            {"key": "DEF456", "data": {"name": "Review 2", "parentCollection": "ABC123"}},
        ]
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        collections = client.list_collections()

        assert len(collections) == 2
        assert collections[0]["key"] == "ABC123"
        assert collections[0]["name"] == "Review 1"
        assert collections[1]["parent"] == "ABC123"

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_list_collections_error(self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig) -> None:
        """Test handling error when listing collections."""
        mock_zotero = MagicMock()
        mock_zotero.collections.side_effect = Exception("API error")
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        collections = client.list_collections()

        assert collections == []

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_get_collection_by_name(self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig) -> None:
        """Test finding collection by name."""
        mock_zotero = MagicMock()
        mock_zotero.collections.return_value = [
            {"key": "ABC123", "data": {"name": "My Review"}},
        ]
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        key = client.get_collection_by_name("My Review")

        assert key == "ABC123"

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_get_collection_by_name_not_found(self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig) -> None:
        """Test collection not found by name."""
        mock_zotero = MagicMock()
        mock_zotero.collections.return_value = []
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        key = client.get_collection_by_name("Nonexistent")

        assert key is None

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_create_collection_success(self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig) -> None:
        """Test creating a collection."""
        mock_zotero = MagicMock()
        mock_zotero.create_collections.return_value = {
            "successful": {"0": {"key": "NEW123"}},
            "failed": {},
        }
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        key = client.create_collection("New Collection")

        assert key == "NEW123"
        mock_zotero.create_collections.assert_called_once_with([{"name": "New Collection"}])

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_create_collection_with_parent(self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig) -> None:
        """Test creating a collection with parent."""
        mock_zotero = MagicMock()
        mock_zotero.create_collections.return_value = {
            "successful": {"0": {"key": "NEW123"}},
        }
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        key = client.create_collection("Child Collection", parent_key="PARENT123")

        mock_zotero.create_collections.assert_called_once_with(
            [{"name": "Child Collection", "parentCollection": "PARENT123"}]
        )
        assert key == "NEW123"


class TestZoteroClientItems:
    """Tests for ZoteroClient item methods."""

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_get_items(self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig) -> None:
        """Test getting items from Zotero."""
        mock_zotero = MagicMock()
        mock_zotero.top.return_value = [
            {
                "key": "ITEM123",
                "data": {
                    "itemType": "journalArticle",
                    "title": "Test Article",
                    "creators": [{"creatorType": "author", "lastName": "Smith", "firstName": "John"}],
                    "abstractNote": "Test abstract",
                    "date": "2023",
                    "DOI": "10.1234/test",
                    "publicationTitle": "Test Journal",
                },
            }
        ]
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        citations = client.get_items()

        assert len(citations) == 1
        assert citations[0].title == "Test Article"
        assert citations[0].authors == ["Smith, John"]
        assert citations[0].year == 2023
        assert citations[0].doi == "10.1234/test"

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_get_items_from_collection(self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig) -> None:
        """Test getting items from a specific collection."""
        mock_zotero = MagicMock()
        mock_zotero.collection_items.return_value = [
            {
                "key": "ITEM123",
                "data": {
                    "itemType": "journalArticle",
                    "title": "Collection Item",
                    "creators": [],
                },
            }
        ]
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        citations = client.get_items(collection_key="COL123")

        mock_zotero.collection_items.assert_called_once_with("COL123", limit=100)
        assert len(citations) == 1

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_get_items_skips_attachments(self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig) -> None:
        """Test that attachments and notes are skipped."""
        mock_zotero = MagicMock()
        mock_zotero.top.return_value = [
            {"key": "1", "data": {"itemType": "attachment", "title": "PDF"}},
            {"key": "2", "data": {"itemType": "note", "note": "Some note"}},
            {"key": "3", "data": {"itemType": "journalArticle", "title": "Real Article", "creators": []}},
        ]
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        citations = client.get_items()

        assert len(citations) == 1
        assert citations[0].title == "Real Article"

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_create_items_success(
        self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig, sample_citations: list[Citation]
    ) -> None:
        """Test creating items in Zotero."""
        mock_zotero = MagicMock()
        mock_zotero.create_items.return_value = {
            "successful": {"0": {}, "1": {}, "2": {}},
            "failed": {},
        }
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        successful, failed = client.create_items(sample_citations)

        assert successful == 3
        assert failed == 0

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_create_items_partial_failure(
        self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig, sample_citations: list[Citation]
    ) -> None:
        """Test creating items with some failures."""
        mock_zotero = MagicMock()
        mock_zotero.create_items.return_value = {
            "successful": {"0": {}, "1": {}},
            "failed": {"2": {"code": 400, "message": "Invalid data"}},
        }
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        successful, failed = client.create_items(sample_citations)

        assert successful == 2
        assert failed == 1


class TestZoteroClientItemConversion:
    """Tests for ZoteroClient item conversion methods."""

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_item_to_citation_full(self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig) -> None:
        """Test converting Zotero item with all fields."""
        mock_zotero_class.return_value = MagicMock()

        client = ZoteroClient(zotero_config)
        item = {
            "key": "ABC123",
            "data": {
                "itemType": "journalArticle",
                "title": "Full Article",
                "creators": [
                    {"creatorType": "author", "lastName": "Smith", "firstName": "John"},
                    {"creatorType": "author", "name": "Organization Name"},
                ],
                "abstractNote": "Test abstract",
                "date": "2023-05-15",
                "DOI": "10.1234/test",
                "publicationTitle": "Test Journal",
            },
        }

        citation = client._item_to_citation(item)

        assert citation is not None
        assert citation.title == "Full Article"
        assert citation.source_key == "ABC123"
        assert "Smith, John" in citation.authors
        assert "Organization Name" in citation.authors
        assert citation.year == 2023
        assert citation.doi == "10.1234/test"
        assert citation.journal == "Test Journal"

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_item_to_citation_year_extraction(self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig) -> None:
        """Test year extraction from various date formats."""
        mock_zotero_class.return_value = MagicMock()
        client = ZoteroClient(zotero_config)

        # Test different date formats
        test_cases = [
            ("2023", 2023),
            ("2023-05-15", 2023),
            ("May 2023", 2023),
            ("15 May 2023", 2023),
            ("circa 1999", 1999),
        ]

        for date_str, expected_year in test_cases:
            item = {
                "key": "TEST",
                "data": {
                    "itemType": "journalArticle",
                    "title": "Test",
                    "date": date_str,
                    "creators": [],
                },
            }
            citation = client._item_to_citation(item)
            assert citation is not None
            assert citation.year == expected_year, f"Failed for date: {date_str}"

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_citation_to_zotero_item(
        self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig, sample_citation: Citation
    ) -> None:
        """Test converting Citation to Zotero item format."""
        mock_zotero_class.return_value = MagicMock()
        client = ZoteroClient(zotero_config)

        item = client._citation_to_zotero_item(sample_citation)

        assert item["itemType"] == "journalArticle"
        assert item["title"] == sample_citation.title
        assert item["abstractNote"] == sample_citation.abstract
        assert item["date"] == str(sample_citation.year)
        assert item["DOI"] == sample_citation.doi
        assert item["publicationTitle"] == sample_citation.journal


class TestZoteroClientExport:
    """Tests for ZoteroClient export methods."""

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_export_citations_to_collection_new(
        self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig, sample_citations: list[Citation]
    ) -> None:
        """Test exporting citations to a new collection."""
        mock_zotero = MagicMock()
        mock_zotero.collections.return_value = []  # No existing collections
        mock_zotero.create_collections.return_value = {
            "successful": {"0": {"key": "NEW123"}},
        }
        mock_zotero.create_items.return_value = {
            "successful": {"0": {}, "1": {}, "2": {}},
            "failed": {},
        }
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        collection_key, successful, failed = client.export_citations_to_collection(sample_citations, "New Review")

        assert collection_key == "NEW123"
        assert successful == 3
        assert failed == 0

    @patch("automated_sr.citations.zotero.zotero.Zotero")
    def test_export_citations_to_existing_collection(
        self, mock_zotero_class: MagicMock, zotero_config: ZoteroConfig, sample_citations: list[Citation]
    ) -> None:
        """Test exporting citations to an existing collection."""
        mock_zotero = MagicMock()
        mock_zotero.collections.return_value = [
            {"key": "EXIST123", "data": {"name": "Existing Review"}},
        ]
        mock_zotero.create_items.return_value = {
            "successful": {"0": {}, "1": {}, "2": {}},
            "failed": {},
        }
        mock_zotero_class.return_value = mock_zotero

        client = ZoteroClient(zotero_config)
        collection_key, successful, failed = client.export_citations_to_collection(sample_citations, "Existing Review")

        assert collection_key == "EXIST123"
        assert successful == 3
        mock_zotero.create_collections.assert_not_called()
