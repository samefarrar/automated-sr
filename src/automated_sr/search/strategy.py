"""Search strategy generation using LLM."""

import json
import logging
from datetime import datetime

from automated_sr.config import get_config
from automated_sr.llm import LLMClient, create_client
from automated_sr.models import SearchStrategy, SearchSuggestionResult

logger = logging.getLogger(__name__)

DEFAULT_DATABASES = ["PubMed", "Scopus", "Web of Science", "OpenAlex"]

SEARCH_STRATEGY_PROMPT = """You are a systematic review search strategist expert.
Your task is to generate comprehensive, database-specific search strategies for finding relevant studies.

## Research Question

{question}

## Target Databases

Generate search strategies for: {databases}

## Instructions

1. **Decompose the question** into key concepts:
   - Population/Condition
   - Intervention/Exposure
   - Comparator (if applicable)
   - Outcome (if applicable)

2. **For each concept**, identify:
   - Primary terms
   - Synonyms and related terms
   - MeSH/controlled vocabulary terms (for PubMed)
   - Truncation/wildcards where appropriate (e.g., adolescen* for adolescent/adolescence)

3. **Generate {num_strategies} search strategies per database** with different trade-offs:
   - High Sensitivity: Broad, captures most relevant studies (more OR operators, broader terms)
   - Balanced: Moderate sensitivity and specificity
   - High Precision: Focused, fewer irrelevant results (more specific terms, MeSH focus)

4. **Use correct database syntax**:
   - **PubMed**: Use [MeSH Terms], [tiab] (title/abstract), [tw] (text word) field tags
     Example: `(depression[MeSH Terms] OR depressive disorder[tiab]) AND (adolescent[MeSH Terms] OR teen*[tiab])`
   - **Scopus**: Use TITLE-ABS-KEY() operator for title/abstract/keyword search
     Example: `TITLE-ABS-KEY(depression OR "depressive disorder") AND TITLE-ABS-KEY(adolescent* OR teen*)`
   - **Web of Science**: Use TS=() for topic search (title, abstract, keywords)
     Example: `TS=(depression OR "depressive disorder") AND TS=(adolescent* OR teen*)`
   - **OpenAlex**: Use simple keyword search with quotation marks for phrases
     Example: `"cognitive behavioral therapy" depression adolescent`

## Output Format

Respond with ONLY a JSON object (no markdown code blocks):
{{
  "concepts": {{
    "population": ["term1", "term2", "..."],
    "intervention": ["term1", "term2", "..."],
    "comparator": ["term1", "..."],
    "outcome": ["term1", "..."]
  }},
  "strategies": [
    {{
      "name": "High Sensitivity",
      "database": "PubMed",
      "search_string": "the actual search string with proper syntax",
      "concepts": ["population", "intervention"],
      "rationale": "Brief explanation of term choices and strategy approach",
      "estimated_sensitivity": "high",
      "estimated_specificity": "low"
    }},
    {{
      "name": "Balanced",
      "database": "PubMed",
      "search_string": "...",
      "concepts": ["population", "intervention", "outcome"],
      "rationale": "...",
      "estimated_sensitivity": "medium",
      "estimated_specificity": "medium"
    }}
  ]
}}

Generate strategies for each target database. Include at least one strategy per database."""


class SearchStrategyGenerator:
    """Generates search strategies for systematic reviews using LLM."""

    def __init__(self, model: str | None = None) -> None:
        """
        Initialize the search strategy generator.

        Args:
            model: Model to use (defaults to config setting)
        """
        self.model = model or get_config().default_model
        self._client: LLMClient | None = None

    @property
    def client(self) -> LLMClient:
        """Get the LLM client (lazy initialization)."""
        if self._client is None:
            self._client = create_client()
        return self._client

    def _build_prompt(
        self,
        question: str,
        databases: list[str],
        num_strategies: int,
    ) -> str:
        """Build the prompt for strategy generation."""
        return SEARCH_STRATEGY_PROMPT.format(
            question=question,
            databases=", ".join(databases),
            num_strategies=num_strategies,
        )

    def _parse_response(self, response: str) -> tuple[dict[str, list[str]], list[SearchStrategy]]:
        """
        Parse JSON response containing strategies.

        Returns:
            Tuple of (concept_breakdown, list of SearchStrategy objects)
        """
        response = response.strip()

        # Remove markdown code blocks if present
        if response.startswith("```json"):
            response = response[7:]
        elif response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]

        response = response.strip()

        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # Try to find JSON object in response
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    data = json.loads(response[start:end])
                except json.JSONDecodeError:
                    logger.warning("Could not parse JSON from response")
                    return {}, []
            else:
                logger.warning("No JSON found in response")
                return {}, []

        # Extract concepts
        concepts = data.get("concepts", {})

        # Extract strategies
        strategies = []
        for strategy_dict in data.get("strategies", []):
            try:
                strategies.append(SearchStrategy(**strategy_dict))
            except (TypeError, ValueError) as e:
                logger.warning("Could not parse strategy: %s", e)
                continue

        return concepts, strategies

    def generate(
        self,
        question: str,
        databases: list[str] | None = None,
        num_strategies: int = 2,
    ) -> SearchSuggestionResult:
        """
        Generate search strategies for a research question.

        Args:
            question: The research question
            databases: Target databases (defaults to all supported)
            num_strategies: Number of strategies per database (default 2: sensitive + precise)

        Returns:
            SearchSuggestionResult containing generated strategies
        """
        if databases is None:
            databases = DEFAULT_DATABASES

        # Normalize database names
        db_map = {
            "pubmed": "PubMed",
            "scopus": "Scopus",
            "wos": "Web of Science",
            "web of science": "Web of Science",
            "webofscience": "Web of Science",
            "openalex": "OpenAlex",
        }
        databases = [db_map.get(db.lower(), db) for db in databases]

        prompt = self._build_prompt(question, databases, num_strategies)

        logger.debug("Generating search strategies for question: %s", question[:100])

        try:
            response_text = self.client.complete(
                prompt=prompt,
                model=self.model,
                max_tokens=8192,
                temperature=0.3,  # Some creativity for synonym generation
            )

            concepts, strategies = self._parse_response(response_text)

            logger.info("Generated %d search strategies", len(strategies))

            return SearchSuggestionResult(
                question=question,
                concept_breakdown=concepts,
                strategies=strategies,
                model=self.model,
                generated_at=datetime.now(),
            )

        except Exception:
            logger.exception("Error generating search strategies")
            return SearchSuggestionResult(
                question=question,
                concept_breakdown={},
                strategies=[],
                model=self.model,
                generated_at=datetime.now(),
            )
