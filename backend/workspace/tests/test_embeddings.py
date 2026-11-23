"""Embedding requests never switch models; transient failures retry the same model."""
import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

import httpx
from django.test import SimpleTestCase
from openai import APIStatusError, APITimeoutError, RateLimitError

from common import embeddings
from common.errors import PipelineError

MODEL = "nvidia/nemotron-3.5-embed-1b:free"
REQUEST = httpx.Request("POST", "https://openrouter.ai/api/v1/embeddings")


def status_error(status, headers=None, cls=APIStatusError):
    response = httpx.Response(status, request=REQUEST, headers=headers or {})
    return cls(f"HTTP {status}", response=response, body=None)


class ScriptedEmbeddings:
    """`client.embeddings`: raises the scripted errors in order, then answers."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.models = []

    def create(self, input, model=None, **kwargs):  # noqa: A002 - OpenAI kwarg name
        self.models.append(model)
        if self.errors:
            raise self.errors.pop(0)
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[1.0, float(i) + 1]) for i in range(len(input))])


class EmbeddingRetryTests(SimpleTestCase):
    def setUp(self):
        patch = mock.patch.object(embeddings, "_sleep")
        self.sleep = patch.start()
        self.addCleanup(patch.stop)

    def embed(self, provider):
        return embeddings.embed_texts(SimpleNamespace(embeddings=provider), ["alpha", "beta"], MODEL)

    def test_transient_failures_retry_the_same_model(self):
        provider = ScriptedEmbeddings(status_error(429, cls=RateLimitError), APITimeoutError(request=REQUEST))
        vectors = self.embed(provider)
        self.assertEqual(len(vectors), 2)
        self.assertEqual(provider.models, [MODEL, MODEL, MODEL])
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], list(embeddings.RETRY_DELAYS_SECONDS))

    def test_a_persistent_rate_limit_fails_retryably_without_another_model(self):
        provider = ScriptedEmbeddings(*[status_error(429, cls=RateLimitError) for _ in range(5)])
        with self.assertRaises(PipelineError) as raised:
            self.embed(provider)
        self.assertEqual((raised.exception.code, raised.exception.retryable), ("provider_rate_limit", True))
        self.assertEqual(set(provider.models), {MODEL})
        self.assertEqual(len(provider.models), len(embeddings.RETRY_DELAYS_SECONDS) + 1)

    def test_exhausted_credits_are_not_retried(self):
        provider = ScriptedEmbeddings(status_error(402))
        with self.assertRaises(PipelineError) as raised:
            self.embed(provider)
        self.assertEqual(raised.exception.code, "provider_credits")
        self.assertEqual(provider.models, [MODEL])
        self.sleep.assert_not_called()

    def test_retry_after_is_honoured_and_capped(self):
        provider = ScriptedEmbeddings(status_error(503, {"retry-after": "2.5"}), status_error(503, {"retry-after": "600"}))
        self.embed(provider)
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [2.5, embeddings.MAX_RETRY_AFTER_SECONDS])

    def test_pipeline_errors_pass_through_untouched(self):
        error = PipelineError("provider_timeout", "Embedding timed out.", retryable=True, http_status=504)
        provider = ScriptedEmbeddings(error)
        with self.assertRaises(PipelineError) as raised:
            self.embed(provider)
        self.assertIs(raised.exception, error)
        self.assertEqual(provider.models, [MODEL])

    def test_no_fallback_model_list_remains(self):
        self.assertFalse(hasattr(embeddings, "FREE_OPENROUTER_EMBEDDING_MODELS"))
