"""Tests for data models."""

from pathlib import Path

from automated_sr.models import (
    APIProvider,
    Citation,
    ExtractionVariable,
    ReviewerConfig,
    ReviewProtocol,
    ScreeningDecision,
    ScreeningResult,
)


class TestCitation:
    """Tests for Citation model."""

    def test_has_abstract_with_abstract(self, sample_citation: Citation) -> None:
        """Test has_abstract returns True when abstract exists."""
        assert sample_citation.has_abstract() is True

    def test_has_abstract_without_abstract(self, sample_citation_no_abstract: Citation) -> None:
        """Test has_abstract returns False when no abstract."""
        assert sample_citation_no_abstract.has_abstract() is False

    def test_has_abstract_empty_string(self) -> None:
        """Test has_abstract returns False for empty string."""
        citation = Citation(title="Test", abstract="")
        assert citation.has_abstract() is False

    def test_has_abstract_whitespace_only(self) -> None:
        """Test has_abstract returns False for whitespace only."""
        citation = Citation(title="Test", abstract="   \n\t  ")
        assert citation.has_abstract() is False

    def test_has_pdf_without_path(self, sample_citation: Citation) -> None:
        """Test has_pdf returns False when no pdf_path."""
        assert sample_citation.has_pdf() is False

    def test_has_pdf_nonexistent_path(self, sample_citation: Citation) -> None:
        """Test has_pdf returns False when path doesn't exist."""
        sample_citation.pdf_path = Path("/nonexistent/path.pdf")
        assert sample_citation.has_pdf() is False


class TestScreeningDecision:
    """Tests for ScreeningDecision enum."""

    def test_decision_values(self) -> None:
        """Test decision enum values."""
        assert ScreeningDecision.INCLUDE.value == "include"
        assert ScreeningDecision.EXCLUDE.value == "exclude"
        assert ScreeningDecision.UNCERTAIN.value == "uncertain"

    def test_decision_from_string(self) -> None:
        """Test creating decision from string."""
        assert ScreeningDecision("include") == ScreeningDecision.INCLUDE
        assert ScreeningDecision("exclude") == ScreeningDecision.EXCLUDE


class TestAPIProvider:
    """Tests for APIProvider enum."""

    def test_provider_values(self) -> None:
        """Test provider enum values."""
        assert APIProvider.ANTHROPIC.value == "anthropic"
        assert APIProvider.OPENAI.value == "openai"
        assert APIProvider.OPENROUTER.value == "openrouter"


class TestReviewerConfig:
    """Tests for ReviewerConfig model."""

    def test_default_values(self) -> None:
        """Test default values for ReviewerConfig."""
        config = ReviewerConfig(
            name="test",
            model="claude-3-5-haiku-20241022",
            api=APIProvider.ANTHROPIC,
        )
        assert config.prompt_template == "rigorous"
        assert config.role == "primary"
        assert config.custom_prompt is None

    def test_tiebreaker_role(self) -> None:
        """Test tiebreaker role configuration."""
        config = ReviewerConfig(
            name="tiebreaker",
            model="claude-sonnet-4-5-20250929",
            api=APIProvider.ANTHROPIC,
            role="tiebreaker",
        )
        assert config.role == "tiebreaker"


class TestReviewProtocol:
    """Tests for ReviewProtocol model."""

    def test_get_primary_reviewers(self, multi_reviewer_protocol: ReviewProtocol) -> None:
        """Test getting primary reviewers."""
        primary = multi_reviewer_protocol.get_primary_reviewers()
        assert len(primary) == 2
        assert all(r.role == "primary" for r in primary)

    def test_get_tiebreaker(self, multi_reviewer_protocol: ReviewProtocol) -> None:
        """Test getting tiebreaker reviewer."""
        tiebreaker = multi_reviewer_protocol.get_tiebreaker()
        assert tiebreaker is not None
        assert tiebreaker.name == "tiebreaker"
        assert tiebreaker.role == "tiebreaker"

    def test_get_tiebreaker_none(self, sample_protocol: ReviewProtocol) -> None:
        """Test getting tiebreaker when none configured."""
        tiebreaker = sample_protocol.get_tiebreaker()
        assert tiebreaker is None

    def test_has_multi_reviewer_true(self, multi_reviewer_protocol: ReviewProtocol) -> None:
        """Test has_multi_reviewer with multiple reviewers."""
        assert multi_reviewer_protocol.has_multi_reviewer() is True

    def test_has_multi_reviewer_false(self, sample_protocol: ReviewProtocol) -> None:
        """Test has_multi_reviewer without reviewers."""
        assert sample_protocol.has_multi_reviewer() is False

    def test_from_yaml(self, temp_dir: Path) -> None:
        """Test loading protocol from YAML file."""
        yaml_content = """
name: yaml-test
objective: Test loading from YAML
inclusion_criteria:
  - Criterion 1
  - Criterion 2
exclusion_criteria:
  - Exclusion 1
extraction_variables:
  - name: var1
    description: Test variable
    type: string
settings:
  model: test-model
reviewers:
  - name: reviewer1
    model: test-model
    api: anthropic
    prompt_template: rigorous
    role: primary
"""
        yaml_path = temp_dir / "protocol.yaml"
        yaml_path.write_text(yaml_content)

        protocol = ReviewProtocol.from_yaml(yaml_path)

        assert protocol.name == "yaml-test"
        assert protocol.objective == "Test loading from YAML"
        assert len(protocol.inclusion_criteria) == 2
        assert len(protocol.exclusion_criteria) == 1
        assert len(protocol.extraction_variables) == 1
        assert protocol.model == "test-model"
        assert len(protocol.reviewers) == 1

    def test_from_yaml_with_options(self, temp_dir: Path) -> None:
        """Test loading protocol with extraction variable options."""
        yaml_content = """
name: options-test
objective: Test options support
inclusion_criteria:
  - Criterion 1
exclusion_criteria:
  - Exclusion 1
extraction_variables:
  - name: design
    description: Study design
    type: string
    options:
      - RCT
      - cohort
      - case-control
  - name: outcomes
    description: Outcomes measured
    type: list
    options:
      - mortality
      - morbidity
  - name: blinded
    description: Was the study blinded
    type: boolean
  - name: sample_size
    description: Number of participants
    type: integer
"""
        yaml_path = temp_dir / "protocol.yaml"
        yaml_path.write_text(yaml_content)

        protocol = ReviewProtocol.from_yaml(yaml_path)

        assert len(protocol.extraction_variables) == 4
        design_var = protocol.extraction_variables[0]
        assert design_var.options == ["RCT", "cohort", "case-control"]
        assert protocol.extraction_variables[1].type == "list"
        assert protocol.extraction_variables[2].type == "boolean"
        assert protocol.extraction_variables[3].options is None

    def test_to_yaml(self, sample_protocol: ReviewProtocol, temp_dir: Path) -> None:
        """Test saving protocol to YAML file."""
        yaml_path = temp_dir / "output.yaml"
        sample_protocol.to_yaml(yaml_path)

        assert yaml_path.exists()

        # Load it back and verify
        loaded = ReviewProtocol.from_yaml(yaml_path)
        assert loaded.name == sample_protocol.name
        assert loaded.objective == sample_protocol.objective

    def test_to_yaml_with_options(self, temp_dir: Path) -> None:
        """Test round-trip with extraction variable options."""
        protocol = ReviewProtocol(
            name="options-roundtrip",
            objective="Test options round-trip",
            inclusion_criteria=["Criterion 1"],
            exclusion_criteria=["Exclusion 1"],
            extraction_variables=[
                ExtractionVariable(
                    name="design",
                    description="Study design",
                    options=["RCT", "cohort"],
                ),
                ExtractionVariable(
                    name="count",
                    description="Count",
                    type="integer",
                ),
            ],
        )
        yaml_path = temp_dir / "options.yaml"
        protocol.to_yaml(yaml_path)

        loaded = ReviewProtocol.from_yaml(yaml_path)
        assert loaded.extraction_variables[0].options == ["RCT", "cohort"]
        assert loaded.extraction_variables[1].options is None


class TestScreeningResult:
    """Tests for ScreeningResult model."""

    def test_create_result(self) -> None:
        """Test creating a screening result."""
        result = ScreeningResult(
            citation_id=1,
            decision=ScreeningDecision.INCLUDE,
            reasoning="Meets criteria",
            model="test-model",
        )
        assert result.citation_id == 1
        assert result.decision == ScreeningDecision.INCLUDE
        assert result.screened_at is not None

    def test_result_with_reviewer_name(self) -> None:
        """Test result with reviewer name."""
        result = ScreeningResult(
            citation_id=1,
            decision=ScreeningDecision.EXCLUDE,
            reasoning="Does not meet criteria",
            model="test-model",
            reviewer_name="screener-1",
        )
        assert result.reviewer_name == "screener-1"

    def test_result_with_pdf_error(self) -> None:
        """Test result with PDF error."""
        result = ScreeningResult(
            citation_id=1,
            decision=ScreeningDecision.UNCERTAIN,
            reasoning="Could not process PDF",
            model="test-model",
            pdf_error="PDF not found",
        )
        assert result.pdf_error == "PDF not found"


class TestExtractionVariable:
    """Tests for ExtractionVariable model."""

    def test_default_type(self) -> None:
        """Test default type is string."""
        var = ExtractionVariable(name="test", description="Test variable")
        assert var.type == "string"

    def test_integer_type(self) -> None:
        """Test integer type."""
        var = ExtractionVariable(name="count", description="Count", type="integer")
        assert var.type == "integer"

    def test_options(self) -> None:
        """Test extraction variable with options."""
        var = ExtractionVariable(
            name="design",
            description="Study design",
            options=["RCT", "cohort", "case-control"],
        )
        assert var.options == ["RCT", "cohort", "case-control"]
        assert var.type == "string"

    def test_options_default_none(self) -> None:
        """Test options defaults to None."""
        var = ExtractionVariable(name="test", description="Test variable")
        assert var.options is None

    def test_boolean_type(self) -> None:
        """Test boolean type."""
        var = ExtractionVariable(name="blinded", description="Blinding", type="boolean")
        assert var.type == "boolean"

    def test_list_type(self) -> None:
        """Test list type."""
        var = ExtractionVariable(name="outcomes", description="Outcomes", type="list")
        assert var.type == "list"
