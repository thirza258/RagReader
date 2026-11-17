"""Experiment comparison (PRD §30) and experimental hygiene (§31).

For each metric: every experiment's mean, the difference from the baseline,
and a paired view over the items both experiments scored — the mean paired
difference, a paired bootstrap percentile interval, and per-item wins,
losses and ties. Items pair on their stable `item_id` when their question,
expected answer and expected sources are identical, so experiments on two
versions of one dataset only pair unchanged items.

The bootstrap is deterministic: pairs are sorted by item id and every cell
draws from a fresh `numpy.random.default_rng(seed)`, so a comparison gives
the same intervals however often (and in whatever order) it is computed.
"""
import hashlib
import json

import numpy as np

from lab.services import metrics as m
from lab.services.aggregate import aggregate, latency_summary

RESAMPLES = 2000
CONFIDENCE = 0.95
MIN_COMPARED, MAX_COMPARED = 2, 6
TEST_SET_TUNING_RUNS = 5
EVALUATION_SETTINGS = ("retrieval_only", "query_rewrite", "k_values", "judge_model", "thresholds", "document_ids")


def _round(value, digits=m.DECIMALS):
    return None if value is None else round(float(value), digits)


def paired_bootstrap(differences, seed, resamples=RESAMPLES, confidence=CONFIDENCE):
    """(low, high) percentile interval of the mean paired difference, or (None, None) for < 2 pairs."""
    values = np.asarray(differences, dtype=float)
    if values.size < 2:
        return None, None
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, values.size, size=(resamples, values.size))
    means = values[draws].mean(axis=1)
    tail = (1 - confidence) / 2 * 100
    low, high = np.percentile(means, [tail, 100 - tail])
    return _round(low), _round(high)


def item_key(item):
    """What must be identical for two experiments' items to be paired."""
    content = json.dumps([item.question, item.expected_answer, item.expected_sources], sort_keys=True, ensure_ascii=False)
    return item.item_id, hashlib.sha256(content.encode("utf-8")).hexdigest()


def item_values(items, key):
    """{pairing key: value or None} of completed items for one metric."""
    return {item_key(item): (item.metrics or {}).get(key) if item.status == "completed" else None for item in items}


def compare_cell(baseline_values, values, seed, higher_is_better=True):
    pairs = sorted(
        (pair_key, baseline_values[pair_key], value) for pair_key, value in values.items()
        if pair_key in baseline_values and value is not None and baseline_values[pair_key] is not None
    )
    differences = [value - base for _key, base, value in pairs]
    low, high = paired_bootstrap(differences, seed)
    sign = 1 if higher_is_better else -1
    wins = sum(1 for difference in differences if sign * round(difference, m.DECIMALS) > 0)
    losses = sum(1 for difference in differences if sign * round(difference, m.DECIMALS) < 0)
    return {
        "paired_delta": _round(sum(differences) / len(differences)) if differences else None,
        "ci_low": low, "ci_high": high, "pairs": len(differences),
        "wins": wins, "losses": losses, "ties": len(differences) - wins - losses,
    }


def metric_keys(experiments):
    k_values = sorted({k for experiment in experiments for k in experiment.config.get("k_values") or []})
    return m.retrieval_keys(k_values) + list(m.GENERATION_METRICS)


def default_item_metric(experiments):
    if all(5 in (experiment.config.get("k_values") or []) for experiment in experiments):
        return "recall@5"
    return "mrr"


def _settings(experiment):
    config = experiment.config or {}
    pipeline = (config.get("pipeline") or {}).get("config") or {}
    evaluation = {key: config.get(key) for key in EVALUATION_SETTINGS}
    return pipeline, evaluation


def config_differences(experiments):
    rows = []
    settings = [_settings(experiment) for experiment in experiments]
    pipeline_keys = sorted({key for pipeline, _evaluation in settings for key in pipeline})
    for key in pipeline_keys:
        values = [pipeline.get(key) for pipeline, _evaluation in settings]
        if any(value != values[0] for value in values):
            rows.append({"key": key, "group": "pipeline", "values": values})
    for key in EVALUATION_SETTINGS:
        values = [evaluation.get(key) for _pipeline, evaluation in settings]
        if any(value != values[0] for value in values):
            rows.append({"key": key, "group": "evaluation", "values": values})
    return rows


def hygiene_warnings(experiments, baseline, *, dataset_runs=0):
    warnings = []
    versions = {(experiment.dataset_snapshot or {}).get("version_id") for experiment in experiments}
    if len(versions) > 1:
        warnings.append({
            "code": "dataset_version_mismatch",
            "message": "These experiments ran on different versions of the dataset; only items that did not change are paired.",
            "experiment_ids": [experiment.pk for experiment in experiments],
        })
    settings = {experiment.pk: _settings(experiment) for experiment in experiments}
    base_pipeline, base_evaluation = settings[baseline.pk]
    differing = [experiment.pk for experiment in experiments if settings[experiment.pk][1] != base_evaluation]
    if differing:
        warnings.append({
            "code": "evaluation_settings_differ",
            "message": "The evaluation settings (retrieval only, query rewrite, K values, judge, thresholds or documents) "
                       "differ, so the scores are not measured the same way.",
            "experiment_ids": differing,
        })
    confounded = []
    for experiment in experiments:
        if experiment.pk == baseline.pk:
            continue
        pipeline = settings[experiment.pk][0]
        changed = [key for key in sorted(set(pipeline) | set(base_pipeline)) if pipeline.get(key) != base_pipeline.get(key)]
        if len(changed) > 1:
            confounded.append((experiment.pk, changed))
    if confounded:
        warnings.append({
            "code": "multiple_changes",
            "message": "More than one pipeline setting changed from the baseline ("
                       + "; ".join(f"#{pk}: {', '.join(keys)}" for pk, keys in confounded)
                       + "), so a difference cannot be attributed to one change.",
            "experiment_ids": [pk for pk, _keys in confounded],
        })
    indexes = {}
    for experiment in experiments:
        for entry in experiment.index_versions or []:
            indexes.setdefault(entry.get("document_id"), set()).add(entry.get("index_version_id"))
    changed_documents = sorted(document_id for document_id, ids in indexes.items() if len(ids) > 1 and document_id is not None)
    if changed_documents:
        warnings.append({
            "code": "index_versions_differ",
            "message": f"The experiments searched different index versions of {len(changed_documents)} document(s); "
                       "re-indexing between runs changes the passages.",
            "experiment_ids": [experiment.pk for experiment in experiments], "document_ids": changed_documents,
        })
    incomplete = [experiment.pk for experiment in experiments if experiment.status != "completed" or experiment.failed_count]
    if incomplete:
        warnings.append({
            "code": "incomplete_experiment",
            "message": "Some experiments did not finish or have failed items; their means cover fewer items.",
            "experiment_ids": incomplete,
        })
    if dataset_runs >= TEST_SET_TUNING_RUNS:
        warnings.append(tuning_warning(dataset_runs))
    return warnings


def tuning_warning(count):
    return {
        "code": "repeated_dataset_runs",
        "message": f"{count} experiments have run on this dataset version. Tuning a pipeline against one test set "
                   "overfits it; confirm a winner on a held-out dataset.",
    }


def compare(experiments, items_by_experiment, *, baseline, item_metric, seed, summaries, dataset_runs=0):
    """The §30 comparison payload. `summaries` are the experiments' list payloads (same order)."""
    keys = metric_keys(experiments)
    aggregates = {
        experiment.pk: (experiment.metrics if experiment.status == "completed" and experiment.metrics
                        else aggregate(items_by_experiment[experiment.pk], experiment.config.get("k_values") or []))
        for experiment in experiments
    }
    base_items = items_by_experiment[baseline.pk]
    rows = []
    for key in keys:
        group = m.metric_group(key)
        baseline_values = item_values(base_items, key)
        base_mean = ((aggregates[baseline.pk].get(group) or {}).get(key) or {}).get("mean")
        cells = []
        for experiment in experiments:
            stats = (aggregates[experiment.pk].get(group) or {}).get(key) or {}
            cell = {"experiment_id": experiment.pk, "mean": stats.get("mean"), "count": stats.get("count", 0),
                    "delta": None, "paired_delta": None, "ci_low": None, "ci_high": None,
                    "pairs": None, "wins": None, "losses": None, "ties": None}
            if experiment.pk != baseline.pk:
                if cell["mean"] is not None and base_mean is not None:
                    cell["delta"] = _round(cell["mean"] - base_mean)
                cell.update(compare_cell(baseline_values, item_values(items_by_experiment[experiment.pk], key), seed))
            cells.append(cell)
        rows.append({"key": key, "group": group, "higher_is_better": True, "cells": cells})

    operational = []
    latency = {experiment.pk: latency_summary([item.latency_ms for item in items_by_experiment[experiment.pk]
                                               if item.status == "completed"]) for experiment in experiments}
    tokens = {experiment.pk: aggregates[experiment.pk].get("tokens") or {} for experiment in experiments}
    for key, read in (
        ("latency_p50_ms", lambda pk: latency[pk]["p50"]),
        ("latency_p95_ms", lambda pk: latency[pk]["p95"]),
        ("tokens_per_item", lambda pk: tokens[pk].get("per_item")),
        ("total_tokens", lambda pk: tokens[pk].get("total") if tokens[pk].get("items_with_usage") else None),
        ("cost_usd", lambda pk: None),
    ):
        base = read(baseline.pk)
        cells = []
        for experiment in experiments:
            value = read(experiment.pk)
            delta = None
            if experiment.pk != baseline.pk and value is not None and base is not None:
                delta = _round(value - base, 1)
            cells.append({"experiment_id": experiment.pk, "value": value, "delta": delta})
        operational.append({"key": key, "higher_is_better": False, "cells": cells})

    item_rows = []
    base_by_id = {item.item_id: item for item in base_items}
    order = [item.item_id for item in base_items]
    for experiment in experiments:
        for item in items_by_experiment[experiment.pk]:
            if item.item_id not in base_by_id and item.item_id not in order:
                order.append(item.item_id)
    lookups = {experiment.pk: {item.item_id: item for item in items_by_experiment[experiment.pk]} for experiment in experiments}
    for item_id in order:
        base_item = lookups[baseline.pk].get(item_id)
        base_value = (base_item.metrics or {}).get(item_metric) if base_item is not None and base_item.status == "completed" else None
        question = next((lookups[pk][item_id].question for pk in lookups if item_id in lookups[pk]), "")
        cells = []
        for experiment in experiments:
            item = lookups[experiment.pk].get(item_id)
            value = (item.metrics or {}).get(item_metric) if item is not None and item.status == "completed" else None
            outcome = None
            same_item = item is not None and base_item is not None and item_key(item) == item_key(base_item)
            if experiment.pk != baseline.pk and same_item and value is not None and base_value is not None:
                difference = round(value - base_value, m.DECIMALS)
                outcome = "win" if difference > 0 else "loss" if difference < 0 else "tie"
            cells.append({"experiment_id": experiment.pk, "value": value, "outcome": outcome})
        item_rows.append({"item_id": item_id, "question": question, "cells": cells})

    return {
        "baseline_id": baseline.pk,
        "experiments": summaries,
        "metrics": rows,
        "operational": operational,
        "items": {"metric": item_metric, "rows": item_rows},
        "bootstrap": {"seed": seed, "resamples": RESAMPLES, "confidence": CONFIDENCE},
        "config_differences": config_differences(experiments),
        "warnings": hygiene_warnings(experiments, baseline, dataset_runs=dataset_runs),
    }
