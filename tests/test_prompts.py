"""Tests for prompt templates."""

import pytest

from automated_sr.prompts.templates import (
    ABSTRACT_TEMPLATES,
    FULLTEXT_TEMPLATES,
    PromptTemplate,
    format_criteria,
    get_abstract_template,
    get_fulltext_template,
)


class TestPromptTemplate:
    """Tests for PromptTemplate enum."""

    def test_template_values(self) -> None:
        """Test template enum values."""
        assert PromptTemplate.RIGOROUS.value == "rigorous"
        assert PromptTemplate.SENSITIVE.value == "sensitive"
        assert PromptTemplate.SPECIFIC.value == "specific"
        assert PromptTemplate.CUSTOM.value == "custom"


class TestGetAbstractTemplate:
    """Tests for get_abstract_template function."""

    def test_get_rigorous_template(self) -> None:
        """Test getting rigorous template."""
        template = get_abstract_template(PromptTemplate.RIGOROUS)
        assert "{objective}" in template
        assert "{inclusion_criteria}" in template
        assert "{exclusion_criteria}" in template
        assert "INCLUDE" in template
        assert "EXCLUDE" in template

    def test_get_sensitive_template(self) -> None:
        """Test getting sensitive template."""
        template = get_abstract_template(PromptTemplate.SENSITIVE)
        assert "MAXIMIZE SENSITIVITY" in template
        assert "When in doubt, INCLUDE" in template

    def test_get_specific_template(self) -> None:
        """Test getting specific template."""
        template = get_abstract_template(PromptTemplate.SPECIFIC)
        assert "MAXIMIZE SPECIFICITY" in template
        assert "When in doubt, EXCLUDE" in template

    def test_get_template_by_string(self) -> None:
        """Test getting template using string."""
        template = get_abstract_template("rigorous")
        assert template == ABSTRACT_TEMPLATES[PromptTemplate.RIGOROUS]

    def test_get_template_case_insensitive(self) -> None:
        """Test that string lookup is case insensitive."""
        template1 = get_abstract_template("RIGOROUS")
        template2 = get_abstract_template("Rigorous")
        template3 = get_abstract_template("rigorous")
        assert template1 == template2 == template3

    def test_custom_template_raises(self) -> None:
        """Test that custom template raises error."""
        with pytest.raises(ValueError, match="Custom template"):
            get_abstract_template(PromptTemplate.CUSTOM)

    def test_unknown_template_raises(self) -> None:
        """Test that unknown template string raises error."""
        with pytest.raises(ValueError):
            get_abstract_template("nonexistent")


class TestGetFulltextTemplate:
    """Tests for get_fulltext_template function."""

    def test_get_rigorous_fulltext(self) -> None:
        """Test getting rigorous fulltext template."""
        template = get_fulltext_template(PromptTemplate.RIGOROUS)
        assert "full-text" in template.lower() or "full text" in template.lower()
        assert "{objective}" in template

    def test_get_sensitive_fulltext(self) -> None:
        """Test getting sensitive fulltext template."""
        template = get_fulltext_template(PromptTemplate.SENSITIVE)
        assert "SENSITIVITY" in template

    def test_get_specific_fulltext(self) -> None:
        """Test getting specific fulltext template."""
        template = get_fulltext_template(PromptTemplate.SPECIFIC)
        assert "SPECIFICITY" in template

    def test_get_fulltext_by_string(self) -> None:
        """Test getting fulltext template using string."""
        template = get_fulltext_template("rigorous")
        assert template == FULLTEXT_TEMPLATES[PromptTemplate.RIGOROUS]


class TestFormatCriteria:
    """Tests for format_criteria function."""

    def test_format_single_criterion(self) -> None:
        """Test formatting single criterion."""
        result = format_criteria(["First criterion"])
        assert result == "1. First criterion"

    def test_format_multiple_criteria(self) -> None:
        """Test formatting multiple criteria."""
        criteria = ["First criterion", "Second criterion", "Third criterion"]
        result = format_criteria(criteria)
        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[0] == "1. First criterion"
        assert lines[1] == "2. Second criterion"
        assert lines[2] == "3. Third criterion"

    def test_format_empty_list(self) -> None:
        """Test formatting empty list."""
        result = format_criteria([])
        assert result == ""


class TestTemplateVariables:
    """Tests for template variable placeholders."""

    def test_abstract_templates_have_required_variables(self) -> None:
        """Test that all abstract templates have required placeholders."""
        required_vars = [
            "{objective}",
            "{inclusion_criteria}",
            "{exclusion_criteria}",
            "{title}",
            "{authors}",
            "{year}",
            "{abstract}",
        ]

        for template_type, template in ABSTRACT_TEMPLATES.items():
            for var in required_vars:
                assert var in template, f"Template {template_type} missing {var}"

    def test_fulltext_templates_have_required_variables(self) -> None:
        """Test that all fulltext templates have required placeholders."""
        required_vars = [
            "{objective}",
            "{inclusion_criteria}",
            "{exclusion_criteria}",
            "{title}",
            "{authors}",
            "{year}",
        ]

        for template_type, template in FULLTEXT_TEMPLATES.items():
            for var in required_vars:
                assert var in template, f"Template {template_type} missing {var}"

    def test_templates_have_decision_instruction(self) -> None:
        """Test that all templates include decision instruction."""
        all_templates = list(ABSTRACT_TEMPLATES.values()) + list(FULLTEXT_TEMPLATES.values())

        for template in all_templates:
            assert "DECISION:" in template
            assert "REASONING:" in template
