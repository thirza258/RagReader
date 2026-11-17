"""Experiment aggregates: metric means, latency percentiles, tokens, failure counts.

Means are over the items with a value; each metric reports how many items
had none and why. Latency percentiles use the Phase 2 definition
(`workspace.services.runs.percentile`). Tokens are generation tokens; the
judge reports none, and there is no pricing data for a dollar cost.
"""
from lab.services import failures
from lab.services import metrics as m
from workspace.services.runs import percentile

LATENCY_FIELDS = (("total", "latency_ms"), ("retrieval", "retrieval_ms"), ("generation", "generation_ms"), ("judge", "judge_ms"))


def metric_aggregate(values, reasons):
    present = [value for value in values if value is not None]
    tally = {}
    for reason in reasons:
        if reason:
            tally[reason] = tally.get(reason, 0) + 1
    return {
        "mean": round(sum(present) / len(present), m.DECIMALS) if present else None,
        "count": len(present),
        "null_count": len(values) - len(present),
        "reasons": tally,
    }


def latency_summary(values):
    present = [value for value in values if value is not None]
    return {
        "p50": percentile(present, 50), "p95": percentile(present, 95),
        "mean": round(sum(present) / len(present), 1) if present else None, "count": len(present),
    }


def experiment_keys(k_values):
    return m.retrieval_keys(k_values), list(m.GENERATION_METRICS)


def aggregate(items, k_values):
    """Aggregates over the finished (completed or failed) `items`."""
    finished = [item for item in items if item.status != "pending"]
    completed = [item for item in finished if item.status == "completed"]
    retrieval_keys, generation_keys = experiment_keys(k_values)

    def group(keys):
        result = {}
        for key in keys:
            values, reasons = [], []
            for item in finished:
                if item.status != "completed":
                    values.append(None)
                    reasons.append(m.ITEM_FAILED)
                    continue
                value = (item.metrics or {}).get(key)
                values.append(value)
                reasons.append(None if value is not None else (item.metric_reasons or {}).get(key))
            result[key] = metric_aggregate(values, reasons)
        return result

    usage = [item for item in completed if item.total_tokens is not None]
    prompt = sum(item.prompt_tokens or 0 for item in usage)
    completion = sum(item.completion_tokens or 0 for item in usage)
    total = sum(item.total_tokens or 0 for item in usage)
    return {
        "items": {"total": len(items), "completed": len(completed), "failed": len(finished) - len(completed)},
        "retrieval": group(retrieval_keys),
        "generation": group(generation_keys),
        "latency_ms": {key: latency_summary([getattr(item, field) for item in completed]) for key, field in LATENCY_FIELDS},
        "tokens": {
            "prompt": prompt, "completion": completion, "total": total,
            "per_item": round(total / len(usage), 1) if usage else None,
            "items_with_usage": len(usage),
        },
        "cost": {"usd": None, "reason": "pricing_unavailable"},
    }


def failure_summary(items):
    return failures.count_labels(item.failure_labels for item in items if item.status != "pending")
