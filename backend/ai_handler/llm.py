from common.prompt_builder import vote_prompt, rag_prompt, prompt_generator
from abc import ABC, abstractmethod
from typing import Optional
from django.conf import settings
from openai import OpenAI

# All LLMs are routed through OpenRouter using a single API key.
# Provider-specific classes just set the appropriate model prefix.


class BaseLLM(ABC):
    def __init__(self, model: str, temperature: float = 0.0, api_key: Optional[str] = None):
        self.model = model
        self.temperature = temperature
        self.api_key = api_key or settings.OPENROUTER_API_KEY

    @abstractmethod
    def _call_api(self, prompt: str) -> str:
        """Abstract method that child classes must implement."""
        pass

    def generate(self, prompt: str) -> str:
        """Standard text generation."""
        return self._call_api(prompt)

    def rag_generate(self, query: str, context: str) -> str:
        """Generates an answer based on RAG context."""
        formatted_prompt = rag_prompt(query, context)
        return self._call_api(formatted_prompt)

    def prompt_generate(self, query: str) -> str:
        """Generates/Optimizes a search query."""
        formatted_prompt = prompt_generator(query)
        return self._call_api(formatted_prompt)

    def vote_generate(self, query: str, chunk: str, response: str) -> str:
        """Generates a vote (Yes/No) for validity."""
        formatted_prompt = vote_prompt(query, chunk, response)
        return self._call_api(formatted_prompt)


class OpenRouterBase(BaseLLM):
    """Base class for OpenRouter-routed models using the OpenAI-compatible API."""

    def __init__(self, model: str, temperature: float = 0.0, api_key: str = ""):
        super().__init__(model, temperature, api_key)
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
            default_headers={
                "HTTP-Referer": "https://rag.nevatal.tech",
                "X-Title": "RagReader",
            },
        )

    def _call_api(self, prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            raise RuntimeError(f"OpenRouter call failed ({self.model}): {e}") from e


class OpenAILLM(OpenRouterBase):
    """OpenAI models via OpenRouter (e.g. openai/gpt-4o, openai/gpt-4o-mini)."""
    def __init__(self, model: str = "openai/gpt-4o", temperature: float = 0.0, api_key: str = ""):
        super().__init__(model, temperature, api_key)


class ClaudeLLM(OpenRouterBase):
    """Anthropic models via OpenRouter (e.g. anthropic/claude-3.5-sonnet)."""
    def __init__(self, model: str = "anthropic/claude-3.5-sonnet", temperature: float = 0.0, api_key: str = ""):
        super().__init__(model, temperature, api_key)


class GeminiLLM(OpenRouterBase):
    """Google models via OpenRouter (e.g. google/gemini-2.0-flash)."""
    def __init__(self, model: str = "google/gemini-2.0-flash", temperature: float = 0.0, api_key: str = ""):
        super().__init__(model, temperature, api_key)


class MistralLLM(OpenRouterBase):
    """Mistral models via OpenRouter (e.g. mistralai/mistral-nemo)."""
    def __init__(self, model: str = "mistralai/mistral-nemo", temperature: float = 0.0, api_key: str = ""):
        super().__init__(model, temperature, api_key)