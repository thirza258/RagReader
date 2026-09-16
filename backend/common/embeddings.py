"""Bounded remote embedding requests with strict response alignment."""
import numbers
import numpy as np

from common.errors import PipelineError, provider_error

EMBEDDING_BATCH_SIZE = 64
EMBEDDING_TIMEOUT_SECONDS = 45.0


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
            raise provider_error(exc, "Embedding", model) from exc
        dimensions = values.shape[1]
        vectors.extend(values.tolist())
    return vectors
