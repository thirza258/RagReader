"""The LLM judge for generation metrics (PRD §28).

Wraps the legacy deep-analysis evaluator, `evaluation.eval.evaluate_response`
(Ragas through OpenRouter's API, no local model), so both products score
answers the same way. Ragas metric → lab metric:

    faithfulness         → faithfulness
    answer_relevancy     → answer_relevance
    factual_correctness  → answer_correctness (F1 against the expected answer)

A score the judge cannot produce is None with a reason code, never 0.
"""
import logging

from evaluation import eval as legacy_eval
from lab.services import metrics as m

logger = logging.getLogger(__name__)

RAGAS_TO_LAB = {
    "faithfulness": "faithfulness",
    "answer_relevancy": "answer_relevance",
    "factual_correctness": "answer_correctness",
}
NO_KEY_REASON = "OpenRouter API key is not configured."


def _skip_reason(metric, answer, contexts, expected_answer):
    if metric == "answer_correctness" and not expected_answer:
        return m.NO_EXPECTED_ANSWER
    if not answer:
        return m.NO_ANSWER
    if metric == "faithfulness" and not contexts:
        return m.EMPTY_CONTEXT
    return m.NO_ANSWER


def judge_answer(*, question, answer, contexts, expected_answer, judge_model):
    """({metric: score or None}, {metric: reason}) for one answer."""
    answer = (answer or "").strip()
    expected_answer = (expected_answer or "").strip()
    contexts = [text for text in contexts or [] if isinstance(text, str) and text.strip()]
    values = {name: None for name in m.JUDGE_METRICS}
    reasons = {}
    try:
        report = legacy_eval.evaluate_response(
            answer, expected_answer or None, contexts, judge_model, question=question,
        )
    except Exception:
        logger.warning("The evaluation judge failed", exc_info=True)
        return values, {name: m.JUDGE_FAILED for name in m.JUDGE_METRICS}
    scores = report.get("scores") or {}
    states = (report.get("details") or {}).get("metrics") or {}
    for ragas_name, name in RAGAS_TO_LAB.items():
        score = scores.get(ragas_name)
        state = states.get(ragas_name) or {}
        if isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 1:
            values[name] = round(float(score), m.DECIMALS)
            continue
        status = state.get("status")
        if status == "skipped":
            reasons[name] = _skip_reason(name, answer, contexts, expected_answer)
        elif status == "unavailable" and state.get("reason") == NO_KEY_REASON:
            reasons[name] = m.JUDGE_UNAVAILABLE
        else:
            reasons[name] = m.JUDGE_FAILED
    return values, reasons
