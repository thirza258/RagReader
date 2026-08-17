"""
Tests for `router/consumers.py` — the WebSocket that drives a deep analysis.

This is the module that turns a stored AnalysisBatch into a stream of results:
it expands the batch's config into variants, pins the retrieval depth per
variant, initializes engines that aren't ready, calls `run_analysis`, persists
each result, and reports progress. None of that was covered before, and it is
the only place the pipeline layer is exercised end to end.

The engines themselves are mocked here — `router/tests_pipeline.py` covers what
they actually do. What matters in this file is the protocol: which frames go out,
in what order, what survives a failing variant, and what gets written to the DB.

`TransactionTestCase` rather than `TestCase`: the consumer reaches the database
through `sync_to_async`, which runs on a worker thread with its own connection,
so the fixtures have to be committed to be visible.
"""
import json
import os
from unittest import mock

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

from asgiref.sync import async_to_sync
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.core.cache import cache
from django.test import TransactionTestCase, override_settings

import router.consumers as consumers
import router.urls
from router.models import (
    AnalysisBatch,
    AnalysisResult,
    Conversation,
    Document,
    GuestUser,
)

IN_MEMORY_CHANNELS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
}
LOCMEM_CACHE = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}

DENSE = "Dense Retrieval"
GPT = "openai/gpt-4o-mini"
GEMINI = "google/gemini-3-flash-preview"

ANALYSIS_RESPONSE = {
    "answer": "generated answer",
    "context": [{"text": "chunk text", "chunk_id": 7, "score": 0.83}],
    "evaluation": {
        "chunk_evaluation": {"precision_k": 0.5, "recall_k": 1.0, "f1_k": 0.667},
        "response_evaluation": {"rougeL_f1": 0.4, "faithfulness": 0.8},
    },
}


def make_engine(is_initialized=True, response=None):
    engine = mock.Mock()
    engine.is_initialized.return_value = is_initialized
    engine.run_analysis.return_value = dict(response or ANALYSIS_RESPONSE)
    return engine


@override_settings(CHANNEL_LAYERS=IN_MEMORY_CHANNELS, CACHES=LOCMEM_CACHE)
class AnalysisConsumerTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.user = GuestUser.objects.create(
            username="alice", email="alice@example.com"
        )
        self.document = Document.objects.create(
            user=self.user, name="doc.txt", source_type="text"
        )
        self.conversation = Conversation.objects.create(
            user=self.user,
            document=self.document,
            query="what about alpha?",
            response="",
            context="",
        )

    # ── helpers ─────────────────────────────────────────────────────────────

    def make_batch(self, methods=(DENSE,), models=(GPT,), top_k=3):
        batch = AnalysisBatch.objects.create(
            user=self.user,
            conversation=self.conversation,
            query=self.conversation.query,
            total_variants=len(methods) * len(models),
            config={
                "methods": list(methods),
                "models": list(models),
                "top_k": top_k,
                "ground_truth_mode": "manual",
                "pool_top_n": 10,
            },
        )
        cache.set(
            f"job_input_{batch.job_id}",
            {
                "username": self.user.username,
                "query": self.conversation.query,
                "document_id": str(self.document.pk),
                "conversation_id": str(self.conversation.pk),
            },
            300,
        )
        return batch

    def collect(self, job_id, max_frames=25):
        """Drive the socket and return every frame it sent."""

        async def run():
            communicator = WebsocketCommunicator(
                URLRouter(router.urls.websocket_urlpatterns),
                f"/ws/analysis/{job_id}/",
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            frames = []
            terminated = False
            try:
                for _ in range(max_frames):
                    frame = json.loads(await communicator.receive_from(timeout=5))
                    frames.append(frame)
                    if frame.get("status") == "COMPLETE":
                        terminated = True
                        break
                    # A per-variant failure carries `method` and the run
                    # continues; an error without one is fatal and the
                    # consumer closes the socket behind it.
                    if "error" in frame and "method" not in frame:
                        terminated = True
                        break
            finally:
                await communicator.disconnect()

            # Without this, hitting the frame cap would truncate the stream and
            # the assertions on frames[-1] would pass against a partial run.
            self.assertTrue(
                terminated,
                f"stream did not finish within {max_frames} frames: "
                f"{[f.get('status') or f.get('method') for f in frames]}",
            )
            return frames

        return async_to_sync(run)()

    @staticmethod
    def results_in(frames):
        return [f for f in frames if "answer" in f]

    # ── failure to even start ────────────────────────────────────────────────

    def test_an_expired_job_cache_is_reported_not_hung(self):
        batch = self.make_batch()
        cache.delete(f"job_input_{batch.job_id}")

        frames = self.collect(batch.job_id)

        self.assertEqual(frames[0]["error"], "Job cache expired or invalid")

    def test_a_missing_batch_row_is_reported(self):
        cache.set(
            "job_input_11111111-1111-1111-1111-111111111111",
            {"username": "alice", "query": "q"},
            300,
        )

        frames = self.collect("11111111-1111-1111-1111-111111111111")

        self.assertEqual(frames[0]["error"], "Batch record not found in DB")

    # ── the normal run ───────────────────────────────────────────────────────

    def test_a_single_variant_streams_config_result_then_complete(self):
        batch = self.make_batch()
        engine = make_engine()

        with mock.patch.object(
            consumers.rag_registry, "get_engine", return_value=engine
        ), mock.patch.object(consumers, "apply_retrieval_depth"):
            frames = self.collect(batch.job_id)

        self.assertEqual(frames[0]["status"], "CONFIG")
        self.assertEqual(frames[0]["expected_count"], 1)
        self.assertEqual(frames[0]["config"]["top_k"], 3)

        result = frames[1]
        self.assertEqual(result["method"], DENSE)
        self.assertEqual(result["aiModel"], GPT)
        self.assertEqual(result["answer"], "generated answer")
        self.assertEqual(result["progress"], 100)
        self.assertEqual(
            result["evaluation"]["chunk_evaluation"]["recall_k"], 1.0
        )
        self.assertEqual(
            result["evaluation"]["retrieval_score"], [{"chunk_id": 7, "score": 0.83}]
        )

        self.assertEqual(frames[-1], {"status": "COMPLETE", "progress": 100})

        engine.run_analysis.assert_called_once_with(
            str(self.document.pk), str(self.conversation.pk)
        )

    def test_each_result_is_persisted_with_its_metrics(self):
        batch = self.make_batch()
        engine = make_engine()

        with mock.patch.object(
            consumers.rag_registry, "get_engine", return_value=engine
        ), mock.patch.object(consumers, "apply_retrieval_depth"):
            self.collect(batch.job_id)

        stored = AnalysisResult.objects.get(batch=batch)
        self.assertEqual(stored.method, DENSE)
        self.assertEqual(stored.ai_model, GPT)
        self.assertEqual(stored.query, self.conversation.query)
        self.assertEqual(stored.retrieved_chunks, [{"id": 7, "text": "chunk text", "score": 0.83}])
        self.assertEqual(
            [metric["name"] for metric in stored.evaluation_metrics],
            ["chunk_evaluation", "response_evaluation", "retrieval_score"],
        )

    def test_retrieval_depth_is_reapplied_for_every_variant(self):
        # Engines are process-wide singletons; skipping this per variant is how
        # one run's Top-K leaks into the next.
        batch = self.make_batch(models=(GPT, GEMINI), top_k=7)
        engine = make_engine()

        with mock.patch.object(
            consumers.rag_registry, "get_engine", return_value=engine
        ), mock.patch.object(consumers, "apply_retrieval_depth") as depth:
            frames = self.collect(batch.job_id)

        self.assertEqual(len(self.results_in(frames)), 2)
        self.assertEqual(depth.call_count, 2)
        for call in depth.call_args_list:
            self.assertEqual(call[0][1], 7)

    def test_progress_climbs_with_each_variant(self):
        batch = self.make_batch(models=(GPT, GEMINI))
        engine = make_engine()

        with mock.patch.object(
            consumers.rag_registry, "get_engine", return_value=engine
        ), mock.patch.object(consumers, "apply_retrieval_depth"):
            frames = self.collect(batch.job_id)

        self.assertEqual([f["progress"] for f in self.results_in(frames)], [50, 100])

    def test_an_engine_that_is_not_ready_is_initialized_first(self):
        batch = self.make_batch()
        engine = make_engine(is_initialized=False)

        with mock.patch.object(
            consumers.rag_registry, "get_engine", return_value=engine
        ), mock.patch.object(consumers, "apply_retrieval_depth"):
            frames = self.collect(batch.job_id)

        statuses = [f.get("status") for f in frames]
        self.assertIn("INITIALIZING", statuses)
        engine.init.assert_called_once_with("alice")
        self.assertEqual(len(self.results_in(frames)), 1)

    def test_one_failing_variant_does_not_sink_the_others(self):
        batch = self.make_batch(models=(GPT, GEMINI))
        engine = make_engine()

        def get_engine(method, model):
            if model == GPT:
                raise ValueError("Engine not found")
            return engine

        with mock.patch.object(
            consumers.rag_registry, "get_engine", side_effect=get_engine
        ), mock.patch.object(consumers, "apply_retrieval_depth"):
            frames = self.collect(batch.job_id)

        errors = [f for f in frames if "error" in f]
        self.assertEqual(len(errors), 1)
        self.assertIn("Engine not found", errors[0]["error"])
        self.assertEqual(len(self.results_in(frames)), 1)
        self.assertEqual(frames[-1]["status"], "COMPLETE")
        self.assertEqual(AnalysisResult.objects.filter(batch=batch).count(), 1)

    def test_a_variant_whose_analysis_raises_is_reported_and_skipped(self):
        batch = self.make_batch()
        engine = make_engine()
        engine.run_analysis.side_effect = RuntimeError("OpenRouter down")

        with mock.patch.object(
            consumers.rag_registry, "get_engine", return_value=engine
        ), mock.patch.object(consumers, "apply_retrieval_depth"):
            frames = self.collect(batch.job_id)

        self.assertIn("OpenRouter down", frames[1]["error"])
        self.assertEqual(frames[-1]["status"], "COMPLETE")
        self.assertFalse(AnalysisResult.objects.filter(batch=batch).exists())

    # ── reconnecting to a finished batch ─────────────────────────────────────

    def test_a_finished_batch_is_replayed_instead_of_recomputed(self):
        batch = self.make_batch()
        AnalysisResult.objects.create(
            batch=batch,
            method=DENSE,
            ai_model=GPT,
            query=self.conversation.query,
            answer="answer from the first run",
            retrieved_chunks=[{"id": 7, "text": "chunk text", "score": 0.83}],
            evaluation_metrics=[],
        )

        with mock.patch.object(consumers.rag_registry, "get_engine") as get_engine:
            frames = self.collect(batch.job_id)

        get_engine.assert_not_called()
        self.assertEqual(frames[0]["status"], "REPLAYING")
        replayed = self.results_in(frames)
        self.assertEqual(replayed[0]["answer"], "answer from the first run")
        self.assertTrue(replayed[0]["replayed"])
        self.assertEqual(frames[-1]["status"], "COMPLETE")
        self.assertEqual(AnalysisResult.objects.filter(batch=batch).count(), 1)

    def test_a_partly_finished_batch_replays_what_it_has_and_runs_the_rest(self):
        batch = self.make_batch(models=(GPT, GEMINI))
        AnalysisResult.objects.create(
            batch=batch,
            method=DENSE,
            ai_model=GPT,
            query=self.conversation.query,
            answer="already done",
            retrieved_chunks=[],
            evaluation_metrics=[],
        )
        engine = make_engine()

        with mock.patch.object(
            consumers.rag_registry, "get_engine", return_value=engine
        ), mock.patch.object(consumers, "apply_retrieval_depth"):
            frames = self.collect(batch.job_id)

        results = self.results_in(frames)
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0].get("replayed"))
        self.assertEqual(results[0]["answer"], "already done")
        self.assertIsNone(results[1].get("replayed"))
        # Only the missing variant was computed.
        engine.run_analysis.assert_called_once()
        self.assertEqual(AnalysisResult.objects.filter(batch=batch).count(), 2)

    def test_a_batch_without_a_stored_config_runs_the_full_matrix(self):
        # Batches created before the config field existed must still run.
        batch = AnalysisBatch.objects.create(
            user=self.user,
            conversation=self.conversation,
            query=self.conversation.query,
        )
        cache.set(
            f"job_input_{batch.job_id}",
            {
                "username": self.user.username,
                "query": self.conversation.query,
                "document_id": str(self.document.pk),
                "conversation_id": str(self.conversation.pk),
            },
            300,
        )
        engine = make_engine()

        with mock.patch.object(
            consumers.rag_registry, "get_engine", return_value=engine
        ), mock.patch.object(consumers, "apply_retrieval_depth"):
            frames = self.collect(batch.job_id, max_frames=40)

        self.assertEqual(frames[0]["expected_count"], 9)
        self.assertEqual(len(self.results_in(frames)), 9)
        self.assertEqual(AnalysisResult.objects.filter(batch=batch).count(), 9)
