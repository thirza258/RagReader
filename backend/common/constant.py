"""Retrieval methods, models, and the pipeline configuration contract.

Every knob a pipeline reads is declared here, in one of two tiers, because the
two are not equally safe to change:

**Per-run (Tier A)** — the generation model, temperature, retrieval depth, the
hybrid fusion/rerank settings and the judge model. None of these touch the
stored index, so a deep-analysis run can vary them freely and two runs over the
same document stay comparable.

**Ingest-time (Tier B)** — the embedding model and the chunking strategy. These
*define* the index. `DocumentVector` is keyed by retrieval method alone and
`Chunk.config_hash` covers only the chunk settings, so nothing on record would
stop a query embedded with model B from being scored against vectors built with
model A — the cosine similarities would simply be meaningless, with no error
raised. Changing chunk settings is worse still: `_sync_chunks` deletes and
rebuilds every chunk, which cascades to the ground truth attached to them. So
Tier B is deployment configuration, applied once at ingest, and re-uploading is
how a document gets chunked or embedded differently.

Generation models are *not* an allowlist. Anything OpenRouter serves is
accepted as long as the id has the right shape; `LLM_MODELS` is the default
selection, not the permitted set. Retrieval methods and rerankers stay closed —
each method needs a pipeline class, and a reranker is a model this server
downloads and runs locally.

Environment reads below use `os.getenv` directly. That is safe because Django
loads `settings.py` (which calls `load_dotenv()`) before any app module imports
this one.
"""
import os
import re

RETRIEVAL_METHODS = [
    {"id": "Dense Retrieval", "label": "Dense", "description": "Semantic vector search over embeddings."},
    {"id": "Sparse Retrieval", "label": "Sparse", "description": "BM25 keyword search."},
    {"id": "Hybrid Retrieval", "label": "Hybrid", "description": "Dense + sparse candidates, reranked by a cross-encoder."},
]
METHOD_IDS = [m["id"] for m in RETRIEVAL_METHODS]

# The models a run selects when the client says nothing — "the big three".
# Any other OpenRouter id is equally runnable; these are just the defaults.
LLM_MODELS = [
    {"id": "openai/gpt-4o-mini", "label": "GPT-4o mini", "provider": "OpenAI"},
    {"id": "google/gemini-3-flash-preview", "label": "Gemini 3 Flash", "provider": "Google"},
    {"id": "anthropic/claude-haiku-4.5", "label": "Claude Haiku 4.5", "provider": "Anthropic"},
]
MODEL_IDS = [m["id"] for m in LLM_MODELS]

DEFAULT_CHAT_MODEL = MODEL_IDS[0]

# The single (method, model) pair that answers in the normal chat, and the one
# candidate pooling borrows when it needs a query rewriter.
DEFAULT_CHAT_VARIANT = {"method": METHOD_IDS[0], "model": DEFAULT_CHAT_MODEL}

# Every default method × every default model — the "run everything" matrix.
CONFIG_VARIANTS = [
    {"method": method, "model": model}
    for model in MODEL_IDS
    for method in METHOD_IDS
]


# ── Model ids ────────────────────────────────────────────────────────────────
# OpenRouter ids are `provider/model`, where the model half may carry a date
# suffix (`openai/gpt-4o-mini-2024-07-18`) or a routing variant (`:free`,
# `:nitro`). Shape is all we can check locally; OpenRouter is the authority on
# whether a model exists and says so in the error it returns.
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]*$")
MODEL_ID_MAX_LENGTH = 128


def is_valid_model_id(value) -> bool:
    """True if `value` has the shape of an OpenRouter model id."""
    return (
        isinstance(value, str)
        and 0 < len(value) <= MODEL_ID_MAX_LENGTH
        and bool(MODEL_ID_RE.match(value))
    )


# ── Tier A: per-run ──────────────────────────────────────────────────────────

# Retrieval depth. TOP_K_MAX is capped well below a typical document's chunk
# count so a runaway value can't turn every run into a full-corpus scan.
DEFAULT_TOP_K = 5
TOP_K_MIN = 1
TOP_K_MAX = 20

DEFAULT_TEMPERATURE = 0.0
TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 2.0

# How many candidates Hybrid's sub-engines feed the cross-encoder. Kept above
# the final depth so the reranker has something to actually rerank.
DEFAULT_CHILD_TOP_K = 10
CHILD_TOP_K_MIN = 1
CHILD_TOP_K_MAX = 50

# The RRF constant, both for Hybrid's score fusion and for candidate pooling.
DEFAULT_RRF_K = 60
RRF_K_MIN = 1
RRF_K_MAX = 1000

# Reranking is served by Ollama, which holds the model and manages GPU/CPU
# itself. Unlike a generation model this one is not reached through OpenRouter,
# so the set is closed: an arbitrary string would name a model the local Ollama
# has probably never pulled. Add an entry here to offer another.
DEFAULT_OLLAMA_EMBED_MODEL = os.getenv("RAG_OLLAMA_EMBED_MODEL", "nomic-embed-text")

RERANKER_MODELS = [
    {
        "id": "nomic-embed-text",
        "label": "Nomic Embed Text",
        "description": "The default. Ollama embeds query and candidates, then ranks by cosine similarity.",
    },
    {
        "id": "mxbai-embed-large",
        "label": "MxBai Embed Large",
        "description": "Larger embeddings, slower, usually a little sharper. Requires `ollama pull mxbai-embed-large`.",
    },
    {
        "id": "bge-m3",
        "label": "BGE-M3 (multilingual)",
        "description": "Stronger on non-English text. Requires `ollama pull bge-m3`.",
    },
]
RERANKER_MODEL_IDS = [m["id"] for m in RERANKER_MODELS]

# Keep the environment's choice selectable even when it is not one of the three
# above, so RAG_OLLAMA_EMBED_MODEL can name any model the local Ollama has.
if DEFAULT_OLLAMA_EMBED_MODEL not in RERANKER_MODEL_IDS:
    RERANKER_MODELS.insert(0, {
        "id": DEFAULT_OLLAMA_EMBED_MODEL,
        "label": DEFAULT_OLLAMA_EMBED_MODEL,
        "description": "Configured by RAG_OLLAMA_EMBED_MODEL.",
    })
    RERANKER_MODEL_IDS = [m["id"] for m in RERANKER_MODELS]

DEFAULT_RERANKER_MODEL = DEFAULT_OLLAMA_EMBED_MODEL

# The model that scores faithfulness, answer relevance and answer coverage.
# Any OpenRouter id works; it is a normal chat completion under the hood.
DEFAULT_JUDGE_MODEL = os.getenv("RAG_JUDGE_MODEL", "mistralai/mistral-nemo")

# Ground-truth strategies, mirrored by GroundTruthChunk.Source.
GROUND_TRUTH_MODES = [
    {
        "id": "manual",
        "label": "Manual selection",
        "description": "You pick the chunks that should count as relevant.",
    },
    {
        "id": "pooled",
        "label": "Candidate pooling (RRF)",
        "description": "Run the query through every retrieval method and fuse the rankings with Reciprocal Rank Fusion.",
    },
]
GROUND_TRUTH_MODE_IDS = [m["id"] for m in GROUND_TRUTH_MODES]

# How deep the fused candidate pool goes when ground_truth_mode is "pooled".
# Deliberately above DEFAULT_TOP_K: if the pool were the same depth as a single
# run's output, the ground truth would be close to a copy of that run and the
# retrieval metrics would flatter it.
DEFAULT_POOL_TOP_N = 10
POOL_TOP_N_MIN = 1
POOL_TOP_N_MAX = 50

# The cost guard. One variant is one full retrieve-generate-judge cycle, so the
# matrix has to be bounded — with an open model list, "select all" would
# otherwise be an unbounded bill.
MAX_VARIANTS = max(1, int(os.getenv("RAG_MAX_VARIANTS", "12")))

# How many models the defaults can pre-select without exceeding the cap. At the
# default of 12 this is 4, so all three shipped models fit; lowering the cap
# narrows the defaults too, rather than letting the sidebar advertise a
# selection the server would silently trim.
DEFAULT_MODEL_LIMIT = max(1, MAX_VARIANTS // len(METHOD_IDS))


# ── Tier B: ingest-time ──────────────────────────────────────────────────────
# Set these in the environment; they take effect for documents indexed after
# the change. See the module docstring for why they are not per-run.

DEFAULT_EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "openai/text-embedding-3-small")
DEFAULT_CHUNK_STRATEGY = os.getenv("RAG_CHUNK_STRATEGY", "fixed")
DEFAULT_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "512"))
DEFAULT_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "50"))
DEFAULT_VECTOR_STORE_PATH = os.getenv("RAG_VECTOR_STORE_PATH", "./vector_stores")

CHUNK_STRATEGIES = ["fixed", "paragraph", "semantic"]

INGEST_CONFIG = {
    "embedding_model": DEFAULT_EMBEDDING_MODEL,
    "chunk_strategy": DEFAULT_CHUNK_STRATEGY,
    "chunk_size": DEFAULT_CHUNK_SIZE,
    "overlap": DEFAULT_CHUNK_OVERLAP,
    "vector_store_path": DEFAULT_VECTOR_STORE_PATH,
}


DEFAULT_ANALYSIS_CONFIG = {
    "methods": METHOD_IDS,
    "models": MODEL_IDS[:DEFAULT_MODEL_LIMIT],
    "top_k": DEFAULT_TOP_K,
    "ground_truth_mode": "manual",
    "pool_top_n": DEFAULT_POOL_TOP_N,
    "temperature": DEFAULT_TEMPERATURE,
    "child_top_k": DEFAULT_CHILD_TOP_K,
    "rrf_k": DEFAULT_RRF_K,
    "reranker_model": DEFAULT_RERANKER_MODEL,
    "judge_model": DEFAULT_JUDGE_MODEL,
}

# The keys that change how a pipeline is *built* (as opposed to how deep it
# retrieves, which `apply_retrieval_depth` sets per call). Two configs that
# agree on these can share one cached engine.
PIPELINE_SHAPING_KEYS = (
    "llm_model",
    "temperature",
    "embedding_model",
    "child_top_k",
    "rrf_k",
    "reranker_model",
    "chunk_strategy",
    "chunk_size",
    "overlap",
    "vector_store_path",
)


def _clamped_int(raw, default: int, minimum: int, maximum: int) -> int:
    """Coerce to int and clamp to range; non-numeric input takes `default`."""
    try:
        return max(minimum, min(maximum, int(raw)))
    except (TypeError, ValueError):
        return default


def _clamped_float(raw, default: float, minimum: float, maximum: float) -> float:
    """Coerce to float and clamp to range; non-numeric input takes `default`."""
    try:
        return max(minimum, min(maximum, float(raw)))
    except (TypeError, ValueError):
        return default


def _clean_selection(raw, allowed, fallback):
    """Keep only recognised ids, de-duplicated and in `allowed` order."""
    if not isinstance(raw, (list, tuple, set)):
        return list(fallback)
    chosen = {str(item) for item in raw}
    kept = [item for item in allowed if item in chosen]
    return kept or list(fallback)


def _clean_models(raw, fallback):
    """Keep well-formed model ids in the order the client sent them.

    Unlike methods, models are not checked against an allowlist — the point of
    the selector is that any OpenRouter model can be run. Order is preserved
    because it is what `MAX_VARIANTS` trims from the end of.
    """
    if not isinstance(raw, (list, tuple)):
        return list(fallback)
    kept = list(dict.fromkeys(item for item in raw if is_valid_model_id(item)))
    return kept or list(fallback)


def _clean_choice(raw, allowed, default):
    return raw if raw in allowed else default


def normalize_analysis_config(raw: dict | None) -> dict:
    """Validate a client-supplied analysis config, filling in defaults.

    Unknown methods are dropped rather than rejected: the sidebar is a
    convenience, and a stale option in the browser should narrow the run, not
    fail it. An empty selection falls back to the defaults. The model list is
    then trimmed so `methods × models` never exceeds `MAX_VARIANTS`.

    Configs stored before a key existed (an older `AnalysisBatch.config`) come
    back with that key filled from the defaults, so old batches keep replaying.
    """
    raw = raw if isinstance(raw, dict) else {}

    methods = _clean_selection(raw.get("methods"), METHOD_IDS, METHOD_IDS)
    models = _clean_models(raw.get("models"), MODEL_IDS)

    # Trim from the end of the model list: methods are a closed set of three,
    # so models are the axis that can grow without bound.
    max_models = max(1, MAX_VARIANTS // len(methods))
    models = models[:max_models]

    return {
        "methods": methods,
        "models": models,
        "top_k": _clamped_int(raw.get("top_k"), DEFAULT_TOP_K, TOP_K_MIN, TOP_K_MAX),
        "ground_truth_mode": _clean_choice(
            raw.get("ground_truth_mode"),
            GROUND_TRUTH_MODE_IDS,
            DEFAULT_ANALYSIS_CONFIG["ground_truth_mode"],
        ),
        "pool_top_n": _clamped_int(
            raw.get("pool_top_n"), DEFAULT_POOL_TOP_N, POOL_TOP_N_MIN, POOL_TOP_N_MAX
        ),
        "temperature": _clamped_float(
            raw.get("temperature"), DEFAULT_TEMPERATURE, TEMPERATURE_MIN, TEMPERATURE_MAX
        ),
        "child_top_k": _clamped_int(
            raw.get("child_top_k"), DEFAULT_CHILD_TOP_K, CHILD_TOP_K_MIN, CHILD_TOP_K_MAX
        ),
        "rrf_k": _clamped_int(raw.get("rrf_k"), DEFAULT_RRF_K, RRF_K_MIN, RRF_K_MAX),
        "reranker_model": _clean_choice(
            raw.get("reranker_model"), RERANKER_MODEL_IDS, DEFAULT_RERANKER_MODEL
        ),
        "judge_model": (
            raw.get("judge_model")
            if is_valid_model_id(raw.get("judge_model"))
            else DEFAULT_JUDGE_MODEL
        ),
    }


def build_variants(config: dict | None) -> list[dict]:
    """Expand a normalized config into the {method, model} variant list."""
    config = normalize_analysis_config(config)
    return [
        {"method": method, "model": model}
        for model in config["models"]
        for method in config["methods"]
    ]


def build_pipeline_config(config: dict | None = None, model: str | None = None) -> dict:
    """The constructor argument for a pipeline, from an analysis config.

    Merges the ingest-time defaults (Tier B) with the per-run choices (Tier A)
    into the flat dict every pipeline and RAG engine reads. `model` names the
    generation LLM for this variant; without it the chat default is used.
    """
    config = normalize_analysis_config(config)
    return {
        **INGEST_CONFIG,
        # DenseRAG historically read the embedding model from "model"; both
        # keys are set so either spelling resolves to the same thing.
        "model": INGEST_CONFIG["embedding_model"],
        "llm_model": model if is_valid_model_id(model) else DEFAULT_CHAT_MODEL,
        "temperature": config["temperature"],
        "top_k": config["top_k"],
        "child_top_k": config["child_top_k"],
        "rrf_k": config["rrf_k"],
        "reranker_model": config["reranker_model"],
        "judge_model": config["judge_model"],
    }
