"""Exercise real Ragas, Instructor and OpenAI code with only HTTP mocked."""
import importlib.util
import asyncio
import json
from unittest import mock

import httpx
from django.test import SimpleTestCase, override_settings
from openai import AsyncOpenAI

from common.constant import DEFAULT_EMBEDDING_MODEL
from common.analysis_progress import progress_scope, progress_stage
from evaluation.eval import evaluate_response


class OpenRouterEvaluationFixture:
    def __init__(self, fail_embeddings=False):
        self.requests = []
        self.clients = []
        self.fail_embeddings = fail_embeddings

    def client(self, **kwargs):
        client = AsyncOpenAI(**{**kwargs, "max_retries": 0}, http_client=httpx.AsyncClient(transport=httpx.MockTransport(self.respond)))
        self.clients.append(client)
        return client

    def respond(self, request):
        payload = json.loads(request.content)
        self.requests.append((request.url, payload))
        assert request.url.host == "openrouter.ai"
        if request.url.path == "/api/v1/embeddings":
            if self.fail_embeddings:
                return httpx.Response(503, json={"error": {"message": "Fixture embedding outage"}})
            values = payload["input"] if isinstance(payload["input"], list) else [payload["input"]]
            return httpx.Response(200, json={"object": "list", "data": [{"object": "embedding", "index": i, "embedding": [1.0, 0.0]} for i in range(len(values))], "model": payload["model"], "usage": {"prompt_tokens": 1, "total_tokens": 1}})
        assert request.url.path == "/api/v1/chat/completions"
        prompt = "\n".join(message["content"] for message in payload["messages"])
        claims = ["Solar panels generate power.", "Cats use solar panels."]
        if "Generate a question for the given answer" in prompt:
            content = {"question": "How does solar power work?", "noncommittal": 0}
        elif "judge the faithfulness of a series of statements" in prompt:
            content = {"statements": [{"statement": claim, "reason": "Fixture verdict", "verdict": 1 - i} for i, claim in enumerate(claims)]}
        elif "Decompose and break down" in prompt:
            content = {"claims": claims}
        elif "Break down each sentence" in prompt:
            content = {"statements": claims}
        else:
            raise AssertionError("Unexpected evaluation prompt")
        return httpx.Response(200, json={"id": "fixture", "object": "chat.completion", "created": 1, "model": payload["model"], "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(content)}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


@override_settings(OPENROUTER_API_KEY="test-only-key")
class RagasEvaluationTests(SimpleTestCase):
    def setUp(self):
        self.fixture = OpenRouterEvaluationFixture()
        patcher = mock.patch("evaluation.eval.AsyncOpenAI", side_effect=self.fixture.client)
        self.client_factory = patcher.start()
        self.addCleanup(patcher.stop)

    def evaluate(self, **kwargs):
        return evaluate_response(**{
            "response": "Solar panels generate power. Cats use solar panels.",
            "ground_truth_response": "Solar panels turn sunlight into electricity.",
            "chunks": ["Only this actual source passage is evidence."],
            "question": "How does solar power work?",
            "judge_model": "openai/gpt-4o-mini",
            **kwargs,
        })

    def test_real_ragas_metrics_use_openrouter_chat_and_embeddings(self):
        events = []
        with progress_scope(events.append):
            progress_stage("evaluate", "Scoring the answer.")
            report = self.evaluate()
        for name, value in report["scores"].items():
            updates = [event for event in events if event["id"] == name]
            self.assertEqual([event["status"] for event in updates], ["running", "completed"])
            self.assertEqual(updates[-1]["score"], value)
            self.assertTrue(all(event["stage"] == "evaluate" for event in updates))
        self.assertEqual(report["scores"], {"faithfulness": 0.5, "answer_relevancy": 1.0, "factual_correctness": 0.5})
        self.assertTrue(all(value["status"] == "completed" for value in report["details"]["metrics"].values()))
        chats = [body for url, body in self.fixture.requests if url.path.endswith("chat/completions")]
        embeddings = [body for url, body in self.fixture.requests if url.path.endswith("embeddings")]
        self.assertTrue(chats and embeddings)
        self.assertTrue(all(body["model"] == "openai/gpt-4o-mini" for body in chats))
        self.assertTrue(all(body["model"] == DEFAULT_EMBEDDING_MODEL for body in embeddings))
        prompts = json.dumps(chats)
        self.assertIn("How does solar power work?", prompts)
        self.assertIn("Only this actual source passage is evidence.", prompts)
        self.assertIn("Solar panels turn sunlight into electricity.", prompts)
        self.assertTrue(all(client.is_closed() for client in self.fixture.clients))
        json.dumps(report, allow_nan=False)

    def test_embedding_failure_keeps_other_metric_scores(self):
        self.fixture.fail_embeddings = True
        events = []
        with progress_scope(events.append):
            report = self.evaluate()
        updates = [event for event in events if event["id"] == "answer_relevancy"]
        self.assertEqual([event["status"] for event in updates], ["running", "unavailable"])
        self.assertIsNone(updates[-1]["score"])
        self.assertEqual(report["scores"]["faithfulness"], 0.5)
        self.assertEqual(report["scores"]["factual_correctness"], 0.5)
        self.assertIsNone(report["scores"]["answer_relevancy"])
        self.assertEqual(report["details"]["metrics"]["answer_relevancy"]["status"], "unavailable")

    def test_no_reference_still_scores_faithfulness_and_relevance(self):
        report = self.evaluate(ground_truth_response=None)
        self.assertEqual(report["scores"]["faithfulness"], 0.5)
        self.assertEqual(report["scores"]["answer_relevancy"], 1.0)
        self.assertIsNone(report["scores"]["factual_correctness"])
        self.assertEqual(report["details"]["metrics"]["factual_correctness"]["status"], "skipped")

    def test_direct_answer_does_not_fake_a_faithfulness_score(self):
        report = self.evaluate(chunks=[])
        self.assertIsNone(report["scores"]["faithfulness"])
        self.assertEqual(report["details"]["metrics"]["faithfulness"]["status"], "skipped")
        self.assertEqual(report["scores"]["factual_correctness"], 0.5)

    def test_missing_question_does_not_substitute_the_reference(self):
        report = self.evaluate(question="")
        self.assertIsNone(report["scores"]["answer_relevancy"])
        self.assertIsNone(report["scores"]["faithfulness"])
        self.assertEqual(report["scores"]["factual_correctness"], 0.5)

    def test_empty_answer_does_not_call_any_provider(self):
        report = self.evaluate(response=" ")
        self.assertTrue(all(value is None for value in report["scores"].values()))
        self.client_factory.assert_not_called()

    @override_settings(OPENROUTER_API_KEY="")
    def test_missing_key_reports_unavailable_without_a_provider_call(self):
        report = self.evaluate()
        self.client_factory.assert_not_called()
        self.assertTrue(all(value["status"] == "unavailable" for value in report["details"]["metrics"].values()))

    def test_client_setup_failure_does_not_lose_the_report(self):
        self.client_factory.side_effect = RuntimeError("fixture-secret")
        report = self.evaluate()
        self.assertTrue(all(value is None for value in report["scores"].values()))
        self.assertNotIn("fixture-secret", json.dumps(report))

    def test_nan_is_json_null_and_the_failure_is_explained(self):
        with mock.patch("ragas.metrics.collections.Faithfulness.ascore", new=mock.AsyncMock(return_value=mock.Mock(value=float("nan")))):
            report = self.evaluate()
        self.assertIsNone(report["scores"]["faithfulness"])
        self.assertEqual(report["details"]["metrics"]["faithfulness"]["status"], "unavailable")
        json.dumps(report, allow_nan=False)

    def test_metric_timeout_is_bounded_and_keeps_successful_scores(self):
        async def delayed_metric(self, **kwargs):
            await asyncio.sleep(1)
        with mock.patch("ragas.metrics.collections.Faithfulness.ascore", new=delayed_metric), mock.patch("evaluation.eval.METRIC_TIMEOUT_SECONDS", 0.2):
            report = self.evaluate()
        self.assertIsNone(report["scores"]["faithfulness"])
        self.assertEqual(report["details"]["metrics"]["faithfulness"]["reason"], "Evaluation timed out.")
        self.assertEqual(report["scores"]["factual_correctness"], 0.5)

    def test_backend_installs_no_local_neural_or_overlap_evaluator(self):
        for package in ("torch", "transformers", "sentence_transformers", "bert_score", "rouge_score"):
            with self.subTest(package=package):
                self.assertIsNone(importlib.util.find_spec(package))
