"""Retrieval pipelines: configuration, validation and versioning (PRD §17–20).

A pipeline's configuration is stored as immutable `PipelineVersion` rows.
Editing a pipeline validates the merged configuration and, when it differs
from the latest version (by hash), adds version n + 1; nothing ever changes a
saved version. A conversation names a pipeline (null = the workspace default)
and every question runs with that pipeline's latest version *at question
time*, recorded on the answer, its retrieval run and the run's provenance.

Every workspace gets a default pipeline on first need, whose version 1 is
Phase 1 chat exactly: dense retrieval, CHAT_CANDIDATE_K candidates,
CHAT_CONTEXT_K sources, the chat model at DEFAULT_TEMPERATURE.

The embedding model is not free to choose: indexes are built at ingest time
with `INGEST_CONFIG["embedding_model"]`, and a query embedded with any other
model would be compared against vectors from a different space (meaningless
similarities, no error). So configurations must name that model, and a
question is refused when a document in scope was indexed with another one.
"""
import hashlib
import json
import math

from django.db import IntegrityError, transaction
from django.db.models import Max

from common.constant import (
    CHAT_CANDIDATE_K, CHAT_CONTEXT_K, CHAT_PROMPT_VERSION, CHILD_TOP_K_MAX, CHILD_TOP_K_MIN,
    DEFAULT_CHAT_MODEL, DEFAULT_FUSION_METHOD, DEFAULT_HYBRID_WEIGHT, DEFAULT_LLM_RERANKER_MODEL,
    DEFAULT_PIPELINE_STRATEGY, DEFAULT_RERANKER_MODEL, DEFAULT_RRF_K, DEFAULT_TEMPERATURE, FUSION_METHOD_IDS,
    FUSION_METHODS, HYBRID_WEIGHT_MAX, HYBRID_WEIGHT_MIN, INGEST_CONFIG, LLM_MODELS, PIPELINE_STRATEGIES,
    PIPELINE_STRATEGY_IDS, RERANKER_MODEL_IDS, RERANKER_MODELS, RERANKER_PROVIDER_IDS, RERANKER_PROVIDERS,
    RRF_K_MAX, RRF_K_MIN, TEMPERATURE_MAX, TEMPERATURE_MIN, TOP_K_MAX, TOP_K_MIN, is_valid_model_id,
)
from workspace.errors import ApiError
from workspace.models import DEFAULT_PIPELINE_NAME, Pipeline, PipelineVersion

# Every version stores all of these, so a version alone reproduces a run.
CONFIG_KEYS = (
    "strategy", "fusion", "hybrid_weight", "rrf_k", "candidate_k", "top_k", "reranker",
    "generation_model", "temperature", "prompt_version", "embedding_model",
)
DENSE_STRATEGIES = {"dense", "hybrid", "hybrid_rerank"}
BM25_STRATEGIES = {"bm25", "hybrid", "hybrid_rerank"}
FUSION_STRATEGIES = {"hybrid", "hybrid_rerank"}
RERANK_STRATEGIES = {"hybrid_rerank"}
PROMPT_VERSIONS = (CHAT_PROMPT_VERSION,)
MAX_NAME_CHARS = 120

RANGES = {
    "candidate_k": {"min": CHILD_TOP_K_MIN, "max": CHILD_TOP_K_MAX},
    "top_k": {"min": TOP_K_MIN, "max": TOP_K_MAX},
    "rrf_k": {"min": RRF_K_MIN, "max": RRF_K_MAX},
    "hybrid_weight": {"min": HYBRID_WEIGHT_MIN, "max": HYBRID_WEIGHT_MAX},
    "temperature": {"min": TEMPERATURE_MIN, "max": TEMPERATURE_MAX},
}


def ingest_embedding_model():
    """The model every index is built with (Tier B, deployment configuration)."""
    return INGEST_CONFIG["embedding_model"]


def default_reranker():
    return {"provider": "ollama", "model": DEFAULT_RERANKER_MODEL}


def default_config():
    """Phase 1 chat as a pipeline configuration."""
    return {
        "strategy": DEFAULT_PIPELINE_STRATEGY,
        "fusion": DEFAULT_FUSION_METHOD,
        "hybrid_weight": DEFAULT_HYBRID_WEIGHT,
        "rrf_k": DEFAULT_RRF_K,
        "candidate_k": CHAT_CANDIDATE_K,
        "top_k": CHAT_CONTEXT_K,
        "reranker": None,
        "generation_model": DEFAULT_CHAT_MODEL,
        "temperature": DEFAULT_TEMPERATURE,
        "prompt_version": CHAT_PROMPT_VERSION,
        "embedding_model": ingest_embedding_model(),
    }


def config_hash(config):
    """sha256 of the canonical JSON (sorted keys, no whitespace)."""
    canonical = json.dumps({key: config.get(key) for key in CONFIG_KEYS}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Validation ───────────────────────────────────────────────────────────────

def _integer(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _check_int(errors, key, value):
    number, bounds = _integer(value), RANGES[key]
    if number is None:
        errors[key] = ["Enter a whole number."]
    elif not bounds["min"] <= number <= bounds["max"]:
        errors[key] = [f"Must be between {bounds['min']} and {bounds['max']}."]
    return number


def _check_float(errors, key, value):
    number, bounds = _number(value), RANGES[key]
    if number is None:
        errors[key] = ["Enter a number."]
        return None
    if not bounds["min"] <= number <= bounds["max"]:
        errors[key] = [f"Must be between {bounds['min']:g} and {bounds['max']:g}."]
        return None
    return round(number, 4)


def _check_reranker(errors, value):
    if not isinstance(value, dict) or set(value) - {"provider", "model"}:
        errors["reranker"] = ['Expected {"provider": "ollama" | "llm", "model": "…"} or null.']
        return None
    provider, model = value.get("provider"), value.get("model")
    if provider not in RERANKER_PROVIDER_IDS:
        errors["reranker"] = [f"Unknown reranker provider. Choose one of: {', '.join(RERANKER_PROVIDER_IDS)}."]
        return None
    if provider == "ollama":
        if model in (None, ""):
            model = DEFAULT_RERANKER_MODEL
        if isinstance(model, str) and model.startswith("ollama/"):
            model = model[len("ollama/"):]
        if model not in RERANKER_MODEL_IDS:
            errors["reranker"] = [f"Unknown Ollama reranker model. Choose one of: {', '.join(RERANKER_MODEL_IDS)}."]
            return None
    else:
        if model in (None, ""):
            model = DEFAULT_LLM_RERANKER_MODEL
        if not is_valid_model_id(model):
            errors["reranker"] = ["The LLM reranker needs an OpenRouter model id such as 'openai/gpt-4o-mini'."]
            return None
    return {"provider": provider, "model": model}


def normalize_config(changes, base=None):
    """The full configuration `base` + `changes`, validated.

    `changes` holds any subset of CONFIG_KEYS; `base` defaults to
    `default_config()`. Raises ApiError(invalid_request) with one message per
    field (`details["config.<key>"]`). A reranker belongs to `hybrid_rerank`
    only: switching away from it drops the base's reranker, switching to it
    without naming one picks the default Ollama reranker, and naming one for
    another strategy is an error.
    """
    if changes is None:
        changes = {}
    if not isinstance(changes, dict):
        raise _invalid({"config": ["Expected an object of pipeline settings."]})
    errors = {}
    unknown = sorted(str(key) for key in changes if key not in CONFIG_KEYS)
    for key in unknown:
        errors[key] = ["Unknown setting."]
    merged = {**(base or default_config()), **{key: value for key, value in changes.items() if key in CONFIG_KEYS}}
    config = {}

    strategy = merged.get("strategy")
    if strategy not in PIPELINE_STRATEGY_IDS:
        errors["strategy"] = [f"Choose one of: {', '.join(PIPELINE_STRATEGY_IDS)}."]
    config["strategy"] = strategy
    fusion = merged.get("fusion")
    if fusion not in FUSION_METHOD_IDS:
        errors["fusion"] = [f"Choose one of: {', '.join(FUSION_METHOD_IDS)}."]
    config["fusion"] = fusion
    config["hybrid_weight"] = _check_float(errors, "hybrid_weight", merged.get("hybrid_weight"))
    config["rrf_k"] = _check_int(errors, "rrf_k", merged.get("rrf_k"))
    config["candidate_k"] = _check_int(errors, "candidate_k", merged.get("candidate_k"))
    config["top_k"] = _check_int(errors, "top_k", merged.get("top_k"))
    if "candidate_k" not in errors and "top_k" not in errors and config["top_k"] > config["candidate_k"]:
        errors["top_k"] = ["The final top-k cannot be larger than the candidate top-k."]

    reranker = merged.get("reranker")
    if strategy in RERANK_STRATEGIES:
        if reranker is None:
            if "reranker" in changes:
                errors["reranker"] = ["The hybrid_rerank strategy needs a reranker."]
            else:
                reranker = default_reranker()
        if reranker is not None:
            reranker = _check_reranker(errors, reranker)
    else:
        if "reranker" in changes and changes["reranker"] is not None:
            errors["reranker"] = ["Only the hybrid_rerank strategy uses a reranker; send null or switch strategy."]
        reranker = None
    config["reranker"] = reranker

    generation_model = merged.get("generation_model")
    if not is_valid_model_id(generation_model):
        errors["generation_model"] = ["Expected an OpenRouter model id such as 'openai/gpt-4o-mini'."]
    config["generation_model"] = generation_model
    config["temperature"] = _check_float(errors, "temperature", merged.get("temperature"))
    prompt_version = merged.get("prompt_version")
    if prompt_version not in PROMPT_VERSIONS:
        errors["prompt_version"] = [f"Choose one of: {', '.join(PROMPT_VERSIONS)}."]
    config["prompt_version"] = prompt_version
    embedding_model = merged.get("embedding_model")
    if embedding_model != ingest_embedding_model():
        errors["embedding_model"] = [
            f"Documents are indexed with {ingest_embedding_model()}, so a pipeline must embed questions with it too. "
            "Other embedding models need their own index (set at ingest time)."
        ]
    config["embedding_model"] = embedding_model

    if errors:
        raise _invalid({f"config.{key}" if key in CONFIG_KEYS or key in unknown else key: value for key, value in errors.items()})
    return config


def _invalid(details):
    return ApiError("invalid_request", "The pipeline configuration is not valid.", details=details)


def clean_name(value, *, required):
    name = " ".join(str(value or "").split())
    if not name:
        if required:
            raise ApiError("invalid_request", "The request contains invalid or missing fields.",
                           details={"name": ["This field may not be blank."]})
        return None
    if len(name) > MAX_NAME_CHARS:
        raise ApiError("invalid_request", "The request contains invalid or missing fields.",
                       details={"name": [f"Ensure this field has no more than {MAX_NAME_CHARS} characters."]})
    return name


# ── Versions ─────────────────────────────────────────────────────────────────

def _add_version(pipeline, config):
    """Version n + 1 of `pipeline`. Call inside a transaction holding its row lock."""
    number = (pipeline.versions.aggregate(top=Max("number"))["top"] or 0) + 1
    return PipelineVersion.objects.create(pipeline=pipeline, number=number, config=config, config_hash=config_hash(config))


def latest_version(pipeline):
    version = pipeline.versions.order_by("-number").first()
    if version is None:  # every pipeline is created with v1; repair if not
        with transaction.atomic():
            locked = Pipeline.objects.select_for_update().get(pk=pipeline.pk)
            version = locked.versions.order_by("-number").first() or _add_version(locked, default_config())
    return version


def default_pipeline_for(workspace):
    """The workspace's default pipeline, created (with v1 = Phase 1) on first need."""
    pipeline = Pipeline.objects.filter(workspace=workspace, is_default=True).first()
    if pipeline is not None:
        return pipeline
    try:
        # A savepoint keeps a lost race from poisoning the caller's transaction.
        with transaction.atomic():
            pipeline = Pipeline.objects.create(workspace=workspace, name=DEFAULT_PIPELINE_NAME, is_default=True)
            _add_version(pipeline, default_config())
    except IntegrityError:
        pass  # A concurrent request created it; the constraint keeps it unique.
    return Pipeline.objects.get(workspace=workspace, is_default=True)


def create_pipeline(workspace, name, changes=None):
    config = normalize_config(changes)
    default_pipeline_for(workspace)  # the default exists before any other pipeline
    with transaction.atomic():
        pipeline = Pipeline.objects.create(workspace=workspace, name=name, is_default=False)
        version = _add_version(pipeline, config)
    return pipeline, version


def update_pipeline(pipeline, *, name=None, changes=None):
    """(pipeline, latest version, whether a version was added).

    A configuration identical to the latest version (same hash) adds nothing;
    a rename alone adds nothing either: versions are about behaviour.
    """
    with transaction.atomic():
        locked = Pipeline.objects.select_for_update().get(pk=pipeline.pk)
        latest = latest_version(locked)
        created = False
        if changes is not None:
            config = normalize_config(changes, base=latest.config)
            if config_hash(config) != latest.config_hash:
                latest, created = _add_version(locked, config), True
        if name is not None:
            locked.name = name
        locked.save()
    return locked, latest, created


def pipeline_in_workspace(workspace, pipeline_id, field="pipeline_id"):
    """A pipeline of `workspace`, or 400 — the same for other workspaces, users and unknown ids."""
    pipeline = Pipeline.objects.filter(pk=pipeline_id, workspace=workspace).first() if pipeline_id else None
    if pipeline is None:
        raise ApiError("invalid_request", "The request contains invalid or missing fields.",
                       details={field: [f"Pipeline {pipeline_id} is not in this workspace."]})
    return pipeline


def session_pipeline(session):
    """(pipeline, latest version) a question in `session` runs with now."""
    pipeline = session.pipeline if session.pipeline_id else None
    if pipeline is None or pipeline.workspace_id != session.workspace_id:
        pipeline = default_pipeline_for(session.workspace)
    return pipeline, latest_version(pipeline)


def check_documents(version, documents):
    """Refuse a question whose documents were indexed with another embedding model.

    Documents that never recorded their model (backfilled legacy rows) are
    let through: loading their index checks the model stamp in the file.
    """
    config = version.config
    if config.get("strategy") not in DENSE_STRATEGIES:
        return
    wanted = config.get("embedding_model")
    for document in documents:
        indexed_with = (document.metadata or {}).get("embedding_model")
        if indexed_with and indexed_with != wanted:
            raise ApiError(
                "embedding_model_mismatch",
                f"“{document.name}” is indexed with {indexed_with}, but the pipeline “{version.pipeline.name}” "
                f"embeds questions with {wanted}. Re-index the document or choose another pipeline.",
                status=409,
            )


def snapshot(version):
    """What provenance records about the pipeline (survives the pipeline's deletion)."""
    if version is None:
        return None
    return {
        "pipeline_id": version.pipeline_id,
        "name": version.pipeline.name,
        "version_id": version.pk,
        "version": version.number,
        "config": version.config,
        "config_hash": version.config_hash,
    }


def options():
    """Everything a client needs to build and validate a pipeline form."""
    return {
        "strategies": PIPELINE_STRATEGIES,
        "fusion_methods": FUSION_METHODS,
        "reranker_providers": [
            {**provider, "models": RERANKER_MODELS if provider["id"] == "ollama" else LLM_MODELS,
             "default_model": DEFAULT_RERANKER_MODEL if provider["id"] == "ollama" else DEFAULT_LLM_RERANKER_MODEL}
            for provider in RERANKER_PROVIDERS
        ],
        "generation_models": LLM_MODELS,
        "embedding_models": [ingest_embedding_model()],
        "prompt_versions": list(PROMPT_VERSIONS),
        "ranges": RANGES,
        "defaults": default_config(),
        "default_reranker": default_reranker(),
        "keys": list(CONFIG_KEYS),
    }
