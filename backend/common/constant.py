"""Retrieval methods, LLMs, and the deep-analysis configuration contract.

CONFIG_VARIANTS is the full matrix (every method × every model) and stays the
default for a deep-analysis run. A user can narrow it from the Deep Analysis
sidebar; `normalize_analysis_config` validates whatever they send and
`build_variants` turns it back into the same list-of-dicts shape.
"""

RETRIEVAL_METHODS = [
    {"id": "Dense Retrieval", "label": "Dense", "description": "Semantic vector search over embeddings."},
    {"id": "Sparse Retrieval", "label": "Sparse", "description": "BM25 keyword search."},
    {"id": "Hybrid Retrieval", "label": "Hybrid", "description": "Dense + sparse candidates, reranked by a cross-encoder."},
]

LLM_MODELS = [
    {"id": "openai/gpt-4o-mini", "label": "GPT-4o mini", "provider": "OpenAI"},
    {"id": "google/gemini-3-flash-preview", "label": "Gemini 3 Flash", "provider": "Google"},
    {"id": "anthropic/claude-haiku-4.5", "label": "Claude Haiku 4.5", "provider": "Anthropic"},
]

METHOD_IDS = [m["id"] for m in RETRIEVAL_METHODS]
MODEL_IDS = [m["id"] for m in LLM_MODELS]

# Every method × every model — the default "run everything" matrix.
CONFIG_VARIANTS = [
    {"method": method, "model": model}
    for model in MODEL_IDS
    for method in METHOD_IDS
]

# Retrieval depth. TOP_K_MAX is capped well below a typical document's chunk
# count so a runaway value can't turn every run into a full-corpus scan.
DEFAULT_TOP_K = 5
TOP_K_MIN = 1
TOP_K_MAX = 20

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

DEFAULT_ANALYSIS_CONFIG = {
    "methods": METHOD_IDS,
    "models": MODEL_IDS,
    "top_k": DEFAULT_TOP_K,
    "ground_truth_mode": "manual",
    "pool_top_n": DEFAULT_POOL_TOP_N,
}


def _clamped_int(raw, default: int, minimum: int, maximum: int) -> int:
    """Coerce to int and clamp to range; non-numeric input takes `default`."""
    try:
        return max(minimum, min(maximum, int(raw)))
    except (TypeError, ValueError):
        return default


def _clean_selection(raw, allowed, fallback):
    """Keep only recognised ids, de-duplicated and in `allowed` order."""
    if not isinstance(raw, (list, tuple, set)):
        return list(fallback)
    chosen = {str(item) for item in raw}
    kept = [item for item in allowed if item in chosen]
    return kept or list(fallback)


def normalize_analysis_config(raw: dict | None) -> dict:
    """Validate a client-supplied analysis config, filling in defaults.

    Unknown methods/models are dropped rather than rejected: the sidebar is a
    convenience, and a stale option in the browser should narrow the run, not
    fail it. An empty selection falls back to the full matrix.
    """
    raw = raw if isinstance(raw, dict) else {}

    mode = raw.get("ground_truth_mode", DEFAULT_ANALYSIS_CONFIG["ground_truth_mode"])
    if mode not in GROUND_TRUTH_MODE_IDS:
        mode = DEFAULT_ANALYSIS_CONFIG["ground_truth_mode"]

    return {
        "methods": _clean_selection(raw.get("methods"), METHOD_IDS, METHOD_IDS),
        "models": _clean_selection(raw.get("models"), MODEL_IDS, MODEL_IDS),
        "top_k": _clamped_int(raw.get("top_k"), DEFAULT_TOP_K, TOP_K_MIN, TOP_K_MAX),
        "ground_truth_mode": mode,
        "pool_top_n": _clamped_int(
            raw.get("pool_top_n"), DEFAULT_POOL_TOP_N, POOL_TOP_N_MIN, POOL_TOP_N_MAX
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
