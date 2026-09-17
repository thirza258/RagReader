"""Retrieval overlap and Ragas evaluation through OpenRouter's remote APIs."""
import asyncio
import logging
import math
import os

from asgiref.sync import async_to_sync
from django.conf import settings
from openai import AsyncOpenAI

from ai_handler.llm import OPENROUTER_BASE_URL, OPENROUTER_HEADERS
from common.constant import DEFAULT_EMBEDDING_MODEL, DEFAULT_JUDGE_MODEL
from common.analysis_progress import report_progress
from evaluation.contracts import RAGAS_ANSWER_METRICS

# Evaluation does not need Ragas usage telemetry.
os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")
logger = logging.getLogger(__name__)
METRIC_TIMEOUT_SECONDS = 120
METRICS = RAGAS_ANSWER_METRICS

def calculate_recall_K(chunks, ground_truth_chunks):
    """
    Menghitung Recall@K untuk evaluasi retrieval.
    
    Args:
        chunks (list): List string berisi chunk yang diambil (retrieved).
        ground_truth_chunks (list): List string berisi chunk yang relevan (ground truth).
    Returns:
        float: Recall@K (0.0 hingga 1.0).
    """
    try:
        if not ground_truth_chunks:
            return 0.0
        
        retrieved_set = set(chunks)
        relevant_set = set(ground_truth_chunks)
        
        true_positives = len(retrieved_set.intersection(relevant_set))
        recall_k = true_positives / len(relevant_set)
        
        return recall_k
    except Exception as e:
        print(f"Error in calculate_recall_K: {e}")
        return 0.0

def calculate_precision_K(chunks, ground_truth_chunks):
    """
    Menghitung Precision@K untuk evaluasi retrieval.
    
    Args:
        chunks (list): List string berisi chunk yang diambil (retrieved).
        ground_truth_chunks (list): List string berisi chunk yang relevan (ground truth).
    Returns:
        float: Precision@K (0.0 hingga 1.0).
    """
    try:
        if not chunks:
            return 0.0
        
        retrieved_set = set(chunks)
        relevant_set = set(ground_truth_chunks)
        
        true_positives = len(retrieved_set.intersection(relevant_set))
        precision_k = true_positives / len(retrieved_set)
        
        return precision_k
    except Exception as e:
        print(f"Error in calculate_precision_K: {e}")
        return 0.0

def calculate_f1_K(chunks, ground_truth_chunks):
    """
    Menghitung F1@K untuk evaluasi retrieval.
    
    Args:
        chunks (list): List string berisi chunk yang diambil (retrieved).
        ground_truth_chunks (list): List string berisi chunk yang relevan (ground truth).
    Returns:
        float: F1@K (0.0 hingga 1.0).
    """
    try:
        precision_k = calculate_precision_K(chunks, ground_truth_chunks)
        recall_k = calculate_recall_K(chunks, ground_truth_chunks)
        
        if precision_k + recall_k == 0:
            return 0.0
        
        f1_k = 2 * (precision_k * recall_k) / (precision_k + recall_k)
        
        return f1_k
    except Exception as e:
        print(f"Error in calculate_f1_K: {e}")
        return 0.0

def evaluate_chunks(chunks, ground_truth_chunks):
    """
    Evaluasi retrieval dengan menghitung Precision@K, Recall@K, dan F1@K.
    
    Args:
        chunks (list): List string berisi chunk yang diambil (retrieved).
        ground_truth_chunks (list): List string berisi chunk yang relevan (ground truth).
    Returns:
        dict: Dictionary berisi skor Precision@K, Recall@K, dan F1@
    """
    try:
        precision_k = calculate_precision_K(chunks, ground_truth_chunks)
        recall_k = calculate_recall_K(chunks, ground_truth_chunks)
        f1_k = calculate_f1_K(chunks, ground_truth_chunks)
        
        return {
            "precision_k": precision_k,
            "recall_k": recall_k,
            "f1_k": f1_k
        }
    except Exception as e:
        print(f"Error in evaluate_chunks: {e}")
        return {
            "precision_k": 0.0,
            "recall_k": 0.0,
            "f1_k": 0.0
        }


def evaluate_response(response, ground_truth_response=None, chunks=None, judge_model=None, *, question=""):
    """Return JSON-safe scores and per-metric status; unavailable is never zero.

    Ragas receives the original question, the generated answer, the exact source
    passages used by the reader, and (when available) the reference answer.
    Clients are created and closed inside the async call, so Django workers do
    not reuse HTTP clients across event loops. No local model is loaded.
    """
    model = judge_model or DEFAULT_JUDGE_MODEL
    report = {
        "scores": {name: None for name in METRICS},
        "details": {
            "framework": "ragas", "version": "0.4.3", "provider": "openrouter",
            "judge_model": model, "embedding_model": DEFAULT_EMBEDDING_MODEL,
            "metrics": {},
        },
    }
    contexts = [text for text in (chunks or []) if isinstance(text, str) and text.strip()]
    inputs = {
        "faithfulness": {"user_input": question, "response": response, "retrieved_contexts": contexts},
        "answer_relevancy": {"user_input": question, "response": response},
        "factual_correctness": {"response": response, "reference": ground_truth_response},
    }
    missing = {
        "faithfulness": "Requires a question, answer, and retrieved evidence.",
        "answer_relevancy": "Requires a question and answer.",
        "factual_correctness": "Requires an answer and a reference answer.",
    }
    ready = {}
    for name, values in inputs.items():
        if all(value.strip() if isinstance(value, str) else value for value in values.values()):
            ready[name] = values
        else:
            report["details"]["metrics"][name] = {"status": "skipped", "reason": missing[name]}
            report_progress("metric", name, "skipped", missing[name])

    if not ready:
        return report
    if not settings.OPENROUTER_API_KEY:
        for name in ready:
            report["details"]["metrics"][name] = {"status": "unavailable", "reason": "OpenRouter API key is not configured."}
            report_progress("metric", name, "unavailable", "OpenRouter API key is not configured.")
        return report
    for name in ready:
        report_progress("metric", name, "running", "Evaluating with Ragas through OpenRouter.")
    try:
        async_to_sync(_score_ragas)(ready, report, model)
    except Exception as exc:
        # A setup/client failure must not discard the generated answer or any
        # metric that already completed. Do not expose raw provider errors.
        logger.warning("Ragas evaluation setup failed (%s)", type(exc).__name__)
        for name in ready:
            report["details"]["metrics"].setdefault(name, {
                "status": "unavailable", "reason": "Could not start the Ragas evaluator. Check the evaluation provider configuration.",
            })
            state = report["details"]["metrics"][name]
            report_progress("metric", name, state["status"], state.get("reason", "Evaluation finished."), score=report["scores"][name])
    return report


async def _score_ragas(inputs, report, model):
    # Lazy imports keep ordinary chat and server startup independent of Ragas.
    from ragas.embeddings import embedding_factory
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerRelevancy, FactualCorrectness, Faithfulness

    async with AsyncOpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        default_headers=OPENROUTER_HEADERS,
        timeout=45.0,
        max_retries=1,
    ) as client:
        llm = llm_factory(model, client=client, temperature=0, max_retries=2)
        factories = {
            "faithfulness": lambda: Faithfulness(llm=llm),
            "answer_relevancy": lambda: AnswerRelevancy(
                llm=llm,
                embeddings=embedding_factory("openai", model=DEFAULT_EMBEDDING_MODEL, client=client),
            ),
            "factual_correctness": lambda: FactualCorrectness(llm=llm, mode="f1"),
        }

        async def score_one(name, values):
            try:
                metric = factories[name]()
                result = await asyncio.wait_for(metric.ascore(**values), timeout=METRIC_TIMEOUT_SECONDS)
                value = float(result.value)
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("Metric returned a non-finite or out-of-range score.")
                report["scores"][name] = value
                report["details"]["metrics"][name] = {"status": "completed"}
            except Exception as exc:
                logger.warning("Ragas metric %s unavailable (%s)", name, type(exc).__name__)
                reason = "Evaluation timed out." if isinstance(exc, TimeoutError) else "The evaluator could not produce a valid score. Check the judge or embedding provider and retry."
                report["details"]["metrics"][name] = {"status": "unavailable", "reason": reason}
            state = report["details"]["metrics"][name]
            report_progress("metric", name, state["status"], state.get("reason", "Evaluation finished."), score=report["scores"][name])

        await asyncio.gather(*(score_one(name, values) for name, values in inputs.items()))
