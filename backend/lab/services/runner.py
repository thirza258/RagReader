"""Experiment lifecycle and execution (PRD §29, §42; docs/prd-implementation.md, Phase 4).

    create → draft ─start→ queued → running → completed
                     ↑               ├→ failed     (start again resumes)
                     └───────────────┴→ cancelled  (start again resumes)

`create_experiment` snapshots everything an experiment needs to be rerun —
the pipeline configuration, the dataset items, the documents, the seed —
and `run_experiment` (the body of `lab.tasks.run_experiment_task`) works
through the items. Each item takes the chat path (rewrite → `chat.retrieve`
→ cited generation → citation parsing), then the judge and the metrics, and
is recorded as a `RetrievalRun` with `source="evaluation"`.

Ownership is a token. A worker claims a queued experiment by its
`run_token`; every item starts with a heartbeat that is also the ownership
check, and each item's run and result are written in one transaction that
re-checks it. Cancelling, restarting or deleting an experiment changes or
clears the token, so a worker that lost it stops without writing.
"""
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, F, Q, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from ai_handler.llm import StreamResult
from common.constant import CHAT_HISTORY_MESSAGES, DEFAULT_JUDGE_MODEL, is_valid_model_id
from common.prompt_builder import cited_chat_messages
from lab.models import DatasetVersion, EvaluationDataset, Experiment, ExperimentItem
from lab.services import aggregate as agg
from lab.services import comparison
from lab.services import datasets as ds
from lab.services import environment as env
from lab.services import failures
from lab.services import matching
from lab.services import metrics as m
from lab.services.judge import judge_answer
from router.models import Document
from workspace.errors import ApiError, describe_exception
from workspace.models import PipelineVersion, RetrievalRun
from workspace.services import chat, llms, pipelines, tracing
from workspace.services import runs as run_store
from workspace.services.citations import mark_cited
from workspace.services.ingestion import chat_engine
from workspace.services.retrieval import chat_index, index_entry, retrieval_parameters

logger = logging.getLogger(__name__)

Status = Experiment.Status
ItemStatus = ExperimentItem.Status

STALL_AFTER = timedelta(minutes=35)
DEFAULT_K_VALUES = [1, 3, 5, 10]
MAX_K_VALUES = 6
K_MIN, K_MAX = 1, 50
SEED_MAX = 2 ** 31 - 1
DEFAULT_SEED = 42
DEFAULT_THRESHOLDS = {"faithfulness": 0.5, "answer_correctness": 0.5}
MAX_NAME_CHARS = 200
MAX_HYPOTHESIS_CHARS = 4000
MAX_CONCLUSION_CHARS = 10000
# These stop the whole experiment at the item that hit them: every later item
# would fail the same way. Resuming continues from that item.
FATAL_CODES = frozenset({
    "index_unavailable", "embedding_model_mismatch", "missing_provider_key",
    "provider_authentication", "provider_credits", "provider_request_rejected", "no_ready_documents",
})
CONSECUTIVE_FAILURE_LIMIT = 3
QUEUE_FAILURE_MESSAGE = "The experiment worker could not be reached. Try starting the experiment again shortly."
INVALID = ds.INVALID


class LostOwnership(Exception):
    """The experiment was cancelled, restarted or deleted while this worker ran."""


class ExperimentFatal(Exception):
    def __init__(self, error, stage=""):
        super().__init__(error.get("message", ""))
        self.error = error
        self.stage = stage


def _ms(since):
    return int(round((time.monotonic() - since) * 1000))


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


# ── Input ────────────────────────────────────────────────────────────────────

def _flag(data, key, default, errors):
    value = data.get(key, default)
    if not isinstance(value, bool):
        errors[key] = ["Expected true or false."]
        return default
    return value


def clean_k_values(raw, errors):
    if raw is None:
        return list(DEFAULT_K_VALUES)
    values = [_int(value) for value in raw] if isinstance(raw, list) else None
    if (not values or len(values) > MAX_K_VALUES or any(v is None or not K_MIN <= v <= K_MAX for v in values)):
        errors["k_values"] = [f"Give 1–{MAX_K_VALUES} whole numbers between {K_MIN} and {K_MAX}."]
        return list(DEFAULT_K_VALUES)
    return sorted(set(values))


def clean_seed(raw, errors):
    if raw is None:
        return DEFAULT_SEED
    value = _int(raw)
    if value is None or not 0 <= value <= SEED_MAX:
        errors["seed"] = [f"Choose a whole number between 0 and {SEED_MAX}."]
        return DEFAULT_SEED
    return value


def clean_text(data, key, limit, errors, *, default=""):
    value = data.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        errors[key] = ["Expected text."]
        return default
    value = value.strip()
    if len(value) > limit:
        errors[key] = [f"Keep it under {limit} characters."]
    return value[:limit]


def owned_dataset(user, dataset_id):
    pk = _int(dataset_id)
    dataset = (EvaluationDataset.objects.select_related("workspace", "workspace__user")
               .filter(pk=pk, workspace__user=user).first() if pk and pk > 0 else None)
    if dataset is None:
        raise ApiError("not_found", "Dataset not found.", status=404)
    return dataset


def resolve_dataset_version(dataset, data, errors):
    version_id, number = data.get("dataset_version_id"), data.get("dataset_version")
    if version_id not in (None, ""):
        pk = _int(version_id)
        version = dataset.versions.filter(pk=pk).first() if pk else None
        if version is None:
            errors["dataset_version_id"] = [f"Version {version_id} is not a version of this dataset."]
        return version
    if number not in (None, ""):
        value = _int(number)
        version = dataset.versions.filter(number=value).first() if value else None
        if version is None:
            errors["dataset_version"] = [f"The dataset has no version {number}."]
        return version
    return ds.latest_version(dataset)


def resolve_pipeline_version(workspace, data, errors):
    version_id, pipeline_id = data.get("pipeline_version_id"), data.get("pipeline_id")
    if version_id not in (None, ""):
        pk = _int(version_id)
        version = (PipelineVersion.objects.select_related("pipeline")
                   .filter(pk=pk, pipeline__workspace=workspace).first() if pk else None)
        if version is None:
            errors["pipeline_version_id"] = [f"Pipeline version {version_id} is not in this workspace."]
        return version
    if pipeline_id not in (None, ""):
        pipeline = pipelines.pipeline_in_workspace(workspace, _int(pipeline_id), field="pipeline_id")
        return pipelines.latest_version(pipeline)
    return pipelines.latest_version(pipelines.default_pipeline_for(workspace))


def corpus_documents(workspace, version):
    """The READY documents a dataset version is evaluated against (409 otherwise)."""
    ids = list(version.document_ids or [])
    owned = Document.objects.filter(workspace=workspace, user=workspace.user)
    if ids:
        documents = {document.pk: document for document in owned.filter(pk__in=ids)}
        not_ready = [document.name for pk, document in documents.items() if document.status != Document.Status.READY]
        missing = [pk for pk in ids if pk not in documents]
        if not_ready or missing:
            names = ", ".join([f"“{name}”" for name in not_ready] + [f"#{pk} (deleted)" for pk in missing])
            raise ApiError("documents_not_ready",
                           f"Every document of the dataset must be READY before it is evaluated: {names}.", status=409)
        return [documents[pk] for pk in ids]
    documents = list(owned.filter(status=Document.Status.READY).order_by("pk"))
    if not documents:
        raise ApiError("no_ready_documents", "The workspace has no READY documents to evaluate against.", status=409)
    return documents


def models_used(pipeline_config, judge_model):
    reranker = pipeline_config.get("reranker") or None
    return {
        "embedding": pipeline_config.get("embedding_model"),
        "generation": pipeline_config.get("generation_model"),
        "reranker": (reranker or {}).get("model") if isinstance(reranker, dict) else reranker,
        "judge": judge_model,
    }


def dataset_snapshot(dataset, version):
    return {
        "dataset_id": dataset.pk, "name": dataset.name, "version_id": version.pk, "version": version.number,
        "content_hash": version.content_hash, "item_count": version.item_count,
    }


def create_experiment(user, data):
    """Validate an ExperimentInput, snapshot it, and start it unless it is a draft."""
    if not isinstance(data, dict):
        raise ApiError("invalid_request", INVALID, details={"body": ["Expected a JSON object."]})
    if data.get("dataset_id") in (None, ""):
        raise ApiError("invalid_request", INVALID, details={"dataset_id": ["A dataset is required."]})
    dataset = owned_dataset(user, data.get("dataset_id"))
    workspace = dataset.workspace
    errors = {}
    if data.get("workspace_id") not in (None, "") and _int(data.get("workspace_id")) != workspace.pk:
        errors["workspace_id"] = ["The dataset belongs to another workspace."]
    version = resolve_dataset_version(dataset, data, errors)
    pipeline_version = resolve_pipeline_version(workspace, data, errors)
    retrieval_only = _flag(data, "retrieval_only", False, errors)
    query_rewrite = _flag(data, "query_rewrite", True, errors)
    draft = _flag(data, "draft", False, errors)
    k_values = clean_k_values(data.get("k_values"), errors)
    seed = clean_seed(data.get("seed"), errors)
    judge_model = data.get("judge_model") or DEFAULT_JUDGE_MODEL
    if not is_valid_model_id(judge_model):
        errors["judge_model"] = ["Use an OpenRouter model id such as mistralai/mistral-nemo."]
    hypothesis = clean_text(data, "hypothesis", MAX_HYPOTHESIS_CHARS, errors)
    name = clean_text(data, "name", MAX_NAME_CHARS, errors)
    if errors:
        raise ApiError("invalid_request", INVALID, details=errors)
    if version.item_count == 0:
        raise ApiError("dataset_empty", "This dataset version has no items. Add questions before evaluating it.", status=409)
    documents = corpus_documents(workspace, version)
    pipelines.check_documents(pipeline_version, documents)

    pipeline = pipelines.snapshot(pipeline_version)
    judge = None if retrieval_only else judge_model
    config = {
        "schema_version": 1,
        "pipeline": pipeline,
        "dataset": dataset_snapshot(dataset, version),
        "document_ids": [document.pk for document in documents],
        "retrieval_only": retrieval_only,
        "query_rewrite": query_rewrite,
        "k_values": k_values,
        "judge_model": judge,
        "thresholds": dict(DEFAULT_THRESHOLDS),
        "seed": seed,
    }
    name = name or f"{dataset.name} v{version.number} · {pipeline['name']} v{pipeline['version']}"
    with transaction.atomic():
        experiment = Experiment.objects.create(
            workspace=workspace, name=name, hypothesis=hypothesis,
            dataset_version=version, dataset_snapshot=config["dataset"],
            pipeline_version=pipeline_version, config=config, retrieval_only=retrieval_only, seed=seed,
            item_count=version.item_count, git_commit=env.git_commit(),
            environment=env.environment(models_used(pipeline["config"], judge)),
        )
        ExperimentItem.objects.bulk_create([
            ExperimentItem(
                experiment=experiment, position=position, item_id=item["item_id"], question=item["question"],
                expected_answer=item["expected_answer"], expected_sources=item["expected_sources"],
                history=item["history"], tags=item["tags"],
            )
            for position, item in enumerate(ds.version_items(version), 1)
        ], batch_size=500)
    if not draft:
        start_experiment(experiment)
    return experiment


def rerun_experiment(experiment, data):
    """§42: the stored configuration, seed, documents and items, as a new experiment."""
    data = data if isinstance(data, dict) else {}
    errors = {}
    name = clean_text(data, "name", MAX_NAME_CHARS, errors)
    draft = _flag(data, "draft", False, errors)
    if errors:
        raise ApiError("invalid_request", INVALID, details=errors)
    with transaction.atomic():
        copy = Experiment.objects.create(
            workspace=experiment.workspace, name=name or f"Rerun of {experiment.name}"[:MAX_NAME_CHARS],
            hypothesis=experiment.hypothesis,
            dataset_version_id=(experiment.dataset_version_id
                                if DatasetVersion.objects.filter(pk=experiment.dataset_version_id).exists() else None),
            dataset_snapshot=experiment.dataset_snapshot,
            pipeline_version_id=(experiment.pipeline_version_id
                                 if PipelineVersion.objects.filter(pk=experiment.pipeline_version_id).exists() else None),
            config=experiment.config, retrieval_only=experiment.retrieval_only, seed=experiment.seed,
            item_count=experiment.item_count, git_commit=env.git_commit(),
            environment=env.environment(models_used((experiment.config.get("pipeline") or {}).get("config") or {},
                                                    experiment.config.get("judge_model"))),
            rerun_of=experiment,
        )
        ExperimentItem.objects.bulk_create([
            ExperimentItem(
                experiment=copy, position=item.position, item_id=item.item_id, question=item.question,
                expected_answer=item.expected_answer, expected_sources=item.expected_sources,
                history=item.history, tags=item.tags,
            )
            for item in experiment.items.order_by("position")
        ], batch_size=500)
    if not draft:
        start_experiment(copy)
    return copy


# ── Lifecycle ────────────────────────────────────────────────────────────────

def start_experiment(experiment):
    """Queue a draft (first start) or resume a failed/cancelled experiment.

    Returns the experiment; raises ApiError 503 `job_queue_unavailable`
    (with the experiment attached as `experiment`) when the worker cannot
    be reached.
    """
    expire_if_stalled(experiment)
    if experiment.status in (Status.QUEUED, Status.RUNNING):
        raise ApiError("experiment_in_progress", "The experiment is already queued or running.", status=409)
    if experiment.status == Status.COMPLETED:
        raise ApiError("experiment_finished", "The experiment has finished. Rerun it to run it again.", status=409)
    token = uuid.uuid4()
    now = timezone.now()
    with transaction.atomic():
        updated = Experiment.objects.filter(
            pk=experiment.pk, status__in=(Status.DRAFT, Status.FAILED, Status.CANCELLED),
        ).update(status=Status.QUEUED, run_token=token, heartbeat_at=now, updated_at=now,
                 error_code="", error_message="", retryable=False, finished_at=None)
        if not updated:
            raise ApiError("experiment_in_progress", "The experiment changed state; reload it and try again.", status=409)
        failed = []

        def enqueue():
            from lab import tasks
            try:
                tasks.run_experiment_task.delay(experiment.pk, str(token))
            except Exception:
                logger.warning("Could not enqueue experiment %s", experiment.pk, exc_info=True)
                Experiment.objects.filter(pk=experiment.pk, run_token=token).update(
                    status=Status.FAILED, run_token=None, error_code="job_queue_unavailable",
                    error_message=QUEUE_FAILURE_MESSAGE, retryable=True, updated_at=timezone.now(),
                )
                failed.append(True)

        transaction.on_commit(enqueue)
    experiment.refresh_from_db()
    if failed:
        error = ApiError("job_queue_unavailable", QUEUE_FAILURE_MESSAGE, status=503, retryable=True)
        error.experiment = experiment
        raise error
    return experiment


def cancel_experiment(experiment):
    updated = Experiment.objects.filter(pk=experiment.pk, status__in=(Status.QUEUED, Status.RUNNING)).update(
        status=Status.CANCELLED, run_token=None, finished_at=timezone.now(), updated_at=timezone.now(),
    )
    if not updated:
        raise ApiError("experiment_not_running", "Only a queued or running experiment can be cancelled.", status=409)
    experiment.refresh_from_db()
    return experiment


def delete_experiment(experiment):
    """Deletes the experiment and its evaluation runs; a running worker stops at its next heartbeat."""
    with transaction.atomic():
        run_ids = list(experiment.items.exclude(run=None).values_list("run_id", flat=True))
        experiment.delete()
        RetrievalRun.objects.filter(pk__in=run_ids, source=RetrievalRun.Source.EVALUATION).delete()


def expire_if_stalled(experiment):
    """Fail a queued/running experiment whose worker stopped beating (lost message or killed worker)."""
    if experiment.status not in (Status.QUEUED, Status.RUNNING):
        return experiment
    last = experiment.heartbeat_at or experiment.updated_at
    if last and last < timezone.now() - STALL_AFTER:
        Experiment.objects.filter(pk=experiment.pk, status=experiment.status, run_token=experiment.run_token).update(
            status=Status.FAILED, run_token=None, error_code="experiment_stalled", retryable=True,
            error_message="The experiment stopped making progress. Start it again to resume where it stopped.",
            updated_at=timezone.now(),
        )
        experiment.refresh_from_db()
    return experiment


# ── Reproducibility (§42) ────────────────────────────────────────────────────

def reproducibility(experiment):
    """What no longer matches the recorded configuration, checked now."""
    warnings = []
    pipeline = (experiment.config or {}).get("pipeline") or {}
    version = PipelineVersion.objects.select_related("pipeline").filter(pk=pipeline.get("version_id")).first()
    if version is None:
        warnings.append({"code": "pipeline_version_missing",
                         "message": f"Pipeline “{pipeline.get('name')}” v{pipeline.get('version')} no longer exists; "
                                    "a rerun uses the recorded configuration."})
    else:
        latest = version.pipeline.versions.order_by("-number").first()
        if latest is not None and latest.pk != version.pk:
            warnings.append({"code": "pipeline_version_differs",
                             "message": f"“{version.pipeline.name}” is now at v{latest.number}; this experiment used "
                                        f"v{version.number} (a rerun keeps v{version.number})."})
    dataset = (experiment.config or {}).get("dataset") or experiment.dataset_snapshot or {}
    if not DatasetVersion.objects.filter(pk=dataset.get("version_id")).exists():
        warnings.append({"code": "dataset_version_missing",
                         "message": "The dataset version was deleted; a rerun uses the recorded questions."})
    entries = experiment.index_versions or []
    documents = {document.pk: document for document in
                 Document.objects.filter(pk__in=[entry.get("document_id") for entry in entries])}
    from router.models import DocumentVector
    existing = set(DocumentVector.objects.filter(
        pk__in=[entry.get("index_version_id") for entry in entries if entry.get("index_version_id")]
    ).values_list("pk", flat=True))
    for entry in entries:
        document = documents.get(entry.get("document_id"))
        title = entry.get("document_title") or f"#{entry.get('document_id')}"
        if document is None:
            warnings.append({"code": "document_missing", "message": f"“{title}” was deleted.",
                             "document_id": entry.get("document_id")})
        elif entry.get("index_version_id") not in existing:
            warnings.append({"code": "index_version_missing",
                             "message": f"The index version of “{title}” this experiment searched no longer exists.",
                             "document_id": document.pk})
        elif document.current_index_id and document.current_index_id != entry.get("index_version_id"):
            warnings.append({"code": "index_version_changed",
                             "message": f"“{title}” was re-indexed since; a rerun searches its current index.",
                             "document_id": document.pk})
    return {"status": "changed" if warnings else "reproducible", "warnings": warnings}


# ── The worker ───────────────────────────────────────────────────────────────

@dataclass
class RunContext:
    experiment: Experiment
    token: uuid.UUID
    config: dict
    pipeline_config: dict
    version: PipelineVersion | None
    documents: list
    engine: object
    k_values: list
    thresholds: dict
    duplicates: dict
    _llm: object = None
    _corpus: dict = field(default_factory=dict)

    @property
    def retrieval_only(self):
        return bool(self.config.get("retrieval_only"))

    def llm(self):
        if self._llm is None:
            self._llm = llms.generation_llm(self.engine, self.pipeline_config.get("generation_model"))
        return self._llm

    def corpus(self, loaded):
        """document id → matching.IndexChunks for the snapshots searched (positions read once)."""
        result = {}
        for entry in loaded:
            key = (entry.document.pk, entry.vector.pk)
            if key not in self._corpus:
                self._corpus[key] = matching.index_chunks(entry.document.pk, entry.vector.pk, entry.snapshot.chunk_ids)
            result[entry.document.pk] = self._corpus[key]
        return result


def _owns(experiment_id, token):
    return Experiment.objects.filter(pk=experiment_id, status=Status.RUNNING, run_token=token).exists()


def heartbeat(experiment_id, token):
    now = timezone.now()
    return bool(Experiment.objects.filter(pk=experiment_id, status=Status.RUNNING, run_token=token)
                .update(heartbeat_at=now, updated_at=now))


def duplicate_map(items):
    groups = {}
    for item in items:
        groups.setdefault(ds.normalized_question(item.question), []).append(item.item_id)
    return {item_id: [other for other in ids if other != item_id]
            for key, ids in groups.items() if key and len(ids) > 1 for item_id in ids}


def _merge_warnings(existing, new):
    codes = {(warning.get("code"), warning.get("document_id")) for warning in existing}
    merged = list(existing)
    for warning in new:
        if (warning.get("code"), warning.get("document_id")) not in codes:
            merged.append(warning)
    return merged


def prepare(experiment, token):
    """Documents, engine and index versions for this worker run; records warnings."""
    config = experiment.config or {}
    workspace = experiment.workspace
    ids = list(config.get("document_ids") or [])
    owned = {document.pk: document for document in
             Document.objects.select_related("current_index").filter(pk__in=ids, workspace=workspace, user=workspace.user)}
    warnings = []
    documents = []
    for pk in ids:
        document = owned.get(pk)
        if document is None:
            warnings.append({"code": "document_missing", "message": f"Document #{pk} was deleted; it is not searched.",
                             "document_id": pk})
        elif document.status != Document.Status.READY:
            warnings.append({"code": "document_missing",
                             "message": f"“{document.name}” is {document.status.lower()}, not READY; it is not searched.",
                             "document_id": pk})
        else:
            documents.append(document)
    if not documents:
        raise ExperimentFatal({"code": "no_ready_documents", "retryable": True,
                               "message": "None of the experiment's documents is READY any more."})
    version = experiment.pipeline_version
    if version is not None:
        try:
            pipelines.check_documents(version, documents)
        except ApiError as exc:
            raise ExperimentFatal({"code": exc.code, "message": exc.message, "retryable": False}, "retrieve")
    engine = chat_engine()
    entries = []
    for document in documents:
        entry = index_entry(document, chat_index(engine, document))
        entry.pop("loaded", None)
        entries.append(entry)
    recorded = experiment.index_versions or []
    if recorded and [(e.get("document_id"), e.get("index_version_id")) for e in recorded] != \
            [(e.get("document_id"), e.get("index_version_id")) for e in entries]:
        warnings.append({"code": "index_changed_during_run",
                         "message": "A document was re-indexed between runs of this experiment; later items "
                                    "searched the new index."})
    runs_on_version = Experiment.objects.filter(
        workspace=workspace, dataset_snapshot__version_id=(experiment.dataset_snapshot or {}).get("version_id"),
    ).exclude(status=Status.DRAFT).count()
    if runs_on_version >= comparison.TEST_SET_TUNING_RUNS:
        warnings.append(comparison.tuning_warning(runs_on_version))
    warnings += [warning for warning in reproducibility(experiment)["warnings"]
                 if warning["code"] in ("pipeline_version_missing", "dataset_version_missing")]
    merged = _merge_warnings(experiment.warnings or [], warnings)
    if not Experiment.objects.filter(pk=experiment.pk, status=Status.RUNNING, run_token=token).update(
            index_versions=entries, warnings=merged, updated_at=timezone.now()):
        raise LostOwnership()
    items = list(experiment.items.all())
    return RunContext(
        experiment=experiment, token=token, config=config,
        pipeline_config=(config.get("pipeline") or {}).get("config") or {},
        version=version, documents=documents, engine=engine,
        k_values=list(config.get("k_values") or DEFAULT_K_VALUES),
        thresholds={**DEFAULT_THRESHOLDS, **(config.get("thresholds") or {})},
        duplicates=duplicate_map(items),
    )


def _retrieved_rows(ranked, resolved, cited_chunks=None):
    membership = {}
    for index, chunk_set in resolved:
        for chunk_id in chunk_set:
            membership.setdefault(chunk_id, []).append(index)
    rows = []
    for row in ranked:
        sources = sorted(membership.get(row["chunk_id"], []))
        entry = {"rank": row["rank"], "document_id": row["document"].pk, "chunk_id": row["chunk_id"],
                 "in_context": bool(row["selected_for_context"]), "relevant": bool(sources), "sources": sources}
        if cited_chunks is not None:
            entry["cited"] = row["chunk_id"] in cited_chunks
        rows.append(entry)
    return rows


def _provenance(ctx, tracer, item, history, rerank, model, fallback):
    config = ctx.pipeline_config
    return {
        "schema_version": 1,
        "timestamp": tracer.started_at.isoformat(),
        "strategy": config.get("strategy"),
        "retrieval_parameters": {
            **retrieval_parameters(config),
            "query_rewrite": bool(history) and bool(ctx.config.get("query_rewrite")),
            "history_messages": len(history), "history_limit": CHAT_HISTORY_MESSAGES,
        },
        "embedding_model": config.get("embedding_model"),
        "reranker": chat._reranker_provenance(config, rerank),
        "generation_model": model,
        "configured_generation_model": config.get("generation_model"),
        "fallback_used": bool(fallback),
        "generation_parameters": {"temperature": config.get("temperature"), "stream": True},
        "prompt_version": config.get("prompt_version"),
        "index_versions": ctx.experiment.index_versions or [],
        "index_version_count": len(ctx.documents),
        "pipeline": ctx.config.get("pipeline"),
        "evaluation": {"experiment_id": ctx.experiment.pk, "item_id": item.item_id, "position": item.position},
    }


def _save(ctx, item, *, run_kwargs, fields):
    """One transaction: ownership re-checked, the run written, the item settled."""
    with transaction.atomic():
        if not _owns(ctx.experiment.pk, ctx.token):
            raise LostOwnership()
        old_run = item.run_id
        run = run_store.save_run(**run_kwargs)
        for key, value in fields.items():
            setattr(item, key, value)
        item.run = run
        item.finished_at = timezone.now()
        item.save()
        if old_run:
            RetrievalRun.objects.filter(pk=old_run, source=RetrievalRun.Source.EVALUATION).delete()
        counts = ctx.experiment.items.aggregate(
            completed=Count("id", filter=Q(status=ItemStatus.COMPLETED)),
            failed=Count("id", filter=Q(status=ItemStatus.FAILED)),
        )
        Experiment.objects.filter(pk=ctx.experiment.pk).update(
            completed_count=counts["completed"], failed_count=counts["failed"],
            heartbeat_at=timezone.now(), updated_at=timezone.now(),
        )


def process_item(ctx, item):
    """Evaluate one item. Returns None when it completed, else its error code.

    Raises ExperimentFatal for errors every later item would hit too, and
    LostOwnership when the experiment stopped being this worker's.
    """
    started = time.monotonic()
    item.started_at = timezone.now()
    tracer = tracing.new_tracer("evaluation.item", "Evaluation item", origin=started)
    config, question = ctx.pipeline_config, item.question
    history = [turn for turn in (item.history or []) if isinstance(turn, dict)]
    timings = {"rewrite": 0, "embed_query": None, "search": None}
    state = {"stage": "rewrite", "used": question, "rewritten": None, "applied": False, "reason": "first_question",
             "found": None, "retrieval_ms": None, "generation_ms": None, "first_token": None, "judge_ms": None,
             "result": None, "answer": "", "citations": [], "alternative": None, "rewrite_ms": None,
             "judge_values": {}, "judge_reasons": {}}
    try:
        with tracer.span("rewrite", "Query rewrite", history_messages=len(history)) as span:
            if history:
                began = time.monotonic()
                outcome = {}
                candidate, applied = chat.rewrite_question(ctx.llm(), question, history, outcome)
                timings["rewrite"] = state["rewrite_ms"] = _ms(began)
                reason = outcome.get("reason", "")
                usable = reason in ("rewritten", "unchanged")
                state["rewritten"] = candidate if usable else None
                if ctx.config.get("query_rewrite") and applied:
                    state.update(used=candidate, applied=True, reason=reason)
                else:
                    state["reason"] = reason if ctx.config.get("query_rewrite") else "disabled"
                span.set(applied=state["applied"], reason=state["reason"])
                if reason == "failed":
                    span.fail("rewrite_failed")
                elif not state["applied"]:
                    span.skip(chat.REWRITE_DETAILS.get(reason, "Searched with the question as asked"))
            else:
                span.skip("No conversation history")

        state["stage"] = "retrieve"
        began = time.monotonic()
        with tracer.span("retrieve", "Retrieval", documents=len(ctx.documents)) as span:
            found = chat.retrieve(ctx.engine, state["used"], ctx.documents, timings, config, tracer=tracer, indexes=[])
            span.set(candidates=len(found.candidates), context=len(found.sources))
        state["found"], state["retrieval_ms"] = found, _ms(began)
        state["citations"] = list(found.sources)

        if ctx.retrieval_only:
            with tracer.span("generate", "Generation") as span:
                span.skip("Retrieval-only experiment")
            with tracer.span("citations", "Citation parsing") as span:
                span.skip("Retrieval-only experiment")
        else:
            state["stage"] = "generate"
            began, parts = time.monotonic(), []
            with tracer.span("generate", "Generation", configured_model=config.get("generation_model")) as span:
                waiting = tracer.start("generate.first_token", "Time to first token")
                messages = cited_chat_messages(question, found.sources, history)
                for piece in ctx.llm().stream_chat(messages, temperature=config.get("temperature")):
                    if isinstance(piece, StreamResult):
                        state["result"] = piece
                        continue
                    if state["first_token"] is None:
                        state["first_token"] = _ms(started)
                        tracer.finish(waiting)
                    parts.append(piece)
                state["generation_ms"] = _ms(began)
                result = state["result"]
                if result is not None:
                    span.set(model=result.model, fallback=bool(getattr(result, "fallback", False)))
            state["answer"] = "".join(parts)
            with tracer.span("citations", "Citation parsing") as span:
                state["citations"] = mark_cited(found.sources, state["answer"])
                span.set(cited=sum(1 for source in state["citations"] if source["cited"]))

        other = None
        if state["rewritten"] and state["rewritten"] != question:
            other = ("original", question) if state["applied"] else ("rewritten", state["rewritten"])
        with tracer.span("alternative_query", "Diagnostic retrieval") as span:
            if other is None:
                span.skip("Only one formulation of the question")
            else:
                try:
                    alt = chat.retrieve(ctx.engine, other[1], ctx.documents, {}, config, tracer=None, indexes=[])
                    state["alternative"] = (other[0], other[1], alt)
                    span.set(kind=other[0], candidates=len(alt.candidates))
                except Exception:
                    logger.warning("Diagnostic retrieval failed for item %s", item.item_id, exc_info=True)
                    span.fail("alternative_failed")

        with tracer.span("judge", "LLM judge", model=ctx.config.get("judge_model")) as span:
            if ctx.retrieval_only:
                span.skip("Retrieval-only experiment")
            else:
                state["stage"] = "judge"
                began = time.monotonic()
                state["judge_values"], state["judge_reasons"] = judge_answer(
                    question=question, answer=state["answer"], contexts=[source["text"] for source in found.sources],
                    expected_answer=item.expected_answer, judge_model=ctx.config.get("judge_model"),
                )
                state["judge_ms"] = _ms(began)

        state["stage"] = "score"
        with tracer.span("score", "Metrics and failure analysis") as span:
            scored = score_item(ctx, item, state)
            span.set(labels=len(scored["failure_labels"]))
        tracer.close()
    except (LostOwnership, ExperimentFatal):
        raise
    except Exception as exc:
        _status, error = describe_exception(exc)
        tracer.close(error=error["code"])
        if error["code"] in FATAL_CODES:
            raise ExperimentFatal(error, state["stage"])
        stage = state["stage"]
        _record(ctx, item, tracer, history, state, status=RetrievalRun.Status.FAILED, error=error, stage=stage,
                fields={"status": ItemStatus.FAILED, "error_code": error["code"][:80], "error_message": error["message"],
                        "error_stage": stage, "answer": state["answer"], "metrics": {}, "metric_reasons": {},
                        "failure_labels": [], "details": _details(state, None)})
        return error["code"]
    _record(ctx, item, tracer, history, state, status=RetrievalRun.Status.COMPLETED,
            fields={"status": ItemStatus.COMPLETED, "error_code": "", "error_message": "", "error_stage": "",
                    "answer": state["answer"], **scored, "details": _details(state, scored["_matching_rows"])})
    return None


def _details(state, matching_rows):
    found = state["found"]
    details = {
        "query": {"used": state["used"], "original": None, "rewritten": state["rewritten"],
                  "rewrite_applied": state["applied"], "rewrite_reason": state["reason"]},
        "matching": matching_rows or [],
        "retrieved": state.get("_retrieved") or [],
        "alternative": state.get("_alternative"),
    }
    if found is None:
        details["retrieved"] = []
    return details


def score_item(ctx, item, state):
    found = state["found"]
    corpus = ctx.corpus(found.loaded)
    matching_rows = matching.resolve_sources(item.expected_sources or [], corpus)
    resolved = [(row["source"], frozenset(row["chunk_ids"])) for row in matching_rows
                if row["rule"] != matching.UNRESOLVED and row["chunk_ids"]]
    source_sets = [chunk_set for _index, chunk_set in resolved]
    has_sources = bool(item.expected_sources)
    ranked_ids = [row["chunk_id"] for row in found.ranked]
    context_size = len(found.sources)
    values, reasons = m.retrieval_metrics(ranked_ids, source_sets, ctx.k_values, context_size,
                                          has_expected_sources=has_sources)
    if ctx.retrieval_only:
        generation, generation_reasons = m.unavailable(m.GENERATION_METRICS, m.RETRIEVAL_ONLY)
    else:
        cited = [source["chunk_id"] for source in state["citations"] if source.get("cited")]
        generation, generation_reasons = m.citation_metrics(
            [source["chunk_id"] for source in found.sources], cited, source_sets, has_expected_sources=has_sources,
        )
        for key in m.JUDGE_METRICS:
            generation[key] = state["judge_values"].get(key)
            if generation[key] is None:
                generation_reasons[key] = state["judge_reasons"].get(key) or m.JUDGE_FAILED
    values.update(generation)
    reasons.update(generation_reasons)

    cited_chunks = {source["chunk_id"] for source in state["citations"] if source.get("cited")}
    state["_retrieved"] = _retrieved_rows(found.ranked, resolved, None if ctx.retrieval_only else cited_chunks)
    alternative = None
    if state["alternative"] is not None:
        kind, query, alt = state["alternative"]
        alternative = {"kind": kind, "ranked": [{"chunk_id": row["chunk_id"], "document_id": row["document"].pk}
                                                for row in alt.ranked], "context_size": len(alt.sources)}
        state["_alternative"] = {"kind": kind, "query": query, "retrieved": _retrieved_rows(alt.ranked, resolved)}
    expected_documents = {source.get("document_id") for source in item.expected_sources or []}
    labels = failures.retrieval_labels(
        resolved, [{"chunk_id": row["chunk_id"], "document_id": row["document"].pk} for row in found.ranked],
        context_size, expected_documents, alternative,
    )
    if not ctx.retrieval_only:
        labels += failures.generation_labels(values, ctx.thresholds)
    labels += failures.dataset_labels(len(item.expected_sources or []), matching_rows, ctx.duplicates.get(item.item_id))
    usage = (state["result"].usage if state["result"] is not None else None) or {}
    return {
        "metrics": values, "metric_reasons": reasons, "failure_labels": labels,
        "retrieval_ms": state["retrieval_ms"], "generation_ms": state["generation_ms"], "judge_ms": state["judge_ms"],
        "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "_matching_rows": matching_rows,
    }


def _record(ctx, item, tracer, history, state, *, status, fields, error=None, stage=""):
    found, result = state["found"], state["result"]
    fields = {key: value for key, value in fields.items() if not key.startswith("_")}
    details = fields.get("details") or {}
    details.setdefault("query", {})["original"] = item.question
    cited = {source["citation_id"] for source in state["citations"] if source.get("cited")}
    candidates = [{**row, "cited": row["citation_id"] in cited} for row in (found.ranked if found else [])]
    rewrite_ms = state["rewrite_ms"]
    # Pipeline time: what a user would wait for. The diagnostic retrieval and
    # the judge are evaluation overhead (judge_ms is kept separately).
    total = sum(value for value in (rewrite_ms, state["retrieval_ms"], state["generation_ms"]) if value is not None)
    if status == RetrievalRun.Status.COMPLETED:
        fields["latency_ms"] = total
    run_kwargs = dict(
        user=ctx.experiment.workspace.user, workspace=ctx.experiment.workspace,
        source=RetrievalRun.Source.EVALUATION, status=status, query_original=item.question,
        query_rewritten=state["used"], rewrite_applied=state["applied"], rewrite_reason=state["reason"],
        error=error, error_stage=stage,
        provenance=_provenance(ctx, tracer, item, history, found.rerank if found else None,
                               (result.model or None) if result is not None else None,
                               getattr(result, "fallback", False) if result is not None else False),
        latency={"total": total, "rewrite": rewrite_ms,
                 "retrieval": state["retrieval_ms"], "rerank": found.rerank_ms if found else None,
                 "generation": state["generation_ms"], "first_token": state["first_token"]},
        usage=result.usage if result is not None else None,
        counts={"candidates": len(found.candidates) if found else 0, "context": len(found.sources) if found else 0,
                "cited": len(cited)},
        started_at=tracer.started_at, spans=tracer.export(), candidates=candidates,
        pipeline_version=ctx.version,
    )
    fields["details"] = details
    _save(ctx, item, run_kwargs=run_kwargs, fields=fields)


def _fail(experiment_id, token, error):
    Experiment.objects.filter(pk=experiment_id, run_token=token, status__in=(Status.QUEUED, Status.RUNNING)).update(
        status=Status.FAILED, run_token=None, error_code=(error.get("code") or "")[:80],
        error_message=error.get("message") or "", retryable=bool(error.get("retryable")),
        finished_at=timezone.now(), updated_at=timezone.now(),
    )


def finish(experiment_id, token):
    experiment = Experiment.objects.get(pk=experiment_id)
    items = list(experiment.items.all())
    if any(item.status == ItemStatus.PENDING for item in items):
        return False
    metrics = agg.aggregate(items, (experiment.config or {}).get("k_values") or DEFAULT_K_VALUES)
    return bool(Experiment.objects.filter(pk=experiment_id, status=Status.RUNNING, run_token=token).update(
        status=Status.COMPLETED, run_token=None, metrics=metrics, finished_at=timezone.now(), updated_at=timezone.now(),
        completed_count=sum(1 for item in items if item.status == ItemStatus.COMPLETED),
        failed_count=sum(1 for item in items if item.status == ItemStatus.FAILED),
    ))


def run_experiment(experiment_id, token):
    """Body of lab.tasks.run_experiment_task. True when this run completed the experiment."""
    try:
        token = uuid.UUID(str(token))
    except (TypeError, ValueError):
        return False
    began = time.monotonic()
    now = timezone.now()
    claimed = Experiment.objects.filter(pk=experiment_id, status=Status.QUEUED, run_token=token).update(
        status=Status.RUNNING, heartbeat_at=now, updated_at=now,
    )
    if not claimed:
        return False  # a duplicate delivery or a superseded token
    Experiment.objects.filter(pk=experiment_id, started_at=None).update(started_at=now)
    experiment = Experiment.objects.select_related("workspace", "workspace__user", "pipeline_version__pipeline").get(
        pk=experiment_id)
    try:
        ctx = prepare(experiment, token)
        experiment.refresh_from_db(fields=["index_versions", "warnings"])
        streak_code, streak = None, 0
        for item in experiment.items.exclude(status=ItemStatus.COMPLETED).order_by("position"):
            if not heartbeat(experiment_id, token):
                return False
            code = process_item(ctx, item)
            if code is None:
                streak_code, streak = None, 0
                continue
            streak = streak + 1 if code == streak_code else 1
            streak_code = code
            if streak >= CONSECUTIVE_FAILURE_LIMIT:
                failed = item.error_message or "Several items in a row failed the same way."
                _fail(experiment_id, token, {"code": code, "message": failed, "retryable": True})
                return False
        return finish(experiment_id, token)
    except LostOwnership:
        return False
    except ExperimentFatal as fatal:
        _fail(experiment_id, token, fatal.error)
        return False
    except Exception as exc:
        logger.warning("Experiment %s failed", experiment_id, exc_info=True)
        _status, error = describe_exception(exc)
        _fail(experiment_id, token, error)
        return False
    finally:
        Experiment.objects.filter(pk=experiment_id).update(
            runtime_ms=Coalesce(F("runtime_ms"), Value(0)) + _ms(began),
        )


def fail_timeout(experiment_id, token):
    _fail(experiment_id, uuid.UUID(str(token)), {
        "code": "experiment_timeout", "retryable": True,
        "message": "The experiment ran past the worker's time limit. Start it again to resume where it stopped.",
    })
