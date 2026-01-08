"""Prompt templates for systematic review screening."""

from automated_sr.prompts.templates import (
    ABSTRACT_TEMPLATES,
    FULLTEXT_TEMPLATES,
    PromptTemplate,
    format_criteria,
    get_abstract_template,
    get_fulltext_template,
)

__all__ = [
    "PromptTemplate",
    "ABSTRACT_TEMPLATES",
    "FULLTEXT_TEMPLATES",
    "get_abstract_template",
    "get_fulltext_template",
    "format_criteria",
]
