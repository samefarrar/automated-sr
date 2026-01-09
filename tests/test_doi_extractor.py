"""Tests for PDF DOI extraction."""


from automated_sr.pdf.doi_extractor import extract_doi_regex, normalize_doi


class TestExtractDoiRegex:
    """Tests for regex-based DOI extraction."""

    def test_extract_simple_doi(self) -> None:
        """Test extracting a simple DOI."""
        text = "This paper is available at https://doi.org/10.1234/test.2023.001"
        doi = extract_doi_regex(text)
        assert doi == "10.1234/test.2023.001"

    def test_extract_doi_without_url(self) -> None:
        """Test extracting DOI without URL prefix."""
        text = "DOI: 10.1016/j.cell.2023.01.001"
        doi = extract_doi_regex(text)
        assert doi == "10.1016/j.cell.2023.01.001"

    def test_extract_doi_with_trailing_punctuation(self) -> None:
        """Test extracting DOI with trailing punctuation."""
        text = "See reference (10.1234/test.001)."
        doi = extract_doi_regex(text)
        assert doi == "10.1234/test.001"

    def test_extract_doi_complex(self) -> None:
        """Test extracting complex DOI with special characters."""
        text = "Reference: 10.1007/s12652-021-03612-z available online"
        doi = extract_doi_regex(text)
        assert doi == "10.1007/s12652-021-03612-z"

    def test_no_doi_found(self) -> None:
        """Test when no DOI is present."""
        text = "This text contains no DOI identifier."
        doi = extract_doi_regex(text)
        assert doi is None

    def test_extract_first_doi(self) -> None:
        """Test extracting first DOI when multiple present."""
        text = "Primary: 10.1234/first.001, also see 10.1234/second.002"
        doi = extract_doi_regex(text)
        assert doi == "10.1234/first.001"

    def test_doi_in_header(self) -> None:
        """Test DOI typically found in paper headers."""
        text = """
        Journal of Machine Learning Research
        doi:10.5555/jmlr.2023.001

        Abstract: This paper presents...
        """
        doi = extract_doi_regex(text)
        assert doi == "10.5555/jmlr.2023.001"


class TestNormalizeDoi:
    """Tests for DOI normalization."""

    def test_normalize_with_https_prefix(self) -> None:
        """Test normalizing DOI with https://doi.org/ prefix."""
        doi = normalize_doi("https://doi.org/10.1234/test.001")
        assert doi == "10.1234/test.001"

    def test_normalize_with_http_prefix(self) -> None:
        """Test normalizing DOI with http://doi.org/ prefix."""
        doi = normalize_doi("http://doi.org/10.1234/test.001")
        assert doi == "10.1234/test.001"

    def test_normalize_with_doi_prefix(self) -> None:
        """Test normalizing DOI with doi: prefix."""
        doi = normalize_doi("doi:10.1234/test.001")
        assert doi == "10.1234/test.001"

    def test_normalize_with_doi_org_prefix(self) -> None:
        """Test normalizing DOI with doi.org/ prefix."""
        doi = normalize_doi("doi.org/10.1234/test.001")
        assert doi == "10.1234/test.001"

    def test_normalize_lowercase(self) -> None:
        """Test that normalization lowercases the DOI."""
        doi = normalize_doi("10.1234/TEST.001")
        assert doi == "10.1234/test.001"

    def test_normalize_strips_whitespace(self) -> None:
        """Test that normalization strips whitespace."""
        doi = normalize_doi("  10.1234/test.001  ")
        assert doi == "10.1234/test.001"

    def test_normalize_already_clean(self) -> None:
        """Test normalizing an already clean DOI."""
        doi = normalize_doi("10.1234/test.001")
        assert doi == "10.1234/test.001"

    def test_normalize_matches_different_formats(self) -> None:
        """Test that different formats normalize to the same value."""
        formats = [
            "10.1234/test.001",
            "https://doi.org/10.1234/test.001",
            "doi:10.1234/test.001",
            "DOI:10.1234/TEST.001",
            "  https://doi.org/10.1234/TEST.001  ",
        ]
        normalized = [normalize_doi(f) for f in formats]
        assert len(set(normalized)) == 1  # All should be the same
