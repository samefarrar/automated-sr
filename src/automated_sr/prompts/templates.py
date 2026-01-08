"""Built-in prompt templates for systematic review screening.

Templates are designed following best practices from the otto-SR paper and
systematic review methodology. Each template has a specific focus:

- rigorous: Strict adherence to criteria (balanced sensitivity/specificity)
- sensitive: Prioritizes recall, leans towards inclusion when uncertain
- specific: Prioritizes precision, leans towards exclusion when uncertain
"""

from enum import Enum


class PromptTemplate(str, Enum):
    """Built-in prompt template identifiers."""

    RIGOROUS = "rigorous"
    SENSITIVE = "sensitive"
    SPECIFIC = "specific"
    CUSTOM = "custom"


# Otto-SR style rigorous prompt - balanced approach
RIGOROUS_ABSTRACT_TEMPLATE = """You are a researcher rigorously screening titles and abstracts of scientific papers \
for inclusion or exclusion in a systematic review. Use the criteria below to inform your decision.

**Decision Rule**: If ANY exclusion criterion is met OR if NOT ALL inclusion criteria are met, EXCLUDE the article. \
If ALL inclusion criteria are met AND NO exclusion criteria are met, INCLUDE the article.

## Review Protocol

### Objective
{objective}

### Inclusion Criteria (ALL must be met)
{inclusion_criteria}

### Exclusion Criteria (ANY triggers exclusion)
{exclusion_criteria}

## Citation to Screen

**Title:** {title}
**Authors:** {authors}
**Year:** {year}
**Journal:** {journal}
**Abstract:** {abstract}

## Instructions

1. Carefully read the title and abstract
2. Evaluate EACH inclusion criterion - the article must meet ALL of them
3. Check EACH exclusion criterion - ANY match means the article should be EXCLUDED
4. Consider the study population, intervention/exposure, comparator, and outcomes (PICO/PECO)
5. Provide step-by-step reasoning for your evaluation
6. Give your final decision: INCLUDE, EXCLUDE, or UNCERTAIN

If the abstract provides insufficient information to determine eligibility with confidence, \
mark as UNCERTAIN for human review.

REASONING:
[Provide your systematic step-by-step evaluation here]

DECISION: [INCLUDE/EXCLUDE/UNCERTAIN]"""


# High-sensitivity prompt - prioritizes recall
SENSITIVE_ABSTRACT_TEMPLATE = """You are a researcher screening titles and abstracts of scientific papers \
for a systematic review. Your goal is to MAXIMIZE SENSITIVITY - it is better to include a paper that \
turns out to be irrelevant than to miss a potentially relevant paper.

**Decision Rule**: When in doubt, INCLUDE. Only EXCLUDE when you are CERTAIN the article does not meet \
the criteria. If there is ANY possibility the article could be relevant, INCLUDE it.

## Review Protocol

### Objective
{objective}

### Inclusion Criteria
{inclusion_criteria}

### Exclusion Criteria
{exclusion_criteria}

## Citation to Screen

**Title:** {title}
**Authors:** {authors}
**Year:** {year}
**Journal:** {journal}
**Abstract:** {abstract}

## Instructions

1. Read the title and abstract carefully
2. Look for ANY indication that this paper MIGHT be relevant
3. Only exclude if you are CERTAIN the paper cannot possibly meet the criteria
4. When information is missing or unclear, lean towards INCLUDE
5. Provide brief reasoning for your decision
6. Give your final decision: INCLUDE, EXCLUDE, or UNCERTAIN

Remember: False negatives (missing relevant papers) are worse than false positives (including irrelevant papers).

REASONING:
[Provide your evaluation here]

DECISION: [INCLUDE/EXCLUDE/UNCERTAIN]"""


# High-specificity prompt - prioritizes precision
SPECIFIC_ABSTRACT_TEMPLATE = """You are a researcher screening titles and abstracts of scientific papers \
for a systematic review. Your goal is to MAXIMIZE SPECIFICITY - only include papers that clearly and \
definitively meet ALL inclusion criteria.

**Decision Rule**: When in doubt, EXCLUDE. Only INCLUDE when you are CERTAIN the article meets ALL \
inclusion criteria and violates NO exclusion criteria. If there is insufficient information, EXCLUDE.

## Review Protocol

### Objective
{objective}

### Inclusion Criteria (ALL must be definitively met)
{inclusion_criteria}

### Exclusion Criteria (ANY triggers exclusion)
{exclusion_criteria}

## Citation to Screen

**Title:** {title}
**Authors:** {authors}
**Year:** {year}
**Journal:** {journal}
**Abstract:** {abstract}

## Instructions

1. Read the title and abstract carefully
2. Verify that EACH inclusion criterion is EXPLICITLY met
3. Check for ANY indication of exclusion criteria
4. If information is missing or unclear, lean towards EXCLUDE
5. Provide detailed reasoning for your decision
6. Give your final decision: INCLUDE, EXCLUDE, or UNCERTAIN

Remember: False positives (including irrelevant papers) waste review resources. Be strict.

REASONING:
[Provide your detailed evaluation here]

DECISION: [INCLUDE/EXCLUDE/UNCERTAIN]"""


# Full-text screening templates (similar structure but for PDFs)
RIGOROUS_FULLTEXT_TEMPLATE = """You are a researcher rigorously screening full-text articles for inclusion \
or exclusion in a systematic review. You have access to the complete article content.

**Decision Rule**: If ANY exclusion criterion is met OR if NOT ALL inclusion criteria are met, EXCLUDE. \
If ALL inclusion criteria are met AND NO exclusion criteria are met, INCLUDE.

## Review Protocol

### Objective
{objective}

### Inclusion Criteria (ALL must be met)
{inclusion_criteria}

### Exclusion Criteria (ANY triggers exclusion)
{exclusion_criteria}

## Article Information

**Title:** {title}
**Authors:** {authors}
**Year:** {year}
**Journal:** {journal}

## Instructions

1. Review the full text of the article
2. Verify that ALL inclusion criteria are met by examining methods, results, and discussion
3. Check for ANY exclusion criteria throughout the article
4. Pay attention to study design, population, intervention, comparators, and outcomes
5. Provide detailed reasoning with specific references to the article content
6. Give your final decision: INCLUDE, EXCLUDE, or UNCERTAIN

REASONING:
[Provide your systematic evaluation with references to specific sections of the article]

DECISION: [INCLUDE/EXCLUDE/UNCERTAIN]"""


SENSITIVE_FULLTEXT_TEMPLATE = """You are a researcher screening full-text articles for a systematic review. \
Your goal is to MAXIMIZE SENSITIVITY - only exclude papers you are CERTAIN do not meet the criteria.

**Decision Rule**: When in doubt, INCLUDE. Only EXCLUDE when you have clear evidence from the full text \
that the article does not meet the criteria.

## Review Protocol

### Objective
{objective}

### Inclusion Criteria
{inclusion_criteria}

### Exclusion Criteria
{exclusion_criteria}

## Article Information

**Title:** {title}
**Authors:** {authors}
**Year:** {year}
**Journal:** {journal}

## Instructions

1. Review the full text of the article
2. Look for evidence that the article meets the inclusion criteria
3. Only exclude if there is clear evidence the article fails to meet criteria
4. Provide reasoning for your decision
5. Give your final decision: INCLUDE, EXCLUDE, or UNCERTAIN

REASONING:
[Provide your evaluation here]

DECISION: [INCLUDE/EXCLUDE/UNCERTAIN]"""


SPECIFIC_FULLTEXT_TEMPLATE = """You are a researcher screening full-text articles for a systematic review. \
Your goal is to MAXIMIZE SPECIFICITY - only include papers that definitively meet ALL criteria.

**Decision Rule**: When in doubt, EXCLUDE. Only INCLUDE when the full text provides clear evidence \
that ALL inclusion criteria are met and NO exclusion criteria apply.

## Review Protocol

### Objective
{objective}

### Inclusion Criteria (ALL must be definitively met)
{inclusion_criteria}

### Exclusion Criteria (ANY triggers exclusion)
{exclusion_criteria}

## Article Information

**Title:** {title}
**Authors:** {authors}
**Year:** {year}
**Journal:** {journal}

## Instructions

1. Review the full text of the article
2. Verify that EACH inclusion criterion is EXPLICITLY met with evidence from the text
3. Check thoroughly for ANY exclusion criteria
4. Provide detailed reasoning with specific quotes or references
5. Give your final decision: INCLUDE, EXCLUDE, or UNCERTAIN

REASONING:
[Provide your detailed evaluation with specific references]

DECISION: [INCLUDE/EXCLUDE/UNCERTAIN]"""


# Template lookup dictionaries
ABSTRACT_TEMPLATES: dict[PromptTemplate, str] = {
    PromptTemplate.RIGOROUS: RIGOROUS_ABSTRACT_TEMPLATE,
    PromptTemplate.SENSITIVE: SENSITIVE_ABSTRACT_TEMPLATE,
    PromptTemplate.SPECIFIC: SPECIFIC_ABSTRACT_TEMPLATE,
}

FULLTEXT_TEMPLATES: dict[PromptTemplate, str] = {
    PromptTemplate.RIGOROUS: RIGOROUS_FULLTEXT_TEMPLATE,
    PromptTemplate.SENSITIVE: SENSITIVE_FULLTEXT_TEMPLATE,
    PromptTemplate.SPECIFIC: SPECIFIC_FULLTEXT_TEMPLATE,
}


def get_abstract_template(template: PromptTemplate | str) -> str:
    """
    Get the abstract screening template.

    Args:
        template: Template identifier (PromptTemplate enum or string)

    Returns:
        The prompt template string

    Raises:
        ValueError: If template is not found
    """
    if isinstance(template, str):
        template = PromptTemplate(template.lower())

    if template == PromptTemplate.CUSTOM:
        raise ValueError("Custom template requires providing the prompt text directly")

    if template not in ABSTRACT_TEMPLATES:
        raise ValueError(f"Unknown abstract template: {template}")

    return ABSTRACT_TEMPLATES[template]


def get_fulltext_template(template: PromptTemplate | str) -> str:
    """
    Get the full-text screening template.

    Args:
        template: Template identifier (PromptTemplate enum or string)

    Returns:
        The prompt template string

    Raises:
        ValueError: If template is not found
    """
    if isinstance(template, str):
        template = PromptTemplate(template.lower())

    if template == PromptTemplate.CUSTOM:
        raise ValueError("Custom template requires providing the prompt text directly")

    if template not in FULLTEXT_TEMPLATES:
        raise ValueError(f"Unknown fulltext template: {template}")

    return FULLTEXT_TEMPLATES[template]


def format_criteria(criteria: list[str]) -> str:
    """Format a list of criteria as a numbered list."""
    return "\n".join(f"{i + 1}. {criterion}" for i, criterion in enumerate(criteria))
