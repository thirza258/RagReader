"""JSON shapes of the evaluation lab (docs/prd-implementation.md, Phase 4)."""
from lab.models import Experiment, ExperimentItem
from lab.services import aggregate as agg
from lab.services import datasets as ds
from lab.services import runner


def version_payload(version, *, checks=True, items=None, workspace_document_ids=None):
    payload = {
        "id": version.pk, "dataset_id": version.dataset_id, "number": version.number,
        "content_hash": version.content_hash, "item_count": version.item_count,
        "document_ids": list(version.document_ids or []), "note": version.note, "created_at": version.created_at,
    }
    if checks:
        payload["checks"] = ds.version_checks(version, items=items, workspace_document_ids=workspace_document_ids)
    return payload


def version_summary(version):
    return {"id": version.pk, "number": version.number, "item_count": version.item_count,
            "content_hash": version.content_hash, "note": version.note, "created_at": version.created_at}


def dataset_payload(dataset, *, version=None):
    version = version or ds.latest_version(dataset)
    versions = list(dataset.versions.order_by("-number"))
    return {
        "id": dataset.pk, "workspace_id": dataset.workspace_id, "name": dataset.name,
        "description": dataset.description,
        "version": version_payload(version) if version is not None else None,
        "version_count": len(versions),
        "versions": [version_summary(entry) for entry in versions],
        "experiment_count": Experiment.objects.filter(dataset_version__dataset=dataset).count(),
        "created_at": dataset.created_at, "updated_at": dataset.updated_at,
    }


def items_payload(dataset, version):
    resolver = ds.DocumentResolver(dataset.workspace)
    return [ds.output_item(item, position, resolver) for position, item in enumerate(ds.version_items(version), 1)]


def _error(experiment):
    if not experiment.error_code:
        return None
    return {"code": experiment.error_code, "message": experiment.error_message, "retryable": experiment.retryable}


def _dataset_ref(experiment):
    snapshot = experiment.dataset_snapshot or (experiment.config or {}).get("dataset") or {}
    return {
        "id": snapshot.get("dataset_id"), "name": snapshot.get("name"), "version_id": snapshot.get("version_id"),
        "version": snapshot.get("version"), "content_hash": snapshot.get("content_hash"),
        "item_count": snapshot.get("item_count"), "available": experiment.dataset_version_id is not None,
    }


def _pipeline_ref(experiment):
    pipeline = (experiment.config or {}).get("pipeline") or {}
    return {
        "id": pipeline.get("pipeline_id"), "name": pipeline.get("name"), "version_id": pipeline.get("version_id"),
        "version": pipeline.get("version"), "config_hash": pipeline.get("config_hash"),
        "strategy": (pipeline.get("config") or {}).get("strategy"),
        "available": experiment.pipeline_version_id is not None,
    }


def _aggregates(experiment, items):
    if experiment.status == Experiment.Status.COMPLETED and experiment.metrics:
        return experiment.metrics
    return agg.aggregate(items, (experiment.config or {}).get("k_values") or runner.DEFAULT_K_VALUES)


def experiment_payload(experiment, items=None):
    items = list(experiment.items.all()) if items is None else items
    pending = sum(1 for item in items if item.status == ExperimentItem.Status.PENDING)
    completed = sum(1 for item in items if item.status == ExperimentItem.Status.COMPLETED)
    config = experiment.config or {}
    return {
        "id": experiment.pk, "workspace_id": experiment.workspace_id, "name": experiment.name,
        "hypothesis": experiment.hypothesis, "conclusion": experiment.conclusion,
        "status": experiment.status, "error": _error(experiment),
        "dataset": _dataset_ref(experiment), "pipeline": _pipeline_ref(experiment),
        "retrieval_only": experiment.retrieval_only, "seed": experiment.seed,
        "k_values": config.get("k_values") or runner.DEFAULT_K_VALUES,
        "progress": {"total": len(items), "completed": completed, "failed": len(items) - completed - pending,
                     "pending": pending},
        "metrics": _aggregates(experiment, items),
        "failures": agg.failure_summary(items),
        "warnings": experiment.warnings or [],
        "git_commit": experiment.git_commit, "rerun_of": experiment.rerun_of_id, "runtime_ms": experiment.runtime_ms,
        "created_at": experiment.created_at, "updated_at": experiment.updated_at,
        "started_at": experiment.started_at, "finished_at": experiment.finished_at,
    }


def experiment_detail_payload(experiment):
    items = list(experiment.items.all())
    return {
        **experiment_payload(experiment, items),
        "config": experiment.config, "index_versions": experiment.index_versions or [],
        "environment": experiment.environment or {}, "reproducibility": runner.reproducibility(experiment),
    }


def item_payload(item, resolver=None):
    details = item.details or {}
    error = None
    if item.error_code:
        error = {"code": item.error_code, "message": item.error_message, "stage": item.error_stage or None}
    sources = item.expected_sources or []
    if resolver is not None:
        sources = [ds.output_source(source, resolver) for source in sources]
    return {
        "position": item.position, "item_id": item.item_id, "status": item.status, "error": error,
        "question": item.question, "expected_answer": item.expected_answer, "expected_sources": sources,
        "history": item.history or [], "tags": item.tags or [],
        "run_id": item.run_id, "answer": item.answer,
        "query": details.get("query"), "matching": details.get("matching") or [],
        "retrieved": details.get("retrieved") or [], "alternative": details.get("alternative"),
        "metrics": item.metrics or {}, "metric_reasons": item.metric_reasons or {},
        "failure_labels": item.failure_labels or [],
        "latency_ms": {"total": item.latency_ms, "retrieval": item.retrieval_ms, "generation": item.generation_ms,
                       "judge": item.judge_ms},
        "token_usage": (None if item.total_tokens is None else
                        {"prompt_tokens": item.prompt_tokens, "completion_tokens": item.completion_tokens,
                         "total_tokens": item.total_tokens}),
        "started_at": item.started_at, "finished_at": item.finished_at,
    }
