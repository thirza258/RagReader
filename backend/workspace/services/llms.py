"""OpenRouter clients for the models a pipeline names (generation, LLM reranking).

The chat engine's own LLM answers when a pipeline uses the engine's model,
so the default pipeline behaves exactly as Phase 1 chat. Any other
well-formed OpenRouter id gets one shared `OpenRouterLLM`, built on first
use. Sharing is safe: `stream_chat` keeps no per-call state on the instance
and takes the temperature per call, and `generate` only reads the instance.
"""
import threading

from ai_handler.llm import OpenRouterLLM

_clients = {}
_lock = threading.Lock()


def llm_for(model):
    """The shared OpenRouterLLM for `model` (temperature 0 for `generate`).

    Raises ValueError for a malformed id and PipelineError
    `missing_provider_key` when no OpenRouter key is configured.
    """
    with _lock:
        client = _clients.get(model)
    if client is not None:
        return client
    client = OpenRouterLLM(model=model, temperature=0.0)
    with _lock:
        return _clients.setdefault(model, client)


def generation_llm(engine, model):
    """The LLM that answers (and rewrites) for a pipeline whose generation model is `model`."""
    if model and model != getattr(engine.llm, "model", None):
        return llm_for(model)
    return engine.llm


def clear():
    with _lock:
        _clients.clear()
