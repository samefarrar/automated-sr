"""LLM client using LiteLLM for multi-provider support."""

import base64
import logging
from pathlib import Path
from typing import Any

import litellm

from automated_sr.models import APIProvider

logger = logging.getLogger(__name__)

# Suppress LiteLLM info messages
litellm.suppress_debug_info = True


class LLMClient:
    """LLM client using LiteLLM for unified access to multiple providers."""

    def __init__(self, api: APIProvider | None = None, api_key: str | None = None) -> None:
        """
        Initialize the LLM client.

        Args:
            api: Optional API provider hint (not required for LiteLLM)
            api_key: Optional API key (LiteLLM uses env vars by default)
        """
        self.api = api
        self.api_key = api_key

    def complete(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        """
        Send a completion request and return the response text.

        Args:
            prompt: The user prompt to send
            model: Model identifier (e.g., "claude-sonnet-4-5-20250929", "gpt-4.1")
            max_tokens: Maximum tokens in the response
            temperature: Sampling temperature (0.0 = deterministic)

        Returns:
            The model's response text
        """
        logger.debug("LiteLLM completion request: model=%s, max_tokens=%d", model, max_tokens)

        # Build kwargs
        kwargs: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key

        response: Any = litellm.completion(**kwargs)

        # Extract text from response
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            if hasattr(choice, "message") and hasattr(choice.message, "content"):
                return choice.message.content or ""
        return ""

    def complete_with_document(
        self,
        prompt: str,
        document_base64: str,
        model: str,
        document_type: str = "application/pdf",
        max_tokens: int = 4096,
    ) -> str:
        """
        Send a completion request with an attached document.

        Args:
            prompt: The user prompt to send
            document_base64: Base64-encoded document content
            model: Model identifier
            document_type: MIME type of the document
            max_tokens: Maximum tokens in the response

        Returns:
            The model's response text
        """
        logger.debug("LiteLLM document completion: model=%s, doc_type=%s", model, document_type)

        # Use LiteLLM's file format for document processing
        # See: https://docs.litellm.ai/docs/completion/document_understanding
        content = [
            {"type": "text", "text": prompt},
            {
                "type": "file",
                "file": {
                    "file_data": f"data:{document_type};base64,{document_base64}",
                    "format": document_type,
                },
            },
        ]

        kwargs: dict = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key

        response: Any = litellm.completion(**kwargs)

        # Extract text from response
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            if hasattr(choice, "message") and hasattr(choice.message, "content"):
                return choice.message.content or ""
        return ""

    def complete_with_pdf_path(
        self,
        prompt: str,
        pdf_path: Path,
        model: str,
        max_tokens: int = 4096,
    ) -> str:
        """
        Send a completion request with a PDF file.

        Args:
            prompt: The user prompt to send
            pdf_path: Path to the PDF file
            model: Model identifier
            max_tokens: Maximum tokens in the response

        Returns:
            The model's response text
        """
        # Read and encode PDF
        with open(pdf_path, "rb") as f:
            pdf_content = f.read()

        pdf_base64 = base64.b64encode(pdf_content).decode("utf-8")

        return self.complete_with_document(
            prompt=prompt,
            document_base64=pdf_base64,
            model=model,
            document_type="application/pdf",
            max_tokens=max_tokens,
        )

    @property
    def supports_documents(self) -> bool:
        """Whether this client supports document attachments."""
        # Most modern models support documents via multimodal
        return True

    @property
    def provider(self) -> APIProvider | None:
        """The API provider for this client."""
        return self.api


def create_client(api: APIProvider | str | None = None, api_key: str | None = None) -> LLMClient:
    """
    Create an LLM client.

    With LiteLLM, the provider is determined by the model name,
    so the api parameter is optional.

    Args:
        api: Optional API provider (for API key selection)
        api_key: Optional API key (defaults to environment variable)

    Returns:
        LLMClient instance
    """
    api_enum = None
    if isinstance(api, str):
        api_enum = APIProvider(api.lower())
    elif isinstance(api, APIProvider):
        api_enum = api

    return LLMClient(api=api_enum, api_key=api_key)
