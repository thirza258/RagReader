"""Bounded remote embedding requests with strict response alignment."""
import logging
import numbers
import random
import numpy as np

from common.errors import PipelineError, provider_error

logger = logging.getLogger(__name__)

EMBEDDING_BATCH_SIZE = 64
EMBEDDING_TIMEOUT_SECONDS = 45.0

FREE_OPENROUTER_EMBEDDING_MODELS = [
    "nvidia/nemotron-3.5-embed-1b:free",
    "nvidia/nemotron-3-embed-1b:free",
    "nvidia/nemotron-3.5-embed-8b:free",
]


def get_shuffled_free_embedding_models() -> list[str]:
    models = list(FREE_OPENROUTER_EMBEDDING_MODELS)
    random.shuffle(models)
    return models


def validate_vectors(vectors, count, dimensions=None):
    try:
        values = np.asarray(vectors, dtype=float)
    except (TypeError, ValueError, OverflowError):
        values = np.asarray([])
    invalid = (values.ndim != 2 or len(values) != count or not count or values.shape[1] == 0
               or not np.isfinite(values).all()
               or (dimensions is not None and values.shape[1] != dimensions))
    if not invalid:
        with np.errstate(over="ignore", invalid="ignore"):
            norms = np.linalg.norm(values, axis=1)
        invalid = not np.isfinite(norms).all() or np.any(norms == 0)
    if invalid:
        raise PipelineError("invalid_embeddings", "The embedding provider returned incomplete or incompatible vectors. Retry indexing the document.", retryable=True, http_status=502)
    return values


def embed_texts(client, texts, model, *, dimensions=None):
    if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
        raise PipelineError("empty_embedding_input", "The document or search question has no usable text to embed.", http_status=400)
    vectors = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = [text.replace("\n", " ") for text in texts[start:start + EMBEDDING_BATCH_SIZE]]
        try:
            response = client.embeddings.create(input=batch, model=model)
            rows = response.data
            if not isinstance(rows, list) or len(rows) != len(batch):
                raise ValueError("Embedding count mismatch")
            # OpenAI-compatible responses identify the original input position.
            # Never pair an out-of-order vector with the wrong source passage.
            indices = [getattr(row, "index", None) for row in rows]
            if any(not isinstance(index, numbers.Integral) or isinstance(index, bool) for index in indices) or sorted(indices) != list(range(len(batch))):
                raise ValueError("Missing or duplicate embedding indices")
            ordered = [row.embedding for row in sorted(rows, key=lambda row: row.index)]
            values = validate_vectors(ordered, len(batch), dimensions)
        except PipelineError:
            raise
        except (ValueError, TypeError, AttributeError) as exc:
            raise PipelineError("invalid_embeddings", "OpenRouter returned an invalid embedding response. Retry indexing the document.", retryable=True, http_status=502) from exc
        except Exception as exc:
            exc_str = str(exc).lower()
            is_credit = any(k in exc_str for k in ("402", "credit", "payment required", "insufficient", "quota", "balance"))
            is_free_rate_limit = ":free" in str(model) and any(k in exc_str for k in ("429", "rate limit", "502", "503", "timeout", "temporarily unavailable", "overloaded"))
            if is_credit or is_free_rate_limit:
                logger.warning("Embedding with %s failed (%s); retrying with free models", model, exc)
                succeeded = False
                for fb_model in get_shuffled_free_embedding_models():
                    if fb_model == model:
                        continue
                    try:
                        logger.info("Retrying embeddings with free model: %s", fb_model)
                        fb_response = client.embeddings.create(input=batch, model=fb_model)
                        fb_rows = fb_response.data
                        if not isinstance(fb_rows, list) or len(fb_rows) != len(batch):
                            continue
                        fb_ordered = [row.embedding for row in sorted(fb_rows, key=lambda row: row.index)]
                        values = validate_vectors(fb_ordered, len(batch), dimensions)
                        dimensions = values.shape[1]
                        vectors.extend(values.tolist())
                        succeeded = True
                        logger.info("Embedding fallback succeeded with %s", fb_model)
                        break
                    except Exception as fb_exc:
                        logger.warning("Free embedding model %s failed: %s", fb_model, fb_exc)
                        continue
                if succeeded:
                    continue
            raise provider_error(exc, "Embedding", model) from exc
        dimensions = values.shape[1]
        vectors.extend(values.tolist())
    return vectors
