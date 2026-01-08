"""Multi-LLM abstraction layer using LiteLLM for systematic review automation.

LiteLLM provides unified access to multiple LLM providers including:
- Anthropic Claude (claude-sonnet-4-5-20250929, claude-haiku-4-5-20251015, etc.)
- OpenAI (gpt-4.1, gpt-4o, etc.)
- OpenRouter (openrouter/anthropic/claude-3-opus, etc.)
- And many more

Model names follow the LiteLLM convention. Set API keys via environment variables:
- ANTHROPIC_API_KEY for Anthropic models
- OPENAI_API_KEY for OpenAI models
- OPENROUTER_API_KEY for OpenRouter models
"""

from automated_sr.llm.base import LLMClient, create_client
from automated_sr.models import APIProvider

__all__ = [
    "APIProvider",
    "LLMClient",
    "create_client",
]
