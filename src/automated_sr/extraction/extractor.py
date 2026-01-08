"""Data extraction agent using Claude."""

import json
import logging
from datetime import datetime
from typing import Any

import anthropic

from automated_sr.config import get_config
from automated_sr.models import Citation, ExtractionResult, ExtractionVariable, ReviewProtocol
from automated_sr.pdf.processor import PDFError, PDFProcessor

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are a systematic review data extraction assistant.
Your task is to extract specific data from a full-text article.

## Article Information

**Title:** {title}
**Authors:** {authors}
**Year:** {year}

## Variables to Extract

{variables}

## Instructions

1. Carefully read the article
2. Extract each variable listed above
3. If a value is not reported or cannot be determined, use null
4. For numeric values, extract the number only (no units in the value)
5. Be precise and accurate - only extract what is explicitly stated

Respond with a JSON object containing the extracted values. Use the exact variable names provided.

Example format:
```json
{{
  "variable_name_1": "extracted value",
  "variable_name_2": 123,
  "variable_name_3": null
}}
```

IMPORTANT: Respond ONLY with the JSON object, no additional text."""

EXTRACTION_PROMPT_TEXT = """You are a systematic review data extraction assistant.
Your task is to extract specific data from a full-text article.

## Article Information

**Title:** {title}
**Authors:** {authors}
**Year:** {year}

## Full-Text Content

{content}

## Variables to Extract

{variables}

## Instructions

1. Carefully read the article content above
2. Extract each variable listed above
3. If a value is not reported or cannot be determined, use null
4. For numeric values, extract the number only (no units in the value)
5. Be precise and accurate - only extract what is explicitly stated

Respond with a JSON object containing the extracted values. Use the exact variable names provided.

Example format:
```json
{{
  "variable_name_1": "extracted value",
  "variable_name_2": 123,
  "variable_name_3": null
}}
```

IMPORTANT: Respond ONLY with the JSON object, no additional text."""


class DataExtractor:
    """Extracts structured data from articles using Claude."""

    def __init__(self, protocol: ReviewProtocol, model: str | None = None) -> None:
        """
        Initialize the data extractor.

        Args:
            protocol: The review protocol with extraction variables
            model: Claude model to use (defaults to protocol or config setting)
        """
        self.protocol = protocol
        self.model = model or protocol.model or get_config().default_model
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

    def _format_variables(self, variables: list[ExtractionVariable]) -> str:
        """Format extraction variables for the prompt."""
        lines = []
        for var in variables:
            type_hint = f" (type: {var.type})" if var.type != "string" else ""
            lines.append(f"- **{var.name}**{type_hint}: {var.description}")
        return "\n".join(lines)

    def _parse_json_response(self, response: str) -> dict[str, Any]:
        """Parse JSON from the model response."""
        # Try to find JSON in the response
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
            return json.loads(response)
        except json.JSONDecodeError:
            # Try to find JSON object in the response
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(response[start:end])
                except json.JSONDecodeError:
                    pass

            logger.warning("Could not parse JSON from response")
            return {}

    def _coerce_types(self, data: dict[str, Any]) -> dict[str, Any]:
        """Coerce extracted values to expected types based on variable definitions."""
        result = {}

        var_types = {var.name: var.type for var in self.protocol.extraction_variables}

        for key, value in data.items():
            if value is None:
                result[key] = None
                continue

            expected_type = var_types.get(key, "string")

            if expected_type == "integer":
                try:
                    # Handle strings like "123" or "123 patients"
                    if isinstance(value, str):
                        # Extract first number
                        import re

                        match = re.search(r"-?\d+", value)
                        if match:
                            result[key] = int(match.group())
                        else:
                            result[key] = None
                    else:
                        result[key] = int(value)
                except (ValueError, TypeError):
                    result[key] = None

            elif expected_type == "float":
                try:
                    if isinstance(value, str):
                        import re

                        match = re.search(r"-?\d+\.?\d*", value)
                        if match:
                            result[key] = float(match.group())
                        else:
                            result[key] = None
                    else:
                        result[key] = float(value)
                except (ValueError, TypeError):
                    result[key] = None

            elif expected_type == "boolean":
                if isinstance(value, bool):
                    result[key] = value
                elif isinstance(value, str):
                    result[key] = value.lower() in ("true", "yes", "1")
                else:
                    result[key] = bool(value)

            elif expected_type == "list":
                if isinstance(value, list):
                    result[key] = value
                elif isinstance(value, str):
                    # Try to split by common delimiters
                    result[key] = [v.strip() for v in value.split(",") if v.strip()]
                else:
                    result[key] = [value]

            else:  # string or unknown
                result[key] = str(value) if value is not None else None

        return result

    def extract(self, citation: Citation) -> ExtractionResult:
        """
        Extract data from a citation's full-text PDF.

        Args:
            citation: The citation to extract data from (must have pdf_path set)

        Returns:
            ExtractionResult with the extracted data
        """
        if citation.id is None:
            raise ValueError("Citation must have an ID")

        if not self.protocol.extraction_variables:
            logger.warning("No extraction variables defined in protocol")
            return ExtractionResult(
                citation_id=citation.id,
                extracted_data={},
                model=self.model,
                extracted_at=datetime.now(),
            )

        if not citation.pdf_path or not citation.pdf_path.exists():
            logger.warning("No PDF available for citation %d: %s", citation.id, citation.title[:50])
            # Return empty extraction with null values
            return ExtractionResult(
                citation_id=citation.id,
                extracted_data={var.name: None for var in self.protocol.extraction_variables},
                model=self.model,
                extracted_at=datetime.now(),
            )

        logger.debug("Extracting data from citation %d: %s", citation.id, citation.title[:50])

        try:
            # Prepare PDF content
            content, content_type = self.pdf_processor.prepare_for_claude(citation.pdf_path)
            variables_text = self._format_variables(self.protocol.extraction_variables)

            if content_type == "document":
                # Use Claude's document processing
                prompt = EXTRACTION_PROMPT.format(
                    title=citation.title,
                    authors=", ".join(citation.authors) if citation.authors else "Not specified",
                    year=citation.year or "Not specified",
                    variables=variables_text,
                )
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
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
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ],
                )
            else:
                # Use text-based extraction
                prompt = EXTRACTION_PROMPT_TEXT.format(
                    title=citation.title,
                    authors=", ".join(citation.authors) if citation.authors else "Not specified",
                    year=citation.year or "Not specified",
                    content=content,
                    variables=variables_text,
                )
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                )

            response_text = message.content[0].text  # type: ignore[union-attr]
            extracted_data = self._parse_json_response(response_text)
            extracted_data = self._coerce_types(extracted_data)

            logger.info("Extracted %d variables from citation %d", len(extracted_data), citation.id)

            return ExtractionResult(
                citation_id=citation.id,
                extracted_data=extracted_data,
                model=self.model,
                extracted_at=datetime.now(),
            )

        except PDFError as e:
            logger.warning("PDF error for citation %d: %s", citation.id, e)
            return ExtractionResult(
                citation_id=citation.id,
                extracted_data={var.name: None for var in self.protocol.extraction_variables},
                model=self.model,
                extracted_at=datetime.now(),
            )

        except anthropic.APIError:
            logger.exception("API error extracting from citation %d", citation.id)
            return ExtractionResult(
                citation_id=citation.id,
                extracted_data={var.name: None for var in self.protocol.extraction_variables},
                model=self.model,
                extracted_at=datetime.now(),
            )

    def extract_batch(self, citations: list[Citation]) -> list[ExtractionResult]:
        """
        Extract data from multiple citations.

        Args:
            citations: List of citations to extract from (each should have pdf_path set)

        Returns:
            List of ExtractionResults
        """
        results = []
        for citation in citations:
            result = self.extract(citation)
            results.append(result)
        return results
