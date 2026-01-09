"""Full-text screening agent using Claude with PDF processing."""

import logging
from datetime import datetime

import anthropic

from automated_sr.config import get_config
from automated_sr.models import Citation, ReviewProtocol, ScreeningDecision, ScreeningResult
from automated_sr.pdf.processor import PDFError, PDFProcessor

logger = logging.getLogger(__name__)

FULLTEXT_SCREENING_PROMPT = """You are a systematic review screening assistant. Your task is to determine
whether this full-text article should be INCLUDED or EXCLUDED based on the review protocol.

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

## Instructions

1. Carefully read the full-text article provided
2. Evaluate whether it meets ALL inclusion criteria
3. Check if it meets ANY exclusion criteria
4. Consider the methods, population, intervention/exposure, and outcomes
5. Provide your reasoning step by step
6. Give your final decision: INCLUDE, EXCLUDE, or UNCERTAIN

Be thorough but decisive. If the article clearly does not meet inclusion criteria
or clearly meets exclusion criteria, EXCLUDE it.

Respond in the following format:

REASONING:
[Your step-by-step reasoning, referencing specific parts of the article]

DECISION: [INCLUDE/EXCLUDE/UNCERTAIN]"""

FULLTEXT_SCREENING_PROMPT_TEXT = """You are a systematic review screening assistant. Your task is to
determine whether this full-text article should be INCLUDED or EXCLUDED based on the review protocol.

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

## Full-Text Content

{content}

## Instructions

1. Carefully read the full-text article content above
2. Evaluate whether it meets ALL inclusion criteria
3. Check if it meets ANY exclusion criteria
4. Consider the methods, population, intervention/exposure, and outcomes
5. Provide your reasoning step by step
6. Give your final decision: INCLUDE, EXCLUDE, or UNCERTAIN

Be thorough but decisive. If the article clearly does not meet inclusion criteria
or clearly meets exclusion criteria, EXCLUDE it.

Respond in the following format:

REASONING:
[Your step-by-step reasoning, referencing specific parts of the article]

DECISION: [INCLUDE/EXCLUDE/UNCERTAIN]"""


class FullTextScreener:
    """Screens citations at the full-text level using Claude with PDF processing."""

    def __init__(self, protocol: ReviewProtocol, model: str | None = None) -> None:
        """
        Initialize the full-text screener.

        Args:
            protocol: The review protocol with objectives and criteria
            model: Claude model to use (defaults to protocol or config setting)
        """
        self.protocol = protocol
        raw_model = model or protocol.model or get_config().default_model
        # Strip provider prefix if present (e.g., "anthropic/claude-..." -> "claude-...")
        self.model = raw_model.split("/")[-1] if "/" in raw_model else raw_model
        self.pdf_processor = PDFProcessor()
        self._client: anthropic.Anthropic | None = None

    @property
    def client(self) -> anthropic.Anthropic:
        """Get the Anthropic client."""
        if self._client is None:
            config = get_config()
            if not config.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY environment variable is required")
            self._client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        return self._client

    def _format_criteria(self, criteria: list[str]) -> str:
        """Format criteria as a numbered list."""
        return "\n".join(f"{i + 1}. {c}" for i, c in enumerate(criteria))

    def _build_system_prompt(self, citation: Citation) -> str:
        """Build the system prompt with protocol and citation info."""
        return FULLTEXT_SCREENING_PROMPT.format(
            objective=self.protocol.objective,
            inclusion_criteria=self._format_criteria(self.protocol.inclusion_criteria),
            exclusion_criteria=self._format_criteria(self.protocol.exclusion_criteria),
            title=citation.title,
            authors=", ".join(citation.authors) if citation.authors else "Not specified",
            year=citation.year or "Not specified",
        )

    def _build_text_prompt(self, citation: Citation, content: str) -> str:
        """Build the prompt for text-based screening."""
        return FULLTEXT_SCREENING_PROMPT_TEXT.format(
            objective=self.protocol.objective,
            inclusion_criteria=self._format_criteria(self.protocol.inclusion_criteria),
            exclusion_criteria=self._format_criteria(self.protocol.exclusion_criteria),
            title=citation.title,
            authors=", ".join(citation.authors) if citation.authors else "Not specified",
            year=citation.year or "Not specified",
            content=content,
        )

    def _parse_response(self, response: str) -> tuple[ScreeningDecision, str]:
        """Parse the model response to extract decision and reasoning."""
        response_upper = response.upper()

        # Extract reasoning (everything before DECISION:)
        reasoning = response
        if "DECISION:" in response_upper:
            parts = response.split("DECISION:")
            reasoning = parts[0].strip()
            if reasoning.startswith("REASONING:"):
                reasoning = reasoning[10:].strip()

        # Determine decision
        if "DECISION: INCLUDE" in response_upper or "DECISION:INCLUDE" in response_upper:
            decision = ScreeningDecision.INCLUDE
        elif "DECISION: EXCLUDE" in response_upper or "DECISION:EXCLUDE" in response_upper:
            decision = ScreeningDecision.EXCLUDE
        elif "DECISION: UNCERTAIN" in response_upper or "DECISION:UNCERTAIN" in response_upper:
            decision = ScreeningDecision.UNCERTAIN
        else:
            logger.warning("Could not parse decision from response, defaulting to UNCERTAIN")
            decision = ScreeningDecision.UNCERTAIN

        return decision, reasoning

    def screen(self, citation: Citation) -> ScreeningResult:
        """
        Screen a single citation using its full-text PDF.

        Args:
            citation: The citation to screen (must have pdf_path set)

        Returns:
            ScreeningResult with the decision and reasoning
        """
        if citation.id is None:
            raise ValueError("Citation must have an ID")

        if not citation.pdf_path or not citation.pdf_path.exists():
            logger.warning("No PDF available for citation %d: %s", citation.id, citation.title[:50])
            return ScreeningResult(
                citation_id=citation.id,
                decision=ScreeningDecision.UNCERTAIN,
                reasoning="PDF not available for full-text screening",
                model=self.model,
                screened_at=datetime.now(),
                pdf_error="PDF not found",
            )

        logger.debug("Full-text screening citation %d: %s", citation.id, citation.title[:50])

        try:
            # Prepare PDF content
            content, content_type = self.pdf_processor.prepare_for_claude(citation.pdf_path)

            if content_type == "document":
                # Use Claude's document processing
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=2048,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "document",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "application/pdf",
                                        "data": content,
                                    },
                                },
                                {"type": "text", "text": self._build_system_prompt(citation)},
                            ],
                        }
                    ],
                )
            else:
                # Use text-based screening
                prompt = self._build_text_prompt(citation, content)
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )

            response_text = message.content[0].text  # type: ignore[union-attr]
            decision, reasoning = self._parse_response(response_text)

            logger.info("Citation %d full-text: %s", citation.id, decision.value)

            return ScreeningResult(
                citation_id=citation.id,
                decision=decision,
                reasoning=reasoning,
                model=self.model,
                screened_at=datetime.now(),
            )

        except PDFError as e:
            logger.warning("PDF error for citation %d: %s", citation.id, e)
            return ScreeningResult(
                citation_id=citation.id,
                decision=ScreeningDecision.UNCERTAIN,
                reasoning=f"PDF processing error: {e}",
                model=self.model,
                screened_at=datetime.now(),
                pdf_error=str(e),
            )

        except anthropic.APIError:
            logger.exception("API error screening citation %d", citation.id)
            return ScreeningResult(
                citation_id=citation.id,
                decision=ScreeningDecision.UNCERTAIN,
                reasoning="API error during screening - marked for manual review",
                model=self.model,
                screened_at=datetime.now(),
                pdf_error="API error",
            )

    def screen_batch(self, citations: list[Citation]) -> list[ScreeningResult]:
        """
        Screen multiple citations.

        Args:
            citations: List of citations to screen (each should have pdf_path set)

        Returns:
            List of ScreeningResults
        """
        results = []
        for citation in citations:
            result = self.screen(citation)
            results.append(result)
        return results
