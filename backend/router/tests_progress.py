"""Progress follows actual execution, including thread and async boundaries."""
import asyncio
from unittest import mock

from asgiref.sync import async_to_sync, sync_to_async
from django.test import SimpleTestCase, override_settings

from common.analysis_modules import RAG_MODULE_IDS
from common.analysis_progress import progress_scope, progress_stage, report_progress
from router.tests_modules import make_runner, LOCMEM
from router.consumers import AnalysisConsumer


class ProgressScopeTests(SimpleTestCase):
    def test_parallel_contexts_follow_worker_and_async_metric_calls_without_leaking(self):
        async def run():
            outputs = [[], []]
            async def score():
                await asyncio.sleep(0)
                report_progress("metric", "faithfulness", "completed", score=0.5)
            def worker():
                progress_stage("evaluate", "Scoring.")
                async_to_sync(score)()
            async def variant(events):
                with progress_scope(events.append):
                    await sync_to_async(worker, thread_sensitive=False)()
                report_progress("module", "hyde", "running", "Must not leak.")
            await asyncio.gather(*(variant(events) for events in outputs))
            return outputs
        for events in async_to_sync(run)():
            self.assertEqual([(event["kind"], event["id"]) for event in events], [("stage", "evaluate"), ("metric", "faithfulness")])
            self.assertEqual(events[-1]["stage"], "evaluate")

    def test_failed_stage_preserves_completed_stage_and_drops_late_callbacks(self):
        events = []
        with self.assertRaises(RuntimeError), progress_scope(events.append) as reporter:
            progress_stage("search", "Searching.")
            progress_stage("answer", "Writing.")
            raise RuntimeError("fixture")
        reporter.emit("metric", "late", "completed")
        self.assertEqual([(event["id"], event["status"]) for event in events], [("search", "running"), ("search", "completed"), ("answer", "running"), ("answer", "failed")])

    def test_lost_socket_does_not_abort_computation(self):
        consumer = AnalysisConsumer()
        consumer.job_id = "fixture"
        consumer.stream_available = True
        consumer.send = mock.AsyncMock(side_effect=ConnectionError("closed"))
        engine = mock.Mock()
        engine.is_initialized.return_value = True
        engine.run_analysis.return_value = {"answer": "preserved"}
        with mock.patch("router.consumers.rag_registry.get_engine", return_value=engine), mock.patch("router.consumers.apply_retrieval_depth"):
            response = async_to_sync(consumer.run_variant)("Dense Retrieval", "openai/test", {"top_k": 2, "child_top_k": 4, "modules": []}, "fixture", "1", "1")
        self.assertEqual(response["answer"], "preserved")
        self.assertFalse(consumer.stream_available)


@override_settings(CACHES=LOCMEM)
class ModuleProgressTests(SimpleTestCase):
    def test_query_expansion_and_fallback_are_visible_during_execution(self):
        events = []
        def fail(prompt):
            self.assertEqual(events[-1]["id"], "rag_fusion")
            self.assertEqual(events[-1]["status"], "running")
            return "not JSON"
        runner = make_runner(["rag_fusion", "hyde"], {"rag_fusion": fail})
        with progress_scope(events.append):
            result = runner.run("How is solar stored?")
        states = {(event["id"], event["status"]) for event in events}
        self.assertIn(("rag_fusion", "fallback"), states)
        self.assertIn(("hyde", "running"), states)
        self.assertIn(("hyde", "completed"), states)
        self.assertTrue(result["answer"])
        self.assertEqual([event["id"] for event in events if event["kind"] == "stage" and event["status"] == "running"], ["search", "evidence", "answer"])

    def test_direct_route_reports_skips_before_answer_generation(self):
        events = []
        def respond(prompt):
            if "Classify" in prompt:
                return '{"route": "direct"}'
            skipped = {event["id"] for event in events if event["status"] == "skipped"}
            self.assertTrue({"search", "evidence", "hyde", "flare"}.issubset(skipped))
            self.assertEqual(events[-1]["id"], "answer")
            return "Hello!"
        runner = make_runner(RAG_MODULE_IDS, {"adaptive_rag": respond})
        with progress_scope(events.append):
            result = runner.run("hello")
        self.assertEqual(result["module_trace"]["route"], "direct")
        self.assertFalse(any(event["kind"] == "activity" for event in events))

    def test_flare_followup_search_keeps_answer_stage_active(self):
        events = []
        runner = make_runner(["flare"])
        with progress_scope(events.append):
            runner.run("solar storage")
        searches = [event for event in events if event["kind"] == "activity"]
        self.assertEqual([event["stage"] for event in searches], ["search", "answer"])
        self.assertTrue(all(event["queries"] for event in searches))
