"""Rerankers for the `hybrid_rerank` strategy (PRD §18).

A reranker scores every fused candidate against the query; the candidates
are then reordered by that score (ties keep the fused order) and the top-k
become the answer's sources. Two providers:

* `ollama` — the existing Ollama embedding reranker
  (`hybrid_rag.get_cross_encoder`, models from `RERANKER_MODELS`): cosine
  similarity of query and passage embeddings.
* `llm` — any OpenRouter chat model, asked once for a 0–10 relevance score
  per numbered passage. The prompt is bounded (each passage is cut to fit
  `LLM_RERANK_PROMPT_CHARS`) and the reply is parsed strictly: JSON only,
  every passage id exactly once, a finite score within range. Scores are
  returned divided by `LLM_RERANK_MAX_SCORE`, so 0–1.

Every failure raises; the retrieval service turns any of them into a
fallback to the fused order, so a reranker can never fail a question.
"""
import json
import math

from common.constant import (
    LLM_RERANK_MAX_SCORE, LLM_RERANK_PASSAGE_CHARS, LLM_RERANK_PROMPT_CHARS, LLM_RERANK_QUERY_CHARS,
)
from common.errors import PipelineError
from workspace.services import llms

MIN_PASSAGE_CHARS = 80


class RerankFailed(PipelineError):
    def __init__(self, code, message):
        super().__init__(code, message, retryable=True, http_status=502)


def _scores(values, count):
    """`count` finite floats, or RerankFailed."""
    try:
        scores = [float(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise RerankFailed("reranker_invalid_response", "The reranker returned scores that are not numbers.") from exc
    if len(scores) != count:
        raise RerankFailed("reranker_invalid_response", f"The reranker returned {len(scores)} scores for {count} passages.")
    if not all(math.isfinite(score) for score in scores):
        raise RerankFailed("reranker_invalid_response", "The reranker returned a score that is not finite.")
    return scores


class OllamaReranker:
    provider = "ollama"

    def __init__(self, model):
        self.model = model

    def score(self, query, texts):
        from hybrid_rag.hybrid_rag import get_cross_encoder

        if not texts:
            return []
        try:
            predicted = get_cross_encoder(self.model).predict([(query, text) for text in texts])
        except PipelineError:
            raise
        except Exception as exc:
            raise RerankFailed("reranker_unavailable", f"The Ollama reranker '{self.model}' could not score the candidates.") from exc
        return _scores(predicted, len(texts))


def _clip(text, limit):
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:max(1, limit - 1)].rstrip() + "…"


def rerank_prompt(query, texts):
    """One bounded prompt that asks for a JSON score per numbered passage."""
    budget = max(MIN_PASSAGE_CHARS, min(LLM_RERANK_PASSAGE_CHARS, LLM_RERANK_PROMPT_CHARS // max(1, len(texts))))
    passages = "\n\n".join(f"[{number}] {_clip(text, budget)}" for number, text in enumerate(texts, 1))
    return (
        "You are the relevance judge of a document search engine. For each numbered passage, score how well it "
        f"helps answer the query, from 0 (irrelevant) to {LLM_RERANK_MAX_SCORE} (directly answers it).\n"
        "Reply with JSON only, no explanation or code fence, in exactly this shape, with every passage id exactly once:\n"
        '{"scores": [{"id": 1, "score": 7}, {"id": 2, "score": 0}]}\n\n'
        f"Query: {_clip(query, LLM_RERANK_QUERY_CHARS)}\n\n"
        f"Passages:\n\n{passages}"
    )


def _strip_fence(raw):
    text = (raw or "").strip()
    if text.startswith("```") and text.endswith("```") and len(text) >= 6:
        text = text[3:-3].strip()
        if text[:4].lower() == "json":
            text = text[4:].strip()
    return text


def parse_scores(raw, count):
    """Scores (0–1) in passage order from the model's reply, or RerankFailed."""
    try:
        payload = json.loads(_strip_fence(raw))
    except (TypeError, ValueError) as exc:
        raise RerankFailed("reranker_invalid_response", "The LLM reranker did not reply with JSON.") from exc
    items = payload.get("scores") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise RerankFailed("reranker_invalid_response", 'The LLM reranker reply has no "scores" list.')
    found = {}
    for item in items:
        if not isinstance(item, dict):
            raise RerankFailed("reranker_invalid_response", "Every LLM reranker score must be an object with id and score.")
        number, score = item.get("id"), item.get("score")
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= count or number in found:
            raise RerankFailed("reranker_invalid_response", "The LLM reranker reply has a missing, unknown or repeated passage id.")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) \
                or not 0 <= score <= LLM_RERANK_MAX_SCORE:
            raise RerankFailed("reranker_invalid_response", f"LLM reranker scores must be numbers from 0 to {LLM_RERANK_MAX_SCORE}.")
        found[number] = float(score)
    if len(found) != count:
        raise RerankFailed("reranker_invalid_response", f"The LLM reranker scored {len(found)} of {count} passages.")
    return [found[number] / LLM_RERANK_MAX_SCORE for number in range(1, count + 1)]


class LLMReranker:
    provider = "llm"

    def __init__(self, model):
        self.model = model

    def score(self, query, texts):
        if not texts:
            return []
        reply = llms.llm_for(self.model).generate(rerank_prompt(query, texts))
        return parse_scores(reply, len(texts))


PROVIDERS = {"ollama": OllamaReranker, "llm": LLMReranker}


def reranker_for(spec):
    """The reranker a pipeline configuration names (`{"provider", "model"}`)."""
    provider = PROVIDERS.get((spec or {}).get("provider"))
    if provider is None:
        raise RerankFailed("reranker_unavailable", "The pipeline names an unknown reranker.")
    return provider(spec.get("model"))
