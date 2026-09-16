"""Every module, every pair, and all modules over the real retrieval engines.

Only provider responses and NLTK's tokenizer are replaced. Dense similarity,
BM25, hybrid reranking, RRF, clustering, context packing and stage composition
all execute. These tests verify behavior, not live model answer quality.
"""
import itertools
import json
import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

import numpy as np
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from common.analysis_modules import MODULE_COMPATIBILITY, RAG_MODULE_IDS
from common.constant import build_pipeline_config
from dense_rag.dense_rag import DenseRAG
from sparse_rag.sparse_rag import SparseRAG
from hybrid_rag.hybrid_rag import HybridRAG, OllamaCrossEncoder, clear_cross_encoder_cache
from pipeline.analysis_modules import AnalysisModules, context_text
from router.tests_modules import CORPUS, LOCMEM

QUESTION = "How is solar electricity stored in a battery?"
ENGINES = {"dense": DenseRAG, "sparse": SparseRAG, "hybrid": HybridRAG}


def vector(text):
    words = ("solar", "battery", "electricity", "wind", "cats", "storage")
    return [1 + text.lower().count(word) for word in words]


class ProviderFixture:
    def __init__(self, route="single"):
        self.route = route
        self.calls = []
        self.answer_query = None
        self.answer_context = None

    def rag_generate(self, query, context):
        self.answer_query, self.answer_context = query, context
        return "Batteries store solar electricity."

    def generate(self, prompt):
        module = prompt.splitlines()[0].split(": ")[1]
        data = json.loads(prompt.rsplit("\n", 1)[-1])
        self.calls.append((module, data))
        if module == "adaptive_rag":
            if "Classify" in prompt:
                return json.dumps({"route": self.route})
            if "conversational request" in prompt:
                return "Hello!"
            return '{"queries": ["battery capacity"]}'
        if module in ("rewrite_retrieve_read", "step_back", "rag_fusion"):
            return '{"queries": ["solar efficiency", "battery storage", "renewable energy"]}'
        if module == "hyde":
            return "INVENTED_HYPOTHESIS: A battery stores solar energy."
        if module == "memo_rag":
            return '{"queries": ["battery storage"]}' if "memory" in data else "GENERATED_MEMORY: Solar electricity is stored."
        if module == "raptor":
            return "GENERATED_SUMMARY: Solar energy can be stored in batteries."
        if module == "crag":
            if "chunks" not in data:
                return '{"queries": ["battery capacity", "solar electricity"]}'
            return json.dumps({"relevant_ids": [d["chunk_id"] for d in data["chunks"] if "cats" not in d["text"].lower()]})
        if module == "self_route":
            return '{"sufficient": false}'
        if module == "flare":
            if "sentence" in data:
                return "The battery stores electricity."
            return '{"sentence": "battery capacity", "needs_retrieval": true, "done": true}'
        if module == "contextual_learning":
            if "target_question" in data:
                return '{"examples": [{"question": "What produces wind electricity?", "answer": "Wind turbines."}]}'
            self.answer_query, self.answer_context = data["question"], data["evidence"]
            return "Batteries store solar electricity."
        raise AssertionError(f"Unexpected stage: {module}")


@override_settings(CACHES=LOCMEM, OPENROUTER_API_KEY="test-only")
class ModuleCombinationTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        clear_cross_encoder_cache()
        client = mock.Mock()
        client.embeddings.create.side_effect = lambda input, **kwargs: SimpleNamespace(
            data=[SimpleNamespace(index=i, embedding=vector(text)) for i, text in enumerate(input)],
        )
        ollama = mock.Mock()
        ollama.embed.side_effect = lambda input, **kwargs: {"embeddings": [vector(t) for t in ([input] if isinstance(input, str) else input)]}
        self.patchers = [
            mock.patch("dense_rag.dense_rag.OpenAI", return_value=client),
            mock.patch("sparse_rag.sparse_rag.word_tokenize", side_effect=str.split),
            mock.patch.object(OllamaCrossEncoder, "client", new_callable=mock.PropertyMock, return_value=ollama),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(clear_cross_encoder_cache)

    def verify_combination(self, method, modules, route="single"):
        config = {**build_pipeline_config({"modules": modules, "top_k": 3}), "remove_stop_words": False}
        rag = ENGINES[method](config)
        rag.index_documents(CORPUS)
        model = ProviderFixture(route)
        runner = AnalysisModules(SimpleNamespace(method=method, config=config, rag=rag, llm=model), 1)
        result = runner.run(QUESTION if route != "direct" else "hello")
        trace = result["module_trace"]
        self.assertEqual(set(trace["enabled"]), set(modules))
        self.assertFalse([step for step in trace["steps"] if step["status"] == "fallback"], trace)
        self.assertEqual(trace["route"], route)
        self.assertEqual(len(result["chunk_ids"]), len(set(result["chunk_ids"])))
        self.assertTrue(set(result["chunk_ids"]).issubset({d["chunk_id"] for d in CORPUS}))
        if route == "direct":
            self.assertEqual(result["context"], [])
            self.assertEqual({m for m, _ in model.calls}, {"adaptive_rag"})
            self.assertEqual({s["module"] for s in trace["steps"] if s["status"] == "skipped"}, set(modules) - {"adaptive_rag"})
            return
        self.assertTrue(result["context"])
        self.assertEqual({s["module"] for s in trace["steps"] if s["status"] == "completed"}, set(modules))
        self.assertEqual(model.answer_query, QUESTION)
        self.assertEqual(model.answer_context, context_text(result["context"]))
        if "crag" in modules:
            self.assertNotIn(4, result["chunk_ids"])
        for doc in result["context"]:
            original = next(d for d in CORPUS if d["chunk_id"] == doc["chunk_id"])
            self.assertTrue(original["text"].startswith(doc["text"]))
            self.assertTrue(np.isfinite(doc["score"]) if doc.get("score") is not None else True)
        self.assertNotIn("INVENTED_", model.answer_context)
        self.assertNotIn("GENERATED_", model.answer_context)
        self.assertEqual(getattr(rag, "final_top_k", None) or rag.top_k, 3)
        if method == "hybrid":
            self.assertEqual(rag.dense_engine.top_k, config["child_top_k"])
            self.assertEqual(rag.sparse_engine.top_k, config["child_top_k"])

    def test_compatibility_catalogue_covers_every_module_once_and_references_valid_ids(self):
        declared = [m for stage in MODULE_COMPATIBILITY["stages"] for m in stage["modules"]]
        self.assertCountEqual(declared, RAG_MODULE_IDS)
        self.assertTrue(MODULE_COMPATIBILITY["all_modules_supported"])
        for rule in MODULE_COMPATIBILITY["rules"]:
            self.assertTrue(set(rule["modules"]).issubset(RAG_MODULE_IDS))
            self.assertLessEqual(rule["min_selected"], len(rule["modules"]))
            self.assertGreater(rule["min_selected"], 0)


def combination_case(method, modules, route="single"):
    def test(self):
        self.verify_combination(method, modules, route)
    return test


# Generate separate discoverable tests, so a failing pair is named in CI.
for method in ENGINES:
    for size in (1, 2):
        for modules in itertools.combinations(RAG_MODULE_IDS, size):
            name = f"test_{method}_{'_and_'.join(modules)}"
            setattr(ModuleCombinationTests, name, combination_case(method, modules))
    for route in ("single", "multi", "direct"):
        setattr(ModuleCombinationTests, f"test_{method}_all_modules_{route}", combination_case(method, RAG_MODULE_IDS, route))
