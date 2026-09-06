"""The OpenRouter model catalogue that backs the model selector.

`GET https://openrouter.ai/api/v1/models` is the list of everything OpenRouter
can route to. It is fetched on demand, cached, and reduced to the handful of
fields the selector needs.

The curated defaults are always the fallback. No API key, no network, a slow
response or an unexpected payload must leave the selector usable with the three
models this project ships with, rather than empty — the catalogue is a
convenience, not a dependency.
"""
import logging

import requests
from django.core.cache import cache
from django.conf import settings

from common.constant import LLM_MODELS, MODEL_IDS, is_valid_model_id

logger = logging.getLogger(__name__)

CATALOG_URL = "https://openrouter.ai/api/v1/models"
CATALOG_CACHE_KEY = "openrouter:model-catalog:v1"
CATALOG_CACHE_TTL = 60 * 60 * 6  # six hours; the catalogue changes slowly
CATALOG_TIMEOUT = 8  # seconds — this sits in front of a page load


def _provider_of(model_id: str) -> str:
    """The provider half of `provider/model`, title-cased for display."""
    head = model_id.split("/", 1)[0]
    return {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "google": "Google",
        "meta-llama": "Meta",
        "mistralai": "Mistral",
        "deepseek": "DeepSeek",
        "qwen": "Qwen",
        "x-ai": "xAI",
    }.get(head, head.replace("-", " ").title())


def _is_text_generator(entry: dict) -> bool:
    """Keep chat models; drop embedding-, image- and moderation-only entries.

    Defensive on purpose: OpenRouter has changed this part of the payload
    before, and an unrecognised shape should let a model through rather than
    empty the catalogue.
    """
    architecture = entry.get("architecture")
    if not isinstance(architecture, dict):
        return True

    outputs = architecture.get("output_modalities")
    if isinstance(outputs, list) and outputs:
        return "text" in outputs

    modality = architecture.get("modality")
    if isinstance(modality, str) and "->" in modality:
        return "text" in modality.split("->", 1)[1]

    return True


def _price(entry: dict, key: str):
    """Per-token price as a float, or None when OpenRouter doesn't give one."""
    pricing = entry.get("pricing")
    if not isinstance(pricing, dict):
        return None
    try:
        return float(pricing.get(key))
    except (TypeError, ValueError):
        return None


def _normalize(entry: dict) -> dict | None:
    model_id = entry.get("id")
    if not is_valid_model_id(model_id) or not _is_text_generator(entry):
        return None

    return {
        "id": model_id,
        "label": entry.get("name") or model_id,
        "provider": _provider_of(model_id),
        "context_length": entry.get("context_length"),
        "prompt_price": _price(entry, "prompt"),
        "completion_price": _price(entry, "completion"),
        "is_default": model_id in MODEL_IDS,
    }


def default_catalog() -> list[dict]:
    """The three models this project ships with, in catalogue shape."""
    return [
        {
            **model,
            "context_length": None,
            "prompt_price": None,
            "completion_price": None,
            "is_default": True,
        }
        for model in LLM_MODELS
    ]


def _sorted(models: list[dict]) -> list[dict]:
    """Defaults first in their declared order, then everything else A-Z."""
    rank = {model_id: index for index, model_id in enumerate(MODEL_IDS)}
    return sorted(models, key=lambda m: (rank.get(m["id"], len(rank)), m["id"]))


def fetch_catalog(force: bool = False) -> dict:
    """Return `{models, source, error}` for the model selector.

    `source` is "openrouter" when the list came from the API and "defaults"
    when it fell back, so the UI can say which it is showing.
    """
    if not force:
        cached = cache.get(CATALOG_CACHE_KEY)
        if cached:
            return cached

    api_key = getattr(settings, "OPENROUTER_API_KEY", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    try:
        response = requests.get(CATALOG_URL, headers=headers, timeout=CATALOG_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # network, timeout, non-2xx, bad JSON
        logger.warning(f"OpenRouter catalogue unavailable, using defaults: {exc}")
        return {
            "models": _sorted(default_catalog()),
            "source": "defaults",
            "error": str(exc),
        }

    raw = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        logger.warning("OpenRouter catalogue had an unexpected shape, using defaults.")
        return {
            "models": _sorted(default_catalog()),
            "source": "defaults",
            "error": "unexpected response shape",
        }

    models = [m for m in (_normalize(entry) for entry in raw) if m]

    # Anything shipped as a default but missing from the response still belongs
    # in the list — the run would work, and losing it would silently change
    # what the sidebar pre-selects.
    known = {m["id"] for m in models}
    models.extend(m for m in default_catalog() if m["id"] not in known)

    if not models:
        return {
            "models": _sorted(default_catalog()),
            "source": "defaults",
            "error": "no text-generation models in response",
        }

    result = {"models": _sorted(models), "source": "openrouter", "error": None}
    cache.set(CATALOG_CACHE_KEY, result, CATALOG_CACHE_TTL)
    return result
