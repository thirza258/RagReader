"""The public evaluation contract also runs without model or Django services."""
import copy
import unittest

from evaluation.contracts import RAGAS_ANSWER_METRICS, ragas_only_evaluation


class AnswerEvaluationContractTests(unittest.TestCase):
    def test_ragas_scores_and_statuses_are_allowlisted_without_changing_retrieval(self):
        original = {
            "chunk_evaluation": {"precision_k": 0.5, "recall_k": 1.0, "f1_k": 2 / 3},
            "response_evaluation": {
                "faithfulness": 0, "answer_relevancy": None, "factual_correctness": 0.9,
                "rougeL_f1": 0.7, "answer_coverage": 1,
            },
            "response_evaluation_details": {
                "framework": "ragas", "judge_model": "fixture/judge",
                "metrics": {
                    "faithfulness": {"status": "completed"},
                    "answer_relevancy": {"status": "unavailable", "reason": "Timeout"},
                    "rougeL_f1": {"status": "completed"},
                },
            },
            "module_trace": {"enabled": ["hyde"]},
        }
        before = copy.deepcopy(original)
        filtered = ragas_only_evaluation(original)
        self.assertEqual(list(filtered["response_evaluation"]), list(RAGAS_ANSWER_METRICS))
        self.assertEqual(filtered["response_evaluation"]["faithfulness"], 0)
        self.assertIsNone(filtered["response_evaluation"]["answer_relevancy"])
        self.assertEqual(filtered["chunk_evaluation"], original["chunk_evaluation"])
        self.assertEqual(filtered["module_trace"], original["module_trace"])
        self.assertNotIn("rougeL_f1", filtered["response_evaluation_details"]["metrics"])
        self.assertEqual(filtered["response_evaluation_details"]["metrics"]["answer_relevancy"]["reason"], "Timeout")
        self.assertEqual(original, before)

    def test_earlier_faithfulness_is_not_misrepresented_as_ragas(self):
        for details in (None, {}, {"framework": "custom-judge"}):
            with self.subTest(details=details):
                filtered = ragas_only_evaluation({
                    "response_evaluation": {"faithfulness": 0.95, "rougeL_f1": 0.7},
                    "response_evaluation_details": details,
                    "chunk_evaluation": {"precision_k": 1},
                })
                self.assertEqual(filtered["response_evaluation"], {})
                self.assertNotIn("response_evaluation_details", filtered)
                self.assertEqual(filtered["chunk_evaluation"], {"precision_k": 1})

    def test_missing_ragas_scores_are_unavailable_and_empty_evaluations_stay_empty(self):
        filtered = ragas_only_evaluation({"response_evaluation_details": {"framework": "ragas"}})
        self.assertEqual(filtered["response_evaluation"], dict.fromkeys(RAGAS_ANSWER_METRICS))
        self.assertEqual(filtered["response_evaluation_details"]["metrics"], {})
        self.assertEqual(ragas_only_evaluation({}), {})
