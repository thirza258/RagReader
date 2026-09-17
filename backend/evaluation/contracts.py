"""Public answer metrics must come from a recorded Ragas evaluation."""

RAGAS_ANSWER_METRICS = ("faithfulness", "answer_relevancy", "factual_correctness")


def ragas_only_evaluation(evaluation):
    result = dict(evaluation)
    details = result.get("response_evaluation_details")
    if not isinstance(details, dict) or details.get("framework") != "ragas":
        # Earlier evaluators also used "faithfulness". Its name alone does not
        # establish that Ragas produced the value.
        if "response_evaluation" in result:
            result["response_evaluation"] = {}
        result.pop("response_evaluation_details", None)
        return result

    scores = result.get("response_evaluation")
    states = details.get("metrics")
    result["response_evaluation"] = {
        name: scores.get(name) if isinstance(scores, dict) else None
        for name in RAGAS_ANSWER_METRICS
    }
    result["response_evaluation_details"] = {
        **details,
        "metrics": {
            name: states[name] for name in RAGAS_ANSWER_METRICS
            if isinstance(states, dict) and name in states
        },
    }
    return result
