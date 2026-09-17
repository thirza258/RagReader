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
import threading
from unittest import mock

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

from asgiref.sync import async_to_sync
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.core.cache import cache
from django.test import TransactionTestCase, override_settings
from common.analysis_progress import progress_stage, report_progress
from common.errors import PipelineError

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
        "response_evaluation": {"factual_correctness": 0.4, "faithfulness": 0.8},
        "response_evaluation_details": {"framework": "ragas", "metrics": {}},
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

    def collect(self, job_id, max_frames=200):
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

    def test_selected_k_and_ragas_metrics_survive_live_results_and_replay(self):
        batch = self.make_batch(top_k=8)
        with mock.patch.object(consumers.rag_registry, "get_engine", return_value=make_engine()):
            live = self.results_in(self.collect(batch.job_id))
        replay = self.results_in(self.collect(batch.job_id))
        for frame in live + replay:
            self.assertEqual(frame["top_k"], 8)
            self.assertEqual(set(frame["evaluation"]["response_evaluation"]), {
                "faithfulness", "answer_relevancy", "factual_correctness",
            })
            self.assertEqual(frame["evaluation"]["response_evaluation"]["faithfulness"], 0.8)
        self.assertEqual(len(live), 1)
        self.assertEqual(len(replay), 1)

    # ── failure to even start ────────────────────────────────────────────────

    def test_malformed_id_is_a_terminal_error_frame(self):
        frames = self.collect("invalid-id")
        self.assertEqual(frames[0]["error_code"], "invalid_job_id")
        self.assertTrue(frames[0]["terminal"])

    def test_canonical_id_and_database_binding_override_stale_cache(self):
        batch = self.make_batch()
        cache.set(f"job_input_{batch.job_id}", {"username": "wrong", "document_id": "999", "conversation_id": "999"})
        engine = make_engine()
        with mock.patch.object(consumers.rag_registry, "get_engine", return_value=engine):
            frames = self.collect(batch.job_id.hex.upper())
        engine.run_analysis.assert_called_once_with(str(self.document.pk), str(self.conversation.pk))
        self.assertTrue(all(frame["batch_id"] == str(batch.job_id) for frame in frames))

    def test_embedding_failure_is_persisted_and_replayed_without_retry(self):
        batch = self.make_batch()
        engine = make_engine()
        engine.run_analysis.side_effect = PipelineError("provider_timeout", "Embedding timed out. Try again.", retryable=True)
        with mock.patch.object(consumers.rag_registry, "get_engine", return_value=engine):
            first = self.collect(batch.job_id)
            replay = self.collect(batch.job_id)
        engine.run_analysis.assert_called_once()
        self.assertEqual(first[-1]["outcome"], "failed")
        self.assertEqual(replay[0]["status"], "REPLAYING")
        error = next(frame for frame in replay if "error" in frame)
        self.assertEqual(error["error_code"], "provider_timeout")
        self.assertTrue(error["retryable"])
        self.assertEqual(AnalysisResult.objects.get(batch=batch).error_message, error["error"])

    def test_reconnect_waits_for_inflight_work_then_resumes_same_batch_once(self):
        batch = self.make_batch(models=(GPT, GEMINI))
        release = threading.Event()
        engine = make_engine()
        def analyze(*args):
            progress_stage("search", "Embedding the question.")
            if not release.wait(timeout=10):
                raise TimeoutError("Follower never attached")
            return ANALYSIS_RESPONSE
        engine.run_analysis.side_effect = analyze

        async def run():
            app = URLRouter(router.urls.websocket_urlpatterns)
            first = WebsocketCommunicator(app, f"/ws/analysis/{batch.job_id}/")
            second = WebsocketCommunicator(app, f"/ws/analysis/{batch.job_id}/")
            await first.connect()
            try:
                while True:
                    frame = await first.receive_json_from(timeout=5)
                    if frame.get("event", {}).get("id") == "search":
                        break
                await second.connect()
                while True:
                    frame = await second.receive_json_from(timeout=5)
                    if frame.get("status") == "WAITING":
                        break
                self.assertEqual(engine.run_analysis.call_count, 1)
                await first.disconnect()
                release.set()
                frames = []
                while True:
                    frame = await second.receive_json_from(timeout=5)
                    frames.append(frame)
                    if frame.get("status") in ("ERROR", "COMPLETE"):
                        break
                self.assertEqual(frames[-1]["status"], "COMPLETE")
                self.assertEqual(frames[-1]["completed"], 2)
            finally:
                release.set()
                await second.disconnect()

        with mock.patch.object(consumers.rag_registry, "get_engine", return_value=engine):
            async_to_sync(run)()
        self.assertEqual(engine.run_analysis.call_count, 2)
        self.assertEqual(AnalysisResult.objects.filter(batch=batch).count(), 2)
        batch.refresh_from_db()
        self.assertIsNone(batch.execution_token)

    def test_an_expired_job_cache_falls_back_to_db_and_runs(self):
        batch = self.make_batch()
        cache.delete(f"job_input_{batch.job_id}")
        engine = make_engine()

        with mock.patch.object(
            consumers.rag_registry, "get_engine", return_value=engine
        ), mock.patch.object(consumers, "apply_retrieval_depth"):
            frames = self.collect(batch.job_id)

        self.assertEqual(frames[0]["status"], "CONFIG")
        self.assertEqual(frames[-1]["status"], "COMPLETE")

    def test_a_missing_batch_row_is_reported(self):
        cache.set(
            "job_input_11111111-1111-1111-1111-111111111111",
            {"username": "alice", "query": "q"},
            300,
        )

        frames = self.collect("11111111-1111-1111-1111-111111111111")

        self.assertEqual(frames[0]["error_code"], "job_not_found")
        self.assertTrue(frames[0]["terminal"])

    def test_unknown_batch_and_no_cache_reports_error(self):
        frames = self.collect("22222222-2222-2222-2222-222222222222")
        self.assertEqual(frames[0]["error_code"], "job_not_found")
        self.assertTrue(frames[0]["terminal"])

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

        result = self.results_in(frames)[0]
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

        self.assertEqual(frames[-1]["status"], "COMPLETE")
        self.assertEqual(frames[-1]["outcome"], "completed")
        self.assertEqual(frames[-1]["failed"], 0)

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

    def test_module_trace_is_saved_and_replayed_from_the_batch_configuration(self):
        batch = self.make_batch()
        batch.config["modules"] = ["hyde", "contextual_learning"]
        batch.save()
        trace = {"enabled": batch.config["modules"], "route": "single", "steps": [], "queries": ["expanded query"]}
        engine = make_engine(response={**ANALYSIS_RESPONSE, "module_trace": trace})
        with mock.patch.object(consumers.rag_registry, "get_engine", return_value=engine) as lookup:
            frames = self.collect(batch.job_id)
        self.assertEqual(lookup.call_args.args[2]["modules"], trace["enabled"])
        self.assertEqual(self.results_in(frames)[0]["evaluation"]["module_trace"], trace)
        replay = self.collect(batch.job_id)
        self.assertEqual(self.results_in(replay)[0]["evaluation"]["module_trace"], trace)

    def test_ragas_details_and_null_scores_survive_stream_storage_and_rest(self):
        batch = self.make_batch()
        details = {"framework": "ragas", "provider": "openrouter", "judge_model": GPT, "metrics": {"faithfulness": {"status": "unavailable", "reason": "Evaluation timed out."}}}
        response = {**ANALYSIS_RESPONSE, "evaluation": {**ANALYSIS_RESPONSE["evaluation"], "response_evaluation": {"faithfulness": None, "factual_correctness": 0.8}, "response_evaluation_details": details}}
        with mock.patch.object(consumers.rag_registry, "get_engine", return_value=make_engine(response=response)):
            frames = self.collect(batch.job_id)
        streamed = self.results_in(frames)[0]["evaluation"]
        replayed = self.results_in(self.collect(batch.job_id))[0]["evaluation"]
        restored = self.client.get(f"/api/v1/analysis-status/{batch.job_id}/").json()["results"][0]["evaluation"]
        for evaluation in (streamed, replayed, restored):
            self.assertEqual(evaluation["response_evaluation_details"], details)
            self.assertIsNone(evaluation["response_evaluation"]["faithfulness"])
            self.assertEqual(evaluation["response_evaluation"]["factual_correctness"], 0.8)

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

    def test_preparation_is_owned_by_analysis_for_the_bound_document(self):
        batch = self.make_batch()
        engine = make_engine(is_initialized=False)

        with mock.patch.object(
            consumers.rag_registry, "get_engine", return_value=engine
        ), mock.patch.object(consumers, "apply_retrieval_depth"):
            frames = self.collect(batch.job_id)

        engine.init.assert_not_called()
        engine.run_analysis.assert_called_once_with(str(batch.conversation.document_id), str(batch.conversation_id))
        self.assertEqual(len(self.results_in(frames)), 1)

    def test_one_failing_variant_does_not_sink_the_others(self):
        batch = self.make_batch(models=(GPT, GEMINI))
        engine = make_engine()

        def get_engine(method, model, config=None):
            if model == GPT:
                raise ValueError("Engine not found")
            return engine

        with mock.patch.object(
            consumers.rag_registry, "get_engine", side_effect=get_engine
        ), mock.patch.object(consumers, "apply_retrieval_depth"):
            frames = self.collect(batch.job_id)

        errors = [f for f in frames if "error" in f]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["error_code"], "analysis_failed")
        self.assertNotIn("Engine not found", errors[0]["error"])
        self.assertEqual(len(self.results_in(frames)), 1)
        self.assertEqual(frames[-1]["status"], "COMPLETE")
        self.assertEqual(AnalysisResult.objects.filter(batch=batch).count(), 2)
        self.assertEqual(frames[-1]["outcome"], "partial_failure")

    def test_a_variant_whose_analysis_raises_is_reported_and_skipped(self):
        batch = self.make_batch()
        engine = make_engine()
        engine.run_analysis.side_effect = RuntimeError("OpenRouter down")

        with mock.patch.object(
            consumers.rag_registry, "get_engine", return_value=engine
        ), mock.patch.object(consumers, "apply_retrieval_depth"):
            frames = self.collect(batch.job_id)

        self.assertEqual(next(frame["error_code"] for frame in frames if "error" in frame), "analysis_failed")
        self.assertTrue(any(frame.get("event", {}).get("status") == "failed" for frame in frames))
        self.assertEqual(frames[-1]["status"], "COMPLETE")
        self.assertTrue(AnalysisResult.objects.filter(batch=batch, error_code="analysis_failed").exists())
        self.assertEqual(frames[-1]["outcome"], "failed")

    # ── reconnecting to a finished batch ─────────────────────────────────────

    def test_live_events_arrive_before_result_and_identify_each_shared_engine_attempt(self):
        batch = self.make_batch(models=(GPT, GEMINI))
        release = threading.Event()
        engine = make_engine()

        def analyze(*args):
            progress_stage("search", "Searching the document.")
            report_progress("module", "hyde", "running", "Preparing a hypothesis.")
            if not release.wait(timeout=5):
                raise TimeoutError("The consumer did not stream the live event before the result.")
            report_progress("module", "hyde", "completed", "Retrieved source evidence.")
            progress_stage("answer", "Writing the answer.")
            progress_stage("evaluate", "Scoring the answer.")
            progress_stage("evaluate", "Evaluation finished.", status="completed")
            return ANALYSIS_RESPONSE

        engine.run_analysis.side_effect = analyze

        async def run():
            communicator = WebsocketCommunicator(URLRouter(router.urls.websocket_urlpatterns), f"/ws/analysis/{batch.job_id}/")
            await communicator.connect()
            frames = []
            try:
                for _ in range(100):
                    frame = await communicator.receive_json_from(timeout=5)
                    frames.append(frame)
                    if frame.get("event", {}).get("id") == "hyde" and not release.is_set():
                        self.assertFalse(self.results_in(frames))
                        self.assertEqual(frame["event"]["status"], "running")
                        release.set()
                    if frame.get("status") == "COMPLETE":
                        break
                self.assertEqual(frames[-1]["status"], "COMPLETE")
            finally:
                release.set()
                await communicator.disconnect()
            return frames

        with mock.patch.object(consumers.rag_registry, "get_engine", return_value=engine), mock.patch.object(consumers, "apply_retrieval_depth"):
            frames = async_to_sync(run)()
        attempts = []
        for model in (GPT, GEMINI):
            updates = [frame for frame in frames if frame.get("status") == "STAGE_PROGRESS" and frame["aiModel"] == model]
            self.assertTrue(updates)
            self.assertTrue(all(frame["batch_id"] == str(batch.job_id) and frame["method"] == DENSE for frame in updates))
            self.assertEqual([frame["sequence"] for frame in updates], list(range(1, len(updates) + 1)))
            self.assertEqual(len({frame["attempt_id"] for frame in updates}), 1)
            attempts.append(updates[0]["attempt_id"])
            result_index = next(index for index, frame in enumerate(frames) if frame.get("aiModel") == model and "answer" in frame)
            self.assertLess(frames.index(updates[-1]), result_index)
        self.assertEqual(len(set(attempts)), 2)
        self.assertEqual(AnalysisResult.objects.filter(batch=batch).count(), 2)

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
