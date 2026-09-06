"""LLM access — all of it through OpenRouter.

Generation, query rewriting and LLM-judged evaluation all speak to the same
OpenAI-compatible endpoint with one API key, so a model is fully described by
its OpenRouter id (``provider/model``). There is no per-provider behaviour to
implement: the provider-named classes below differ only in the default id they
carry, and exist so call sites can stay readable.

Because nothing is provider-specific, *any* id OpenRouter serves works here.
`common.constant.is_valid_model_id` checks the shape; OpenRouter itself is the
authority on whether the model exists, and says so in the error it returns.
"""
from abc import ABC, abstractmethod
from typing import Optional

from django.conf import settings
from openai import OpenAI

from common.constant import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_JUDGE_MODEL,
    is_valid_model_id,
)
from common.prompt_builder import vote_prompt, rag_prompt, prompt_generator

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# OpenRouter attributes traffic by these; they are cosmetic, not auth.
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://rag.nevatal.tech",
    "X-Title": "RagReader",
}


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


class OpenRouterLLM(BaseLLM):
    """Any OpenRouter-served model, reached over the OpenAI-compatible API."""

    def __init__(
        self,
        model: str = DEFAULT_CHAT_MODEL,
        temperature: float = 0.0,
        api_key: str = "",
    ):
        if not is_valid_model_id(model):
            raise ValueError(
                f"'{model}' is not a valid OpenRouter model id — "
                "expected the form 'provider/model', e.g. 'openai/gpt-4o-mini'."
            )
        super().__init__(model, temperature, api_key)
        self.client = OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=self.api_key,
            default_headers=OPENROUTER_HEADERS,
        )

    def _call_api(self, prompt: str) -> str:
        try:
            if not self.api_key:
                raise ValueError("OpenRouter API key is missing or not configured.")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
            )
            if not response or getattr(response, "choices", None) is None:
                raise ValueError(f"OpenRouter response missing choices: {response}")
            if len(response.choices) == 0:
                raise ValueError("OpenRouter returned empty choices list.")
            choice = response.choices[0]
            if getattr(choice, "message", None) is None or choice.message.content is None:
                return ""
            return (choice.message.content or "").strip()
        except Exception as e:
            raise RuntimeError(f"OpenRouter call failed ({self.model}): {e}") from e


# ── Named defaults ───────────────────────────────────────────────────────────
# Kept as separate classes because call sites read better as `MistralLLM()`
# than `OpenRouterLLM("mistralai/mistral-nemo")`. They add no behaviour, and a
# model id from any provider works through any of them.

OpenRouterBase = OpenRouterLLM  # pre-existing name, kept for imports


class OpenAILLM(OpenRouterLLM):
    """OpenAI models via OpenRouter (e.g. openai/gpt-4o, openai/gpt-4o-mini)."""
    def __init__(self, model: str = "openai/gpt-4o", temperature: float = 0.0, api_key: str = ""):
        super().__init__(model, temperature, api_key)


class ClaudeLLM(OpenRouterLLM):
    """Anthropic models via OpenRouter (e.g. anthropic/claude-haiku-4.5)."""
    def __init__(self, model: str = "anthropic/claude-3.5-sonnet", temperature: float = 0.0, api_key: str = ""):
        super().__init__(model, temperature, api_key)


class GeminiLLM(OpenRouterLLM):
    """Google models via OpenRouter (e.g. google/gemini-3-flash-preview)."""
    def __init__(self, model: str = "google/gemini-2.0-flash", temperature: float = 0.0, api_key: str = ""):
        super().__init__(model, temperature, api_key)


class MistralLLM(OpenRouterLLM):
    """Mistral models via OpenRouter — the default evaluation judge."""
    def __init__(self, model: str = DEFAULT_JUDGE_MODEL, temperature: float = 0.0, api_key: str = ""):
        super().__init__(model, temperature, api_key)
