"""Abstract screening agent using Claude."""

import logging
from datetime import datetime

import anthropic

from automated_sr.config import get_config
from automated_sr.models import Citation, ReviewProtocol, ScreeningDecision, ScreeningResult

logger = logging.getLogger(__name__)

ABSTRACT_SCREENING_PROMPT = """You are a systematic review screening assistant. Your task is to determine whether
a citation should be INCLUDED or EXCLUDED based on the review protocol.

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

**Abstract:**
{abstract}

## Instructions

1. Carefully read the citation information above
2. Compare it against the inclusion and exclusion criteria
3. Provide your reasoning step by step
4. Give your final decision: INCLUDE, EXCLUDE, or UNCERTAIN

If the abstract is missing or insufficient to make a determination, lean towards INCLUDE
to avoid missing potentially relevant studies (high sensitivity approach).

Respond in the following format:

REASONING:
[Your step-by-step reasoning here]

DECISION: [INCLUDE/EXCLUDE/UNCERTAIN]"""


class AbstractScreener:
    """Screens citations at the abstract level using Claude."""

    def __init__(self, protocol: ReviewProtocol, model: str | None = None) -> None:
        """
        Initialize the abstract screener.

        Args:
            protocol: The review protocol with objectives and criteria
            model: Claude model to use (defaults to protocol or config setting)
        """
        self.protocol = protocol
        raw_model = model or protocol.model or get_config().default_model
        # Strip provider prefix if present (e.g., "anthropic/claude-..." -> "claude-...")
        self.model = raw_model.split("/")[-1] if "/" in raw_model else raw_model
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

    def _build_prompt(self, citation: Citation) -> str:
        """Build the screening prompt for a citation."""
        return ABSTRACT_SCREENING_PROMPT.format(
            objective=self.protocol.objective,
            inclusion_criteria=self._format_criteria(self.protocol.inclusion_criteria),
            exclusion_criteria=self._format_criteria(self.protocol.exclusion_criteria),
            title=citation.title,
            authors=", ".join(citation.authors) if citation.authors else "Not specified",
            year=citation.year or "Not specified",
            journal=citation.journal or "Not specified",
            abstract=citation.abstract or "Abstract not available",
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
            # Default to uncertain if we can't parse the decision
            logger.warning("Could not parse decision from response, defaulting to UNCERTAIN")
            decision = ScreeningDecision.UNCERTAIN

        return decision, reasoning

    def screen(self, citation: Citation) -> ScreeningResult:
        """
        Screen a single citation.

        Args:
            citation: The citation to screen

        Returns:
            ScreeningResult with the decision and reasoning
        """
        if citation.id is None:
            raise ValueError("Citation must have an ID")

        prompt = self._build_prompt(citation)

        logger.debug("Screening citation %d: %s", citation.id, citation.title[:50])

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = message.content[0].text  # type: ignore[union-attr]
            decision, reasoning = self._parse_response(response_text)

            logger.info("Citation %d: %s", citation.id, decision.value)

            return ScreeningResult(
                citation_id=citation.id,
                decision=decision,
                reasoning=reasoning,
                model=self.model,
                screened_at=datetime.now(),
            )

        except anthropic.APIError:
            logger.exception("API error screening citation %d", citation.id)
            # Return uncertain on API errors so we don't lose the citation
            return ScreeningResult(
                citation_id=citation.id,
                decision=ScreeningDecision.UNCERTAIN,
                reasoning="API error during screening - marked for manual review",
                model=self.model,
                screened_at=datetime.now(),
            )

    def screen_batch(self, citations: list[Citation]) -> list[ScreeningResult]:
        """
        Screen multiple citations.

        Args:
            citations: List of citations to screen

        Returns:
            List of ScreeningResults
        """
        results = []
        for citation in citations:
            result = self.screen(citation)
            results.append(result)
        return results
