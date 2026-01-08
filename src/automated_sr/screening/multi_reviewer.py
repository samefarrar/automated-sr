"""Multi-reviewer screening with automatic conflict resolution."""

import logging
from datetime import datetime

from automated_sr.llm import LLMClient, create_client
from automated_sr.models import (
    APIProvider,
    Citation,
    MultiReviewerScreeningResult,
    ReviewerConfig,
    ReviewProtocol,
    ScreeningDecision,
    ScreeningResult,
)
from automated_sr.prompts import format_criteria, get_abstract_template, get_fulltext_template

logger = logging.getLogger(__name__)


class MultiReviewerScreener:
    """Orchestrates multiple reviewers with automatic tiebreaker for conflicts."""

    def __init__(
        self,
        protocol: ReviewProtocol,
        stage: str = "abstract",  # "abstract" or "fulltext"
    ) -> None:
        """
        Initialize the multi-reviewer screener.

        Args:
            protocol: Review protocol with reviewers configuration
            stage: Screening stage ("abstract" or "fulltext")
        """
        self.protocol = protocol
        self.stage = stage
        self._clients: dict[str, LLMClient] = {}

    def _get_client(self, reviewer: ReviewerConfig) -> LLMClient:
        """Get or create an LLM client for a reviewer."""
        if reviewer.name not in self._clients:
            self._clients[reviewer.name] = create_client(reviewer.api)
        return self._clients[reviewer.name]

    def _get_template(self, reviewer: ReviewerConfig) -> str:
        """Get the prompt template for a reviewer."""
        if reviewer.custom_prompt:
            return reviewer.custom_prompt

        if self.stage == "abstract":
            return get_abstract_template(reviewer.prompt_template)
        else:
            return get_fulltext_template(reviewer.prompt_template)

    def _build_prompt(self, citation: Citation, template: str) -> str:
        """Build the prompt for screening a citation."""
        return template.format(
            objective=self.protocol.objective,
            inclusion_criteria=format_criteria(self.protocol.inclusion_criteria),
            exclusion_criteria=format_criteria(self.protocol.exclusion_criteria),
            title=citation.title,
            authors=", ".join(citation.authors) if citation.authors else "Not specified",
            year=citation.year or "Not specified",
            journal=citation.journal or "Not specified",
            abstract=citation.abstract or "Abstract not available",
        )

    def _parse_decision(self, response: str) -> tuple[ScreeningDecision, str]:
        """Parse the decision and reasoning from model response."""
        response_upper = response.upper()
        reasoning = response

        # Extract reasoning if present
        if "REASONING:" in response_upper:
            reasoning_start = response_upper.find("REASONING:")
            decision_start = response_upper.find("DECISION:")
            if decision_start > reasoning_start:
                reasoning = response[reasoning_start + 10 : decision_start].strip()

        # Determine decision
        if "DECISION:" in response_upper:
            decision_part = response_upper.split("DECISION:")[-1].strip()
            if decision_part.startswith("INCLUDE"):
                return ScreeningDecision.INCLUDE, reasoning
            elif decision_part.startswith("EXCLUDE"):
                return ScreeningDecision.EXCLUDE, reasoning
            else:
                return ScreeningDecision.UNCERTAIN, reasoning

        # Fallback: look for keywords
        if "INCLUDE" in response_upper and "EXCLUDE" not in response_upper:
            return ScreeningDecision.INCLUDE, reasoning
        elif "EXCLUDE" in response_upper:
            return ScreeningDecision.EXCLUDE, reasoning
        else:
            return ScreeningDecision.UNCERTAIN, reasoning

    def _screen_with_reviewer(
        self,
        citation: Citation,
        reviewer: ReviewerConfig,
    ) -> ScreeningResult:
        """Screen a citation with a single reviewer."""
        client = self._get_client(reviewer)
        template = self._get_template(reviewer)
        prompt = self._build_prompt(citation, template)

        try:
            response = client.complete(
                prompt=prompt,
                model=reviewer.model,
                max_tokens=1024,
            )
            decision, reasoning = self._parse_decision(response)

            return ScreeningResult(
                citation_id=citation.id or 0,
                decision=decision,
                reasoning=reasoning,
                model=reviewer.model,
                reviewer_name=reviewer.name,
                screened_at=datetime.now(),
            )

        except Exception as e:
            logger.exception("Error screening with reviewer %s", reviewer.name)
            return ScreeningResult(
                citation_id=citation.id or 0,
                decision=ScreeningDecision.UNCERTAIN,
                reasoning=f"Error during screening: {e}",
                model=reviewer.model,
                reviewer_name=reviewer.name,
                screened_at=datetime.now(),
            )

    def screen(self, citation: Citation) -> MultiReviewerScreeningResult:
        """
        Screen a citation with all configured reviewers.

        If primary reviewers disagree, automatically runs the tiebreaker.

        Args:
            citation: Citation to screen

        Returns:
            MultiReviewerScreeningResult with all reviewer decisions and consensus
        """
        primary_reviewers = self.protocol.get_primary_reviewers()
        tiebreaker = self.protocol.get_tiebreaker()

        if not primary_reviewers:
            raise ValueError("No primary reviewers configured in protocol")

        # Screen with all primary reviewers
        results: list[ScreeningResult] = []
        for reviewer in primary_reviewers:
            logger.info("Screening citation %d with reviewer %s", citation.id or 0, reviewer.name)
            result = self._screen_with_reviewer(citation, reviewer)
            results.append(result)

        # Check for consensus
        decisions = [r.decision for r in results]
        unique_decisions = set(decisions)

        if len(unique_decisions) == 1:
            # All reviewers agree
            return MultiReviewerScreeningResult(
                citation_id=citation.id or 0,
                reviewer_results=results,
                consensus_decision=decisions[0],
                required_tiebreaker=False,
                screened_at=datetime.now(),
            )

        # Disagreement - need tiebreaker
        logger.info(
            "Citation %d: Reviewers disagree (%s). Running tiebreaker.",
            citation.id or 0,
            ", ".join(d.value for d in decisions),
        )

        if tiebreaker:
            tiebreaker_result = self._screen_with_reviewer(citation, tiebreaker)
            return MultiReviewerScreeningResult(
                citation_id=citation.id or 0,
                reviewer_results=results,
                consensus_decision=tiebreaker_result.decision,
                required_tiebreaker=True,
                tiebreaker_result=tiebreaker_result,
                screened_at=datetime.now(),
            )
        else:
            # No tiebreaker configured - mark as uncertain
            logger.warning("Citation %d: No tiebreaker configured, marking as uncertain", citation.id or 0)
            return MultiReviewerScreeningResult(
                citation_id=citation.id or 0,
                reviewer_results=results,
                consensus_decision=ScreeningDecision.UNCERTAIN,
                required_tiebreaker=True,
                screened_at=datetime.now(),
            )


def create_default_reviewers(
    primary_model: str = "claude-haiku-4-5-20251015",
    tiebreaker_model: str = "claude-sonnet-4-5-20250929",
) -> list[ReviewerConfig]:
    """
    Create a default set of reviewers for multi-reviewer screening.

    Uses Haiku for fast/cheap primary screening and Sonnet as tiebreaker.

    Args:
        primary_model: Model for primary reviewers (default: Haiku)
        tiebreaker_model: Model for tiebreaker (default: Sonnet)

    Returns:
        List of ReviewerConfig objects
    """
    return [
        ReviewerConfig(
            name="screener-1",
            model=primary_model,
            api=APIProvider.ANTHROPIC,
            prompt_template="rigorous",
            role="primary",
        ),
        ReviewerConfig(
            name="screener-2",
            model=primary_model,
            api=APIProvider.ANTHROPIC,
            prompt_template="sensitive",  # Different template for diversity
            role="primary",
        ),
        ReviewerConfig(
            name="tiebreaker",
            model=tiebreaker_model,
            api=APIProvider.ANTHROPIC,
            prompt_template="rigorous",
            role="tiebreaker",
        ),
    ]
