"""Module behavior and rerun boundaries, with network/model calls replaced."""
import json
import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

from django.test import SimpleTestCase, TestCase, override_settings

from common.analysis_modules import RAG_MODULE_IDS, normalize_modules
from common.constant import build_pipeline_config, normalize_analysis_config
from pipeline.analysis_modules import AnalysisModules, context_text, fuse_rankings, pack_context
from pipeline.base_pipeline import BasePipeline
from rag.rag_service import config_fingerprint
from router.models import AnalysisBatch, AnalysisResult, Conversation, Document, GuestUser
from router.analysis import has_completed_analysis
from evaluation.models import GroundTruthResponse

CORPUS = [
    {"chunk_id": 1, "text": "Solar panels convert sunlight into electricity."},
    {"chunk_id": 2, "text": "Batteries store electricity for use at night."},
    {"chunk_id": 3, "text": "Wind turbines generate electricity from wind."},
    {"chunk_id": 4, "text": "Cats sleep on warm blankets."},
    {"chunk_id": 5, "text": "Solar output depends on daylight and panel efficiency."},
    {"chunk_id": 6, "text": "The battery capacity is ten kilowatt hours."},
]
LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


class FakeRag:
    def __init__(self, corpus=CORPUS):
        self.documents = [d["text"] for d in corpus]
        self.document_metadata = [{"chunk_id": d["chunk_id"]} for d in corpus]
        self.top_k = 2
        self.queries = []

    def retrieve(self, query):
        self.queries.append(query)
        weights = [sum(word in text.lower() for word in query.lower().split()) for text in self.documents]
        order = sorted(range(len(weights)), key=lambda i: weights[i], reverse=True)
        return [{"text": self.documents[i], **self.document_metadata[i], "score": weights[i]} for i in order[:self.top_k]]

    def _get_embeddings(self, texts):
        return [[1 + text.lower().count("solar"), 1 + text.lower().count("battery"), 1 + text.lower().count("wind")] for text in texts]


def make_runner(modules, responses=None, examples=None, corpus=CORPUS):
    responses = responses or {}
    def generate(prompt):
        module = prompt.splitlines()[0].split(": ")[1]
        if module in responses:
            value = responses[module]
            return value(prompt) if callable(value) else value
        defaults = {
            "rewrite_retrieve_read": '{"queries": ["solar daylight efficiency"]}',
            "step_back": '{"queries": ["renewable electricity generation principles"]}',
            "rag_fusion": '{"queries": ["solar daylight", "battery storage", "solar daylight"]}',
            "hyde": "Hypothetical battery stores sunlight overnight; the invented cost is $999.",
            "raptor": "Solar energy and battery storage provide electricity.",
            "adaptive_rag": '{"route": "single"}',
            "self_route": '{"sufficient": false}',
            "crag": '{"relevant_ids": [1, 2]}',
            "contextual_learning": '{"examples": [{"question": "What stores electricity?", "answer": "Batteries."}]}',
            "flare": '{"sentence": "Battery capacity is ten kilowatt hours.", "needs_retrieval": true, "done": true}',
        }
        return defaults[module]
    pipeline = SimpleNamespace(
        config=build_pipeline_config({"modules": modules, "top_k": 2}, "openai/gpt-4o-mini"),
        method="dense", rag=FakeRag(corpus),
        llm=mock.Mock(generate=mock.Mock(side_effect=generate)),
    )
    pipeline.llm.rag_generate.return_value = "An answer grounded in the source."
    return AnalysisModules(pipeline, 123, examples=examples)


@override_settings(CACHES=LOCMEM)
class ModuleBehaviorTests(SimpleTestCase):
    def test_fusion_votes_once_per_chunk_per_ranking_and_preserves_ties(self):
        a, b, c = CORPUS[:3]
        result = fuse_rankings([[a, a, b], [b, c, a]], 3, 60)
        self.assertEqual([d["chunk_id"] for d in result], [1, 2, 3])
        self.assertAlmostEqual(result[0]["score"], 1 / 61 + 1 / 63)
        self.assertAlmostEqual(result[1]["score"], 1 / 63 + 1 / 61)

    def test_pack_context_deduplicates_and_reports_the_exact_text_used(self):
        packed = pack_context([CORPUS[0], CORPUS[0], CORPUS[1]], 90)
        self.assertEqual(len({d["chunk_id"] for d in packed}), len(packed))
        self.assertLessEqual(len(context_text(packed)), 90)
        self.assertTrue(CORPUS[1]["text"].startswith(packed[-1]["text"]))

    def test_module_selection_is_explicit_deduplicated_and_order_independent(self):
        self.assertEqual(normalize_analysis_config(None)["modules"], [])
        for invalid in [None, True, "hyde", {"hyde": True}, [None, {}, 1]]:
            self.assertEqual(normalize_modules(invalid), [])
        self.assertEqual(normalize_modules(["hyde", "unknown", "hyde"]), ["hyde"])
        a = build_pipeline_config({"modules": ["hyde", "rag_fusion"]})
        b = build_pipeline_config({"modules": ["rag_fusion", "hyde"]})
        self.assertEqual(config_fingerprint(a), config_fingerprint(b))
        self.assertNotEqual(config_fingerprint(a), config_fingerprint(build_pipeline_config()))

    def test_hyde_retrieves_with_hypothesis_but_reader_sees_only_source(self):
        runner = make_runner(["hyde"])
        result = runner.run("How is solar energy stored?")
        queries = result["module_trace"]["queries"]
        self.assertTrue(any("$999" in q for q in queries))
        question, context = runner.llm.rag_generate.call_args.args
        self.assertEqual(question, "How is solar energy stored?")
        self.assertNotIn("$999", context)
        self.assertTrue(set(result["chunk_ids"]).issubset({d["chunk_id"] for d in CORPUS}))

    def test_rrf_hybrid_uses_both_engines_without_mutating_their_depth(self):
        runner = make_runner(["rrf_hybrid"])
        runner._sparse_engine = FakeRag(list(reversed(CORPUS)))
        result = runner.run("battery")
        self.assertEqual(runner.pipeline.rag.top_k, 2)
        self.assertEqual(runner._sparse_engine.top_k, 2)
        self.assertTrue(runner._sparse_engine.queries)
        self.assertEqual(result["module_trace"]["steps"][0]["module"], "rrf_hybrid")
        self.assertTrue(all(0 < d["score"] < 0.04 for d in result["context"]))

    def test_query_modules_search_original_and_distinct_variations(self):
        for module in ("rewrite_retrieve_read", "step_back", "rag_fusion"):
            with self.subTest(module=module):
                runner = make_runner([module])
                result = runner.run("How does solar work?")
                queries = result["module_trace"]["queries"]
                self.assertIn("How does solar work?", queries)
                self.assertGreater(len(queries), 1)
                self.assertEqual(len(queries), len(set(queries)))
                self.assertEqual(runner.llm.rag_generate.call_args.args[0], "How does solar work?")

    def test_malformed_expansion_falls_back_with_visible_status(self):
        runner = make_runner(["rag_fusion"], {"rag_fusion": "not JSON"})
        result = runner.run("solar")
        self.assertEqual(result["module_trace"]["steps"][0]["status"], "fallback")
        self.assertTrue(result["context"])

    def test_memory_is_reused_only_for_identical_document_content(self):
        def respond(prompt):
            return '{"queries": ["battery storage"]}' if "queries" in prompt else "memory of solar energy"
        with mock.patch("pipeline.analysis_modules.cache") as store:
            store.get.return_value = None
            runner = make_runner(["memo_rag"], {"memo_rag": respond})
            runner.run("solar")
            first_key = store.get.call_args.args[0]
            store.set.assert_called_once()
            store.get.return_value = "memory of solar energy"
            runner.run("battery")
            self.assertEqual(store.get.call_args.args[0], first_key)
            changed = make_runner(["memo_rag"], {"memo_rag": respond}, corpus=CORPUS[:2])
            changed.run("solar")
            self.assertNotEqual(store.get.call_args.args[0], first_key)

    def test_raptor_builds_multiple_levels_and_returns_source_ids(self):
        runner = make_runner(["raptor"])
        result = runner.run("solar battery")
        self.assertGreaterEqual(runner.llm.generate.call_count, 3)
        self.assertIn("3 summaries", result["module_trace"]["steps"][0]["detail"])
        self.assertTrue(all(d in [c["text"] for c in CORPUS] for d in [c["text"] for c in result["context"]]))

    def test_long_rag_expands_contiguous_source_groups(self):
        runner = make_runner(["long_rag"])
        result = runner.run("solar")
        self.assertGreater(len(result["context"]), runner.top_k)
        self.assertTrue({1, 2, 3, 4}.issubset(set(result["chunk_ids"])))
        self.assertEqual(context_text(result["context"]), runner.llm.rag_generate.call_args.args[1])

    def test_self_route_uses_long_context_only_when_evidence_is_insufficient(self):
        for sufficient, expected in [(True, 2), (False, 6)]:
            runner = make_runner(["self_route"], {"self_route": json.dumps({"sufficient": sufficient})})
            result = runner.run("solar")
            self.assertEqual(len(result["context"]), expected)

    def test_self_route_cannot_reintroduce_crag_rejections(self):
        runner = make_runner(["crag", "self_route"])
        result = runner.run("solar")
        self.assertTrue(result["context"])
        self.assertTrue(set(result["chunk_ids"]).issubset({1, 2}))
        self.assertTrue(set(result["chunk_ids"]).isdisjoint(runner.rejected_ids))
        self.assertIn("CRAG graded", result["module_trace"]["steps"][-1]["detail"])

    def test_crag_partial_failure_retains_rejections(self):
        def respond(prompt):
            if "queries" in prompt:
                raise RuntimeError("corrective query unavailable")
            return '{"relevant_ids": []}'
        runner = make_runner(["crag"], {"crag": respond})
        result = runner.run("solar")
        self.assertEqual(result["context"], [])
        self.assertEqual(result["module_trace"]["steps"][-1]["status"], "fallback")

    def test_flare_cannot_restore_a_previously_rejected_chunk(self):
        grades = []
        def grade(prompt):
            data = json.loads(prompt.rsplit("\n", 1)[-1])
            grades.append([doc["chunk_id"] for doc in data["chunks"]])
            return json.dumps({"relevant_ids": [1] if len(grades) == 1 else grades[-1]})
        def flare(prompt):
            if "Rewrite this proposed sentence" in prompt:
                return "Solar panels generate electricity."
            return '{"sentence": "cats sleep", "needs_retrieval": true, "done": true}'
        runner = make_runner(["crag", "flare"], {"crag": grade, "flare": flare})
        result = runner.run("solar cats")
        self.assertIn(4, grades[0])
        self.assertNotIn(4, grades[1])
        self.assertNotIn(4, result["chunk_ids"])

    def test_crag_never_accepts_ids_for_unseen_passages(self):
        runner = make_runner(["crag"], {"crag": mock.Mock(side_effect=[
            '{"relevant_ids": [2]}', '{"relevant_ids": []}',
        ])})
        evidence = [{"chunk_id": 1, "text": "a" * 30000}, {"chunk_id": 2, "text": "second"}]
        self.assertEqual(runner._grade("q", evidence), [])
        self.assertEqual(runner.llm.generate.call_count, 2)

    def test_long_context_keeps_retrieved_evidence_from_document_end(self):
        corpus = [{"chunk_id": 10, "text": "prefix " * 8000}, {"chunk_id": 99, "text": "The important battery fact is at the end."}]
        for module in ("self_route", "long_rag"):
            with self.subTest(module=module):
                runner = make_runner([module], corpus=corpus)
                result = runner.run("battery")
                self.assertIn(99, result["chunk_ids"])
                self.assertLessEqual(len(context_text(result["context"])), 48000)

    def test_contextual_learning_uses_saved_examples_without_current_answer(self):
        examples = [
            {"question": "solar", "answer": "TARGET SECRET"},
            {"question": "What stores electricity?", "answer": "Batteries."},
        ]
        runner = make_runner(["contextual_learning"], examples=examples)
        result = runner.run("solar")
        prompt = runner.llm.generate.call_args.args[0]
        self.assertIn("Batteries.", prompt)
        self.assertNotIn("TARGET SECRET", prompt)
        self.assertIn("saved Q&A", result["module_trace"]["steps"][0]["detail"])
        self.assertEqual(runner.llm.generate.call_count, 1)

    def test_contextual_learning_generates_examples_when_none_saved(self):
        runner = make_runner(["contextual_learning"])
        result = runner.run("solar")
        self.assertEqual(runner.llm.generate.call_count, 2)
        self.assertIn("generated from retrieved evidence", result["module_trace"]["steps"][0]["detail"])

    def test_crag_does_not_put_rejected_chunks_back_after_corrective_search(self):
        def respond(prompt):
            return '{"queries": ["battery storage"]}' if "queries" in prompt else '{"relevant_ids": []}'
        runner = make_runner(["crag"], {"crag": respond})
        result = runner.run("solar")
        self.assertEqual(result["context"], [])
        self.assertGreater(len(result["module_trace"]["queries"]), 1)
        self.assertEqual(runner.llm.rag_generate.call_args.args[1], "")

    def test_flare_retrieves_for_uncertain_sentence_and_regenerates_from_evidence(self):
        def respond(prompt):
            if "Rewrite this proposed sentence" in prompt:
                return "Battery capacity is ten kilowatt hours."
            return '{"sentence": "battery capacity", "needs_retrieval": true, "done": true}'
        runner = make_runner(["flare"], {"flare": respond})
        result = runner.run("solar")
        self.assertIn("battery capacity", result["module_trace"]["queries"])
        self.assertIn(6, result["chunk_ids"])
        self.assertEqual(context_text(result["context"]), runner.llm.rag_generate.call_args.args[1])

    def test_flare_stops_after_bounded_predictions(self):
        runner = make_runner(["flare"], {"flare": '{"sentence": "Solar works.", "needs_retrieval": false, "done": false}'})
        runner.run("solar")
        self.assertEqual(runner.llm.generate.call_count, 3)

    def test_adaptive_direct_skips_other_modules_without_retrieval(self):
        def respond(prompt):
            return '{"route": "direct"}' if "Classify" in prompt else "Hello!"
        runner = make_runner(RAG_MODULE_IDS, {"adaptive_rag": respond})
        result = runner.run("hello")
        self.assertEqual(result["context"], [])
        self.assertEqual(runner.pipeline.rag.queries, [])
        self.assertEqual(len(result["module_trace"]["steps"]), 13)
        self.assertEqual(result["module_trace"]["route"], "direct")

    def test_adaptive_multistep_retrieves_followups_using_previous_evidence(self):
        def respond(prompt):
            return '{"route": "multi"}' if "Classify" in prompt else '{"queries": ["battery capacity"]}'
        runner = make_runner(["adaptive_rag"], {"adaptive_rag": respond})
        result = runner.run("Compare solar generation and battery capacity")
        self.assertEqual(result["module_trace"]["route"], "multi")
        self.assertEqual(len(runner.pipeline.rag.queries), 3)
        self.assertIn("evidence", runner.llm.generate.call_args.args[0])


@override_settings(CACHES=LOCMEM)
class ModuleRunBoundaryTests(TestCase):
    def setUp(self):
        self.user = GuestUser.objects.create(username="module-user", email="modules@example.com")
        self.document = Document.objects.create(user=self.user, name="solar.txt", source_type="text")
        self.conversation = Conversation.objects.create(user=self.user, document=self.document, query="solar", response="chat", context="source")
        self.config = normalize_analysis_config({"methods": ["Dense Retrieval"], "models": ["openai/gpt-4o-mini"]})

    def start(self, modules):
        return self.client.post("/api/v1/start-analysis/", {"conversation_id": self.conversation.pk, "config": {**self.config, "modules": modules}}, content_type="application/json")

    def complete(self):
        baseline = AnalysisBatch.objects.create(user=self.user, conversation=self.conversation, query="solar", config=self.config, total_variants=1)
        AnalysisResult.objects.create(batch=baseline, method="Dense Retrieval", ai_model="openai/gpt-4o-mini", answer="baseline")
        return baseline

    def test_first_run_cannot_enable_modules_and_has_no_side_effects(self):
        response = self.start(["hyde"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AnalysisBatch.objects.count(), 0)
        self.assertEqual(self.start([]).status_code, 202)

    def test_incomplete_or_other_conversation_does_not_unlock_modules(self):
        batch = self.complete()
        batch.config = {**self.config, "methods": ["Dense Retrieval", "Sparse Retrieval"]}
        batch.save()
        self.assertFalse(has_completed_analysis(self.conversation.pk))
        self.assertEqual(self.start(["hyde"]).status_code, 400)
        other = Conversation.objects.create(user=self.user, document=self.document, query="other", response="", context="")
        batch.conversation = other
        batch.config = self.config
        batch.save()
        self.assertEqual(self.start(["hyde"]).status_code, 400)

    def test_modules_round_trip_and_turning_them_off_stays_off(self):
        self.complete()
        response = self.start(["hyde", "contextual_learning"])
        self.assertEqual(response.status_code, 202)
        batch_id = response.json()["batch_id"]
        status = self.client.get(f"/api/v1/analysis-status/{batch_id}/").json()
        self.assertTrue(status["modules_available"])
        self.assertEqual(status["config"]["modules"], ["hyde", "contextual_learning"])
        self.assertEqual(self.start([]).json()["config"]["modules"], [])

    def test_all_off_uses_original_pipeline_without_loading_auxiliary_data(self):
        pipeline = SimpleNamespace(config={"modules": []}, _run_core=mock.Mock(return_value={"answer": "baseline"}))
        with self.assertNumQueries(0):
            result = BasePipeline._run_analysis_core(pipeline, self.document, self.conversation)
        self.assertEqual(result["answer"], "baseline")
        pipeline._run_core.assert_called_once_with(self.document, "solar")

    def test_module_analysis_uses_exact_document_and_excludes_target_ground_truth(self):
        target = GroundTruthResponse.objects.create(conversation=self.conversation, response="TARGET SECRET")
        other = Conversation.objects.create(user=self.user, document=self.document, query="storage", response="", context="")
        GroundTruthResponse.objects.create(conversation=other, response="Batteries")
        pipeline = SimpleNamespace(config={"modules": ["contextual_learning"]}, method="dense", _build_index=mock.Mock())
        with mock.patch("pipeline.analysis_modules.AnalysisModules") as runner:
            BasePipeline._run_analysis_core(pipeline, self.document, self.conversation)
        pipeline._build_index.assert_called_once_with(self.user.username, self.document)
        examples = runner.call_args.kwargs["examples"]
        self.assertEqual(examples, [{"question": "storage", "answer": "Batteries"}])
        self.assertNotIn(target.response, json.dumps(examples))

    def test_status_preserves_module_trace_and_source_ids(self):
        batch = self.complete()
        result = batch.results.get()
        trace = {"enabled": ["hyde"], "route": "single", "steps": [], "queries": []}
        result.evaluation_metrics = [{"name": "module_trace", "value": trace}]
        result.retrieved_chunks = [{"id": 123, "text": "source"}]
        result.save()
        status = self.client.get(f"/api/v1/analysis-status/{batch.job_id}/").json()
        self.assertEqual(status["results"][0]["evaluation"]["module_trace"], trace)
        self.assertEqual(status["results"][0]["retrievedChunks"][0]["id"], 123)

    def test_queued_task_restores_modules_from_batch_without_config_argument(self):
        from router.tasks import run_single_analysis
        batch = self.complete()
        batch.results.all().delete()
        batch.config = {**self.config, "modules": ["hyde"]}
        batch.save()
        trace = {"enabled": ["hyde"], "route": "single", "steps": [], "queries": []}
        engine = mock.Mock(rag=SimpleNamespace(top_k=1))
        engine.run_analysis.return_value = {"answer": "module answer", "context": CORPUS[:1], "module_trace": trace}
        with mock.patch("router.tasks.rag_registry.get_engine", return_value=engine) as lookup:
            success = run_single_analysis(
                str(batch.job_id), self.user.username, self.conversation.query,
                {"method": "Dense Retrieval", "model": "openai/gpt-4o-mini"},
            )
        self.assertTrue(success)
        self.assertEqual(lookup.call_args.args[2]["modules"], ["hyde"])
        engine.run.assert_not_called()
        engine.run_analysis.assert_called_once_with(self.document.pk, self.conversation.pk)
        self.assertIn({"name": "module_trace", "value": trace}, batch.results.get().evaluation_metrics)
